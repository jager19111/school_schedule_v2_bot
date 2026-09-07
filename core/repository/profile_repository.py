# core/repository/profile_repository.py
from __future__ import annotations
import secrets
from datetime import datetime, timedelta, timezone
import aiosqlite
import logging
import uuid
from typing import Optional, List, Dict, Any

from core.repository.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class ProfileRepository(BaseRepository):
    """
    Репозиторий профилей пользователей и семей.

    Вся работа с таблицами users и families сосредоточена здесь.
    """

    # users.last_active_at / created_at / updated_at и fetched_at уже покрываются BaseRepository

    # ========== USERS ==========

    async def register_user_initial(self, user_id: int) -> None:
        """
        Создаёт пользователя, если его нет, и проставляет last_active_at.
        """
        async with self._connection() as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
                (user_id,),
            )
            await db.execute(
                "UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()
# Возможно нужно удалить дублирующий метод update_user_role, так как он уже есть в ProfileService.
    async def update_user_role(self, user_id: int, role: str) -> None:
        """
        Обновляет роль пользователя.
        """
        await self._execute(
            "UPDATE users SET role = ? WHERE user_id = ?",
            (role, user_id),
        )

    async def update_last_active(self, user_id: int) -> None:
        """
        Обновляет last_active_at.
        """
        await self._execute(
            "UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,),
        )

    async def get_user_row(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Возвращает полную строку пользователя как dict.
        """
        return await self._fetch_one(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        )

    async def get_user_profile_for_dto(
        self,
        user_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Возвращает поля, необходимые для UserProfileDTO."""
        return await self._fetch_one(
            """
            SELECT
                user_id,
                role,
                name,
                class_id,
                group_id,
                family_id,
                morning_summary_time,
                pre_lesson_offset_minutes,
                receive_schedule_changes,
                receive_extra_class_reminders,
                can_manage_own_extra_classes,
                changes_window_days,
                is_notifications_enabled,
                global_extra_reminder
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        )

    async def set_child_class_and_group(self, user_id: int, class_id: str, group_id: str) -> None:
        """
        Задаёт класс и группу ребёнка.
        """
        await self._execute(
            "UPDATE users SET class_id = ?, group_id = ? WHERE user_id = ?",
            (class_id, group_id, user_id),
        )
    
    async def _ensure_parent_child_settings_for_family(
        self,
        db: aiosqlite.Connection,
        family_id: int,
    ) -> None:
        """
        Создаёт недостающие связи взрослый → ребёнок для одной семьи.

        Все parent и observer семьи получают самостоятельную строку настроек
        для каждого child. INSERT OR IGNORE безопасен при повторном вызове:
        PRIMARY KEY(parent_id, child_id) исключает дубли.
        """
        await db.execute(
            """
            INSERT OR IGNORE INTO parent_child_settings (
                parent_id,
                child_id,
                can_manage_extra_classes
            )
            SELECT
                adult.user_id,
                child.user_id,
                CASE
                    WHEN adult.role = 'parent' THEN 1
                    ELSE 0
                END
            FROM users AS adult
            JOIN users AS child
              ON child.family_id = adult.family_id
            WHERE adult.family_id = ?
              AND adult.role IN ('parent', 'observer')
              AND child.role = 'child'
            """,
            (family_id,),
        )

    async def _ensure_parent_student_settings_for_family(
        self,
        *,
        db: aiosqlite.Connection,
        family_id: int,
    ) -> None:
        """
        Создаёт недостающие связи adult → student profile.

        Вызывается при вступлении нового parent/observer в семью.

        Parent:
        - может управлять допзанятиями по умолчанию.

        Observer:
        - видит student profiles и получает subscriptions;
        - не может редактировать кружки по умолчанию.
        """
        await db.execute(
            """
            INSERT OR IGNORE INTO parent_student_settings (
                parent_user_id,
                student_id,

                receive_morning_summary,
                receive_pre_lesson_reminders,
                receive_schedule_changes,
                receive_extra_class_reminders,

                child_notification_settings_locked,
                can_manage_extra_classes
            )
            SELECT
                adult.user_id,
                student.id,

                1,
                1,
                1,
                1,

                0,

                CASE
                    WHEN adult.role = 'parent' THEN 1
                    ELSE 0
                END

            FROM users AS adult
            JOIN student_profiles AS student
                ON student.family_id = adult.family_id

            WHERE adult.family_id = ?
            AND adult.role IN ('parent', 'observer')
            AND student.is_active = 1
            """,
            (family_id,),
        )
            
    # ========== FAMILIES ==========

    async def is_family_admin(
        self,
        user_id: int,
        family_id: int,
    ) -> bool:
        """
        Проверяет, является ли пользователь администратором конкретной семьи.
        """
        row = await self._fetch_one(
            """
            SELECT 1 AS is_admin
            FROM families
            WHERE id = ?
              AND admin_user_id = ?
            """,
            (family_id, user_id),
        )

        return row is not None
 
    async def create_family_invite(
        self,
        *,
        family_id: int,
        created_by_user_id: int,
        intended_role: str,
        expires_in_hours: int = 24,
        max_uses: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        Создаёт одноразовое приглашение с фиксированной ролью.

        Только family admin может выпускать invite.
        """
        allowed_roles = {
            "child",
            "parent",
            "observer",
        }

        if intended_role not in allowed_roles:
            raise ValueError(
                f"Unsupported invite role: {intended_role}"
            )

        if not 1 <= max_uses <= 10:
            raise ValueError(
                "max_uses must be in range 1..10"
            )

        if not 1 <= expires_in_hours <= 168:
            raise ValueError(
                "expires_in_hours must be in range 1..168"
            )

        is_admin = await self.is_family_admin(
            user_id=created_by_user_id,
            family_id=family_id,
        )

        if not is_admin:
            return None

        token = secrets.token_urlsafe(24)

        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(hours=expires_in_hours)
        ).strftime("%Y-%m-%d %H:%M:%S")

        async with self._connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO family_invites (
                    token,
                    family_id,
                    created_by_user_id,
                    intended_role,
                    expires_at,
                    max_uses
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    token,
                    family_id,
                    created_by_user_id,
                    intended_role,
                    expires_at,
                    max_uses,
                ),
            )

            await db.commit()

            invite_id = cursor.lastrowid

        return await self._fetch_one(
            """
            SELECT
                id,
                token,
                family_id,
                intended_role,
                expires_at,
                max_uses,
                uses_count,
                is_revoked,
                created_at
            FROM family_invites
            WHERE id = ?
            """,
            (invite_id,),
        )

    async def get_valid_family_invite(
        self,
        token: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает активное invite, которое можно использовать.

        Проверяет:
        - invite не отозван;
        - срок не истёк;
        - uses_count меньше max_uses;
        - семья ещё существует.
        """
        return await self._fetch_one(
            """
            SELECT
                invite.id,
                invite.token,
                invite.family_id,
                invite.intended_role,
                invite.expires_at,
                invite.max_uses,
                invite.uses_count,
                invite.is_revoked,

                family.family_code,
                family.admin_user_id
            FROM family_invites AS invite
            JOIN families AS family
              ON family.id = invite.family_id
            WHERE invite.token = ?
              AND invite.is_revoked = 0
              AND invite.expires_at > CURRENT_TIMESTAMP
              AND invite.uses_count < invite.max_uses
            """,
            (token,),
        )

    async def consume_family_invite(
        self,
        *,
        token: str,
        user_id: int,
        name: str,
        class_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Атомарно применяет invite к Telegram-пользователю.

        Для child invite нужны class_id и group_id.
        Для parent/observer invite class/group должны быть None.

        Возвращает {family_id, intended_role} при успехе.
        Возвращает None, если invite истёк, отозван, использован либо
        пользователь уже состоит в семье.
        """
        async with self._connection() as db:
            await db.execute("BEGIN")

            try:
                invite_cursor = await db.execute(
                    """
                    SELECT
                        id,
                        family_id,
                        intended_role,
                        max_uses,
                        uses_count
                    FROM family_invites
                    WHERE token = ?
                      AND is_revoked = 0
                      AND expires_at > CURRENT_TIMESTAMP
                      AND uses_count < max_uses
                    """,
                    (token,),
                )

                invite = await invite_cursor.fetchone()

                if invite is None:
                    await db.rollback()
                    return None

                invite_id = invite["id"]
                family_id = invite["family_id"]
                intended_role = invite["intended_role"]

                user_cursor = await db.execute(
                    """
                    SELECT
                        user_id,
                        family_id
                    FROM users
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )

                user = await user_cursor.fetchone()

                if user is None:
                    await db.rollback()
                    return None

                # Не позволяем silently переместить существующего члена семьи
                # в другую семью через forwarded invite.
                if user["family_id"] is not None:
                    await db.rollback()
                    return None

                if intended_role == "child":
                    if not class_id or not group_id:
                        await db.rollback()
                        raise ValueError(
                            "Child invite requires class_id and group_id"
                        )
                else:
                    class_id = None
                    group_id = None

                # Ключевой optimistic lock:
                # один invite может быть потреблён только ограниченное число раз.
                consume_cursor = await db.execute(
                    """
                    UPDATE family_invites
                    SET
                        uses_count = uses_count + 1,
                        used_by_user_id = ?,
                        used_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                      AND is_revoked = 0
                      AND expires_at > CURRENT_TIMESTAMP
                      AND uses_count < max_uses
                    """,
                    (user_id, invite_id),
                )

                if consume_cursor.rowcount != 1:
                    await db.rollback()
                    return None

                await db.execute(
                    """
                    UPDATE users
                    SET
                        name = ?,
                        family_id = ?,
                        role = ?,
                        class_id = ?,
                        group_id = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                    """,
                    (
                        name,
                        family_id,
                        intended_role,
                        class_id,
                        group_id,
                        user_id,
                    ),
                )

                await self._ensure_parent_child_settings_for_family(
                    db=db,
                    family_id=family_id,
                )

                await self._ensure_parent_student_settings_for_family(
                    db=db,
                    family_id=family_id,
                )
                await db.commit()

                return {
                    "family_id": family_id,
                    "intended_role": intended_role,
                }

            except Exception:
                await db.rollback()
                raise

    async def get_active_family_invites(
        self,
        *,
        family_id: int,
        admin_user_id: int,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает активные неиспользованные приглашения семьи.

        Запрос сам проверяет admin_user_id, чтобы observer или обычный
        parent не смогли получить список через поддельный callback.
        """
        return await self._fetch_all(
            """
            SELECT
                invite.id,
                invite.token,
                invite.family_id,
                invite.intended_role,
                invite.expires_at,
                invite.max_uses,
                invite.uses_count,
                invite.is_revoked,
                invite.created_at,
                invite.used_by_user_id,
                invite.used_at

            FROM family_invites AS invite

            JOIN families AS family
              ON family.id = invite.family_id

            WHERE invite.family_id = ?
              AND family.admin_user_id = ?
              AND invite.is_revoked = 0
              AND invite.expires_at > CURRENT_TIMESTAMP
              AND invite.uses_count < invite.max_uses

            ORDER BY invite.created_at DESC, invite.id DESC
            """,
            (
                family_id,
                admin_user_id,
            ),
        )

    async def get_active_family_invite_by_id(
        self,
        *,
        invite_id: int,
        family_id: int,
        admin_user_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает invite только если он принадлежит семье текущего admin
        и ещё пригоден для использования.
        """
        return await self._fetch_one(
            """
            SELECT
                invite.id,
                invite.token,
                invite.family_id,
                invite.intended_role,
                invite.expires_at,
                invite.max_uses,
                invite.uses_count,
                invite.is_revoked,
                invite.created_at,
                invite.used_by_user_id,
                invite.used_at

            FROM family_invites AS invite

            JOIN families AS family
              ON family.id = invite.family_id

            WHERE invite.id = ?
              AND invite.family_id = ?
              AND family.admin_user_id = ?
              AND invite.is_revoked = 0
              AND invite.expires_at > CURRENT_TIMESTAMP
              AND invite.uses_count < invite.max_uses
            """,
            (
                invite_id,
                family_id,
                admin_user_id,
            ),
        )

    async def revoke_family_invite(
        self,
        *,
        invite_id: int,
        family_id: int,
        admin_user_id: int,
    ) -> bool:
        """
        Отзывает неиспользованное invite.

        Использованный invite отзывать бессмысленно: его token уже невалиден
        из-за uses_count == max_uses.
        """
        changed = await self._execute(
            """
            UPDATE family_invites
            SET
                is_revoked = 1
            WHERE id = ?
              AND family_id = ?
              AND is_revoked = 0
              AND uses_count < max_uses
              AND EXISTS (
                  SELECT 1
                  FROM families
                  WHERE id = ?
                    AND admin_user_id = ?
              )
            """,
            (
                invite_id,
                family_id,
                family_id,
                admin_user_id,
            ),
        )

        return changed == 1
                                                    
    async def create_family_and_link(self, admin_user_id: int) -> str:
        """
        Создаёт новую семью и привязывает создателя как администратора-родителя.

        На момент создания семьи детей ещё нет, поэтому строки
        parent_child_settings не создаются. Они появятся автоматически,
        когда к семье присоединится ребёнок.
        """
        family_code = str(uuid.uuid4())[:8].upper()

        async with self._connection() as db:
            await db.execute("BEGIN")

            user_row = await (
                await db.execute(
                    """
                    SELECT user_id
                    FROM users
                    WHERE user_id = ?
                    """,
                    (admin_user_id,),
                )
            ).fetchone()

            if user_row is None:
                raise ValueError(
                    f"Cannot create family for missing user: {admin_user_id}"
                )

            cursor = await db.execute(
                """
                INSERT INTO families (
                    family_code,
                    admin_user_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (family_code, admin_user_id),
            )

            family_id = cursor.lastrowid

            await db.execute(
                """
                UPDATE users
                SET family_id = ?,
                    role = 'parent',
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (family_id, admin_user_id),
            )

            await db.commit()

        return family_code
# legacy метод, который создаёт семью и привязывает пользователя. Для обратной совместимости оставлен
    async def get_family_by_code(self, family_code: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает семью по коду.
        """
        return await self._fetch_one(
            "SELECT id, family_code, admin_user_id FROM families WHERE family_code = ?",
            (family_code,),
        )
# Рабочий core method, оставить
    async def link_user_to_family(
        self,
        user_id: int,
        family_id: int,
        role: str,
    ) -> None:
        """
        Привязывает пользователя к семье и создаёт все недостающие
        связи взрослый → ребёнок.

        Допустимые сценарии:
        - child подключается к существующей семье;
        - parent подключается к существующей семье;
        - observer подключается к существующей семье.

        После операции каждая пара:
            parent/observer × child
        в рамках семьи существует в parent_child_settings.
        """
        allowed_roles = {"child", "parent", "observer"}

        if role not in allowed_roles:
            raise ValueError(f"Unsupported family role: {role}")

        async with self._connection() as db:
            await db.execute("BEGIN")

            family_row = await (
                await db.execute(
                    """
                    SELECT id
                    FROM families
                    WHERE id = ?
                    """,
                    (family_id,),
                )
            ).fetchone()

            if family_row is None:
                raise ValueError(f"Family does not exist: family_id={family_id}")

            user_row = await (
                await db.execute(
                    """
                    SELECT user_id
                    FROM users
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
            ).fetchone()

            if user_row is None:
                raise ValueError(f"User does not exist: user_id={user_id}")

            await db.execute(
                """
                UPDATE users
                SET family_id = ?,
                    role = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (family_id, role, user_id),
            )

            await self._ensure_parent_child_settings_for_family(
                db=db,
                family_id=family_id,
            )
            await self._ensure_parent_student_settings_for_family(
                db=db,
                family_id=family_id,
            )
            await db.commit()

    async def set_child_notifications_lock(
        self,
        parent_user_id: int,
        child_user_id: int,
        locked: bool,
    ) -> bool:
        """
        Устанавливает запрет ребёнку менять личные настройки уведомлений.

        Блокировка принадлежит конкретному взрослому и конкретному ребёнку.
        Она не хранится в users, потому что users не может выразить:
        «родитель A управляет ребёнком X, а observer B — нет».
        """
        changed = await self._execute(
            """
            UPDATE parent_child_settings
            SET child_notification_settings_locked = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE parent_id = ?
              AND child_id = ?
            """,
            (int(locked), parent_user_id, child_user_id),
        )
        return changed == 1
    
    async def get_parent_child_notification_settings_row(
        self,
        parent_user_id: int,
        child_user_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает настройки уведомлений взрослого по конкретному ребёнку.

        Запрос одновременно подтверждает:
        - запись parent_child_settings существует;
        - взрослый имеет подходящую роль;
        - ребёнок имеет роль child;
        - оба находятся в одной семье.
        """
        return await self._fetch_one(
            """
            SELECT
                pcs.parent_id,
                pcs.child_id,

                child.name AS child_name,
                child.class_id AS child_class_id,
                child.group_id AS child_group_id,

                pcs.receive_morning_summary,
                pcs.receive_pre_lesson_reminders,
                pcs.receive_schedule_changes,
                pcs.receive_extra_class_reminders
            FROM parent_child_settings AS pcs
            JOIN users AS adult
              ON adult.user_id = pcs.parent_id
            JOIN users AS child
              ON child.user_id = pcs.child_id
            WHERE pcs.parent_id = ?
              AND pcs.child_id = ?
              AND adult.role IN ('parent', 'observer')
              AND child.role = 'child'
              AND adult.family_id = child.family_id
            """,
            (parent_user_id, child_user_id),
        )

    async def toggle_parent_child_notification_setting(
        self,
        parent_user_id: int,
        child_user_id: int,
        setting_name: str,
    ) -> bool:
        """
        Переключает один notification-флаг взрослого для конкретного ребёнка.

        Имя SQL-поля нельзя передавать из callback напрямую. Оно проходит
        обязательную проверку по белому списку.
        """
        allowed_fields = {
            "receive_morning_summary",
            "receive_pre_lesson_reminders",
            "receive_schedule_changes",
            "receive_extra_class_reminders",
        }

        if setting_name not in allowed_fields:
            raise ValueError(
                f"Unsupported parent-child notification setting: {setting_name}"
            )

        changed = await self._execute(
            f"""
            UPDATE parent_child_settings
            SET {setting_name} = CASE
                    WHEN {setting_name} = 1 THEN 0
                    ELSE 1
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE parent_id = ?
              AND child_id = ?
              AND EXISTS (
                  SELECT 1
                  FROM users AS adult
                  JOIN users AS child
                    ON child.user_id = ?
                   AND child.family_id = adult.family_id
                  WHERE adult.user_id = ?
                    AND adult.role IN ('parent', 'observer')
                    AND child.role = 'child'
              )
            """,
            (
                parent_user_id,
                child_user_id,
                child_user_id,
                parent_user_id,
            ),
        )

        return changed == 1
    
    async def parent_can_access_child(
        self,
        parent_user_id: int,
        child_user_id: int,
    ) -> bool:
        """
        Проверяет, что существует активная связь взрослый → ребёнок.
        Используется перед любой родительской операцией над ребёнком.
        """
        row = await self._fetch_one(
            """
            SELECT 1 AS allowed
            FROM parent_child_settings
            WHERE parent_id = ?
              AND child_id = ?
            """,
            (parent_user_id, child_user_id),
        )
        return row is not None

    async def get_extra_classes_access(
        self,
        actor_user_id: int,
        target_child_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает права инициатора на допзанятия конкретного ребёнка.

        Политика:
        - ребёнок управляет только собственными занятиями;
        - parent/observer видит ребёнка только через parent_child_settings;
        - parent/observer редактирует только при can_manage_extra_classes = 1;
        - несвязанный пользователь не получает строку доступа.
        """
        return await self._fetch_one(
            """
            SELECT
                target.user_id AS target_child_id,

                CASE
                    WHEN target.user_id = ? THEN 1
                    WHEN pcs.parent_id IS NOT NULL THEN 1
                    ELSE 0
                END AS can_view,

                CASE
                    WHEN target.user_id = ?
                        AND target.can_manage_own_extra_classes = 1
                    THEN 1

                    WHEN COALESCE(
                        pcs.can_manage_extra_classes,
                        0
                    ) = 1
                    THEN 1

                    ELSE 0
                END AS can_manage
            FROM users AS target
            LEFT JOIN parent_child_settings AS pcs
              ON pcs.child_id = target.user_id
             AND pcs.parent_id = ?
            LEFT JOIN users AS adult
              ON adult.user_id = pcs.parent_id
            WHERE target.user_id = ?
              AND target.role = 'child'
              AND (
                    target.user_id = ?
                    OR (
                        adult.role IN ('parent', 'observer')
                        AND adult.family_id = target.family_id
                    )
                  )
            """,
            (
                actor_user_id,
                actor_user_id,
                actor_user_id,
                target_child_id,
                actor_user_id,
            ),
        )

    async def get_adult_extra_classes_permissions(
        self,
        admin_user_id: int,
        child_user_id: int,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает список взрослых и их прав управления занятиями ребёнка.

        Список возвращается только если инициатор является администратором
        семьи этого ребёнка. Сам администратор исключён: его право считается
        системным и не должно переключаться через UI.
        """
        return await self._fetch_all(
            """
            SELECT
                adult.user_id AS adult_user_id,
                COALESCE(
                    NULLIF(TRIM(adult.name), ''),
                    'Пользователь ' || adult.user_id
                ) AS adult_name,
                adult.role AS adult_role,
                pcs.child_id AS child_user_id,
                pcs.can_manage_extra_classes
            FROM families AS family
            JOIN users AS child
              ON child.family_id = family.id
            JOIN parent_child_settings AS pcs
              ON pcs.child_id = child.user_id
            JOIN users AS adult
              ON adult.user_id = pcs.parent_id
            WHERE family.admin_user_id = ?
              AND child.user_id = ?
              AND child.role = 'child'
              AND adult.role IN ('parent', 'observer')
              AND adult.user_id != family.admin_user_id
            ORDER BY
                CASE adult.role
                    WHEN 'parent' THEN 0
                    ELSE 1
                END,
                adult_name,
                adult.user_id
            """,
            (admin_user_id, child_user_id),
        )

    async def set_adult_extra_classes_permission(
        self,
        admin_user_id: int,
        adult_user_id: int,
        child_user_id: int,
        can_manage: bool,
    ) -> bool:
        """
        Устанавливает право другого взрослого на допзанятия ребёнка.

        Изменение разрешено только families.admin_user_id.
        Администратор не может менять собственную строку через этот метод.
        """
        changed = await self._execute(
            """
            UPDATE parent_child_settings
            SET
                can_manage_extra_classes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE parent_id = ?
              AND child_id = ?
              AND parent_id != (
                  SELECT admin_user_id
                  FROM families
                  WHERE id = (
                      SELECT family_id
                      FROM users
                      WHERE user_id = ?
                  )
              )
              AND EXISTS (
                  SELECT 1
                  FROM families AS family
                  JOIN users AS child
                    ON child.family_id = family.id
                  JOIN users AS adult
                    ON adult.user_id = ?
                   AND adult.family_id = family.id
                  WHERE family.admin_user_id = ?
                    AND child.user_id = ?
                    AND child.role = 'child'
                    AND adult.role IN ('parent', 'observer')
              )
            """,
            (
                int(can_manage),
                adult_user_id,
                child_user_id,
                child_user_id,
                adult_user_id,
                admin_user_id,
                child_user_id,
            ),
        )

        return changed == 1
            
    async def is_family_admin_for_child(
        self,
        admin_user_id: int,
        child_user_id: int,
    ) -> bool:
        """
        Проверяет, является ли пользователь администратором семьи ребёнка.

        Только families.admin_user_id имеет право принудительно менять
        настройки ребёнка и ставить/снимать блокировку.
        """
        row = await self._fetch_one(
            """
            SELECT 1 AS is_admin
            FROM families AS family
            JOIN users AS child
              ON child.family_id = family.id
            WHERE family.admin_user_id = ?
              AND child.user_id = ?
              AND child.role = 'child'
            """,
            (admin_user_id, child_user_id),
        )

        return row is not None
    
    # безопасный редирект старого метода
        async def is_child_notification_settings_locked(
            self,
            child_user_id: int,
        ) -> bool:
            """
            Legacy-compatible name.

            Реальная проверка теперь использует:
            student_profiles
            → families.admin_user_id
            → parent_student_settings.
            """
            return await self.is_telegram_child_notification_settings_locked(
                telegram_user_id=child_user_id,
            )
        
    async def set_child_notification_settings_locked(
        self,
        admin_user_id: int,
        child_user_id: int,
        locked: bool,
    ) -> bool:
        """
        Устанавливает блокировку настроек ребёнка.

        UPDATE содержит проверку families.admin_user_id, поэтому callback
        вручную подделать недостаточно: не-администратор не сможет изменить
        строку даже при знании child_id.
        """
        changed = await self._execute(
            """
            UPDATE parent_child_settings
            SET
                child_notification_settings_locked = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE parent_id = ?
              AND child_id = ?
              AND EXISTS (
                  SELECT 1
                  FROM families AS family
                  JOIN users AS child
                    ON child.family_id = family.id
                  WHERE family.admin_user_id = ?
                    AND child.user_id = ?
                    AND child.role = 'child'
              )
            """,
            (
                int(locked),
                admin_user_id,
                child_user_id,
                admin_user_id,
                child_user_id,
            ),
        )

        return changed == 1
        
    # ========== CHILDREN LIST ==========

    async def get_children_for_parent_rows(
        self,
        parent_user_id: int,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает только детей, на которых у взрослого есть запись
        parent_child_settings.

        parent_child_settings — источник истины для взрослого доступа
        к конкретному ребёнку.
        """
        return await self._fetch_all(
            """
            SELECT
                child.user_id,
                child.name,
                child.class_id,
                child.group_id
            FROM parent_child_settings AS pcs
            JOIN users AS adult
              ON adult.user_id = pcs.parent_id
            JOIN users AS child
              ON child.user_id = pcs.child_id
            WHERE pcs.parent_id = ?
              AND adult.role IN ('parent', 'observer')
              AND child.role = 'child'
              AND adult.family_id = child.family_id
            ORDER BY
                COALESCE(child.name, ''),
                child.user_id
            """,
            (parent_user_id,),
        )
        
    async def update_user_name(self, user_id: int, name: str) -> None:
        """Сохраняет имя пользователя."""
        await self._execute(
            "UPDATE users SET name = ? WHERE user_id = ?",
            (name, user_id),
        )
# для переключения флагов (toggles) и получения family_code по ID, чтобы изолировать SQL от хендлеров.

    async def get_family_code_by_id(self, family_id: int) -> str | None:
        row = await self._fetch_one("SELECT family_code FROM families WHERE id = ?", (family_id,))
        return row["family_code"] if row else None

    async def toggle_boolean_flag(
        self,
        user_id: int,
        field_name: str,
    ) -> None:
        """
        Безопасно переключает разрешённый boolean-флаг профиля пользователя.
        """
        allowed_fields = {
            "is_notifications_enabled",
            "receive_schedule_changes",
            "receive_extra_class_reminders",
            "can_manage_own_extra_classes",
        }

        if field_name not in allowed_fields:
            raise ValueError(
                f"Unsupported boolean user field: {field_name}"
            )

        await self._execute(
            f"""
            UPDATE users
            SET
                {field_name} = CASE
                    WHEN {field_name} = 1 THEN 0
                    ELSE 1
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (user_id,),
        )
            
 # Сводка       
    async def update_morning_summary_time(self, user_id: int, time_str: str | None) -> None:
        """Обновляет время утренней сводки. Если None - сводка выключена."""
        await self._execute(
            "UPDATE users SET morning_summary_time = ? WHERE user_id = ?",
            (time_str, user_id),
        )
        
    # Перерегистрация   

    async def get_profile_reset_impact(
        self,
        user_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает последствия перерегистрации пользователя.

        Никаких изменений БД не выполняет. Нужен только для confirmation UI.
        """
        return await self._fetch_one(
            """
            SELECT
                u.user_id,
                u.role,
                u.family_id,

                CASE
                    WHEN family.admin_user_id = u.user_id THEN 1
                    ELSE 0
                END AS is_family_admin,

                (
                    SELECT COUNT(*)
                    FROM users AS family_member
                    WHERE family_member.family_id = u.family_id
                ) AS family_members_count,

                (
                    SELECT COUNT(*)
                    FROM users AS child
                    WHERE child.family_id = u.family_id
                      AND child.role = 'child'
                ) AS children_count,

                (
                    SELECT COUNT(*)
                    FROM extra_classes AS family_extra
                    WHERE family_extra.family_id = u.family_id
                ) AS family_extra_classes_count,

                (
                    SELECT COUNT(*)
                    FROM extra_classes AS own_extra
                    JOIN student_profiles AS own_student
                        ON own_student.id = own_extra.student_id
                    WHERE own_student.telegram_user_id = u.user_id
                ) AS own_extra_classes_count

            FROM users AS u

            LEFT JOIN families AS family
              ON family.id = u.family_id

            WHERE u.user_id = ?
            """,
            (user_id,),
        )
            
    async def reset_non_admin_user(
        self,
        user_id: int,
    ) -> bool:
        """
        Сбрасывает профиль обычного участника семьи.

        Возможные роли:
        - child;
        - parent, который не является family admin;
        - observer.

        Пользователь отвязывается от семьи. Семья и остальные участники
        продолжают работать.
        """
        async with self._connection() as db:
            await db.execute("BEGIN")

            user_cursor = await db.execute(
                """
                SELECT
                    user_id,
                    role,
                    family_id
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            )

            user = await user_cursor.fetchone()

            if user is None:
                await db.rollback()
                return False

            user_role = user["role"]
            family_id = user["family_id"]

            admin_cursor = await db.execute(
                """
                SELECT 1
                FROM families
                WHERE admin_user_id = ?
                """,
                (user_id,),
            )

            is_admin = await admin_cursor.fetchone() is not None

            if is_admin:
                await db.rollback()
                raise ValueError(
                    "Family admin must use disband_family_by_admin"
                )

            # Если выходит ребёнок, его допзанятия нельзя оставить:
            # extra_classes.family_id и user_id должны оставаться согласованными.
            if user_role == "child" and family_id is not None:
                """
                Telegram child сбрасывает только Telegram-профиль.

                student_profile и его extra_classes сохраняются:
                профиль ученика превращается в virtual student.
                """
                await db.execute(
                    """
                    UPDATE student_profiles
                    SET
                        telegram_user_id = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE telegram_user_id = ?
                    """,
                    (user_id,),
                )

            # Удаляем отношения, где пользователь был взрослым или ребёнком.
            await db.execute(
                """
                DELETE FROM parent_child_settings
                WHERE parent_id = ?
                   OR child_id = ?
                """,
                (user_id, user_id),
            )

            if user_role in ("parent", "observer"):
                await db.execute(
                    """
                    DELETE FROM parent_student_settings
                    WHERE parent_user_id = ?
                    """,
                    (user_id,),
                )
    
            # Роль сохраняем допустимой для CHECK constraint.
            # class/group очищаются, чтобы /start распознал профиль
            # как незавершённо зарегистрированный.
            await db.execute(
                """
                UPDATE users
                SET
                    role = 'child',
                    family_id = NULL,
                    class_id = NULL,
                    group_id = NULL,
                    teacher_id = NULL,
                    morning_summary_time = NULL,
                    pre_lesson_offset_minutes = 10,
                    receive_schedule_changes = 1,
                    receive_extra_class_reminders = 1,
                    changes_window_days = 3,
                    global_extra_reminder = 30,
                    can_manage_own_extra_classes = 1,
                    is_notifications_enabled = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (user_id,),
            )

            # Очищаем историю отправленных уведомлений, чтобы при перерегистрации
            # старые логи не блокировали новые рассылки
            await db.execute(
                """
                DELETE FROM notification_delivery_log
                WHERE recipient_id = ?
                """,
                (user_id,),
            )

            await db.commit()

        return True

    async def disband_family_by_admin(
        self,
        admin_user_id: int,
    ) -> bool:
        """
        Расформировывает семью по инициативе её администратора.

        Последствия:
        - удаляются parent_child_settings всей семьи;
        - удаляются extra_classes всей семьи;
        - очищаются логи отправки уведомлений всей семьи;
        - все участники отвязываются от family_id;
        - сам администратор полностью сбрасывается;
        - остальные участники сохраняются как отдельные Telegram-профили,
          но больше не состоят в семье.

        Автоматическая передача admin_user_id другому взрослому намеренно
        не выполняется.
        """
        async with self._connection() as db:
            await db.execute("BEGIN")

            family_cursor = await db.execute(
                """
                SELECT id
                FROM families
                WHERE admin_user_id = ?
                """,
                (admin_user_id,),
            )

            family = await family_cursor.fetchone()

            if family is None:
                await db.rollback()
                return False

            family_id = family["id"]

            # Получаем ID всех участников семьи до очистки связи (users.family_id)
            members_cursor = await db.execute(
                """
                SELECT user_id
                FROM users
                WHERE family_id = ?
                """,
                (family_id,),
            )
            member_rows = await members_cursor.fetchall()
            member_ids = [row["user_id"] for row in member_rows]

            # Сначала собираем связи и занятия, затем удаляем dependent data.
            await db.execute(
                """
                DELETE FROM parent_child_settings
                WHERE parent_id IN (
                    SELECT user_id
                    FROM users
                    WHERE family_id = ?
                )
                OR child_id IN (
                    SELECT user_id
                    FROM users
                    WHERE family_id = ?
                )
                """,
                (family_id, family_id),
            )

            await db.execute(
                """
                DELETE FROM extra_classes
                WHERE family_id = ?
                """,
                (family_id,),
            )

            # Удаляем старые логи доставки уведомлений для всех участников семьи
            if member_ids:
                placeholders = ",".join("?" for _ in member_ids)
                await db.execute(
                    f"""
                    DELETE FROM notification_delivery_log
                    WHERE recipient_id IN ({placeholders})
                    """,
                    tuple(member_ids),
                )

            # Все участники становятся независимыми.
            # Дети сохраняют class_id/group_id и могут продолжать смотреть
            # личное расписание; взрослые без family_id при /start пройдут
            # новый flow семьи.
            await db.execute(
                """
                UPDATE users
                SET
                    family_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE family_id = ?
                """,
                (family_id,),
            )

            # Администратора сбрасываем полностью.
            await db.execute(
                """
                UPDATE users
                SET
                    role = 'child',
                    class_id = NULL,
                    group_id = NULL,
                    teacher_id = NULL,
                    morning_summary_time = NULL,
                    pre_lesson_offset_minutes = 10,
                    receive_schedule_changes = 1,
                    receive_extra_class_reminders = 1,
                    changes_window_days = 3,
                    global_extra_reminder = 30,
                    can_manage_own_extra_classes = 1,
                    is_notifications_enabled = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (admin_user_id,),
            )

            await db.execute(
                """
                DELETE FROM families
                WHERE id = ?
                """,
                (family_id,),
            )

            await db.commit()

        return True

    async def update_integer_setting(self, user_id: int, field_name: str, value: int) -> None:
        """Безопасное обновление числовых настроек."""
        allowed_fields = {"pre_lesson_offset_minutes", "global_extra_reminder"}
        if field_name in allowed_fields:
            await self._execute(f"UPDATE users SET {field_name} = ? WHERE user_id = ?", (value, user_id))
            
    # метод получения состава семьи
    async def get_family_members_rows(self, family_id: int) -> list[dict]:
        """Возвращает сырые данные всех участников семьи."""
        return await self._fetch_all(
            "SELECT user_id, name, role, class_id FROM users WHERE family_id = ?",
            (family_id,)
        )

    async def update_role_and_defaults(self, user_id: int, role: str) -> None:
        """Назначает роль и выставляет дефолтные настройки уведомлений."""
        async with self._connection() as db:
            if role in ('parent', 'observer'):
                # Взрослые: включены только изменения, остальное в 0
                await db.execute('''
                    UPDATE users 
                    SET role = ?, 
                        pre_lesson_offset_minutes = 0, 
                        global_extra_reminder = 0
                    WHERE user_id = ?
                ''', (role, user_id))
            elif role == 'child':
                # Ребенок: предурочные выключены (0), остальное работает
                await db.execute('''
                    UPDATE users 
                    SET role = ?, 
                        pre_lesson_offset_minutes = 0
                    WHERE user_id = ?
                ''', (role, user_id))
            else:
                await db.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
            
            await db.commit()
            
    # Виртуальный ученик          
    async def get_parent_student_notification_settings_row(
        self,
        *,
        parent_user_id: int,
        student_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает персональные настройки adult → student.

        Доступ возможен только для parent/observer, состоящего
        в той же семье, что и student profile.
        """
        return await self._fetch_one(
            """
            SELECT
                settings.parent_user_id,
                settings.student_id,

                student.name AS student_name,
                student.class_id AS student_class_id,
                student.group_id AS student_group_id,
                student.telegram_user_id,

                settings.receive_morning_summary,
                settings.receive_pre_lesson_reminders,
                settings.receive_schedule_changes,
                settings.receive_extra_class_reminders,

                settings.can_manage_extra_classes

            FROM parent_student_settings AS settings
            JOIN users AS adult
                ON adult.user_id = settings.parent_user_id
            JOIN student_profiles AS student
                ON student.id = settings.student_id

            WHERE settings.parent_user_id = ?
            AND settings.student_id = ?
            AND adult.role IN ('parent', 'observer')
            AND adult.family_id = student.family_id
            AND student.is_active = 1
            """,
            (
                parent_user_id,
                student_id,
            ),
        )
        
    async def toggle_parent_student_notification_setting(
        self,
        *,
        parent_user_id: int,
        student_id: int,
        setting_name: str,
    ) -> bool:
        """
        Переключает одну из личных подписок взрослого
        на конкретный student profile.

        Безопасность:
        - поле проверяется whitelist-ом;
        - взрослый может менять только собственную строку;
        - student обязан принадлежать той же семье.
        """
        allowed_fields = {
            "receive_morning_summary",
            "receive_pre_lesson_reminders",
            "receive_schedule_changes",
            "receive_extra_class_reminders",
        }

        if setting_name not in allowed_fields:
            raise ValueError(
                f"Unsupported parent-student setting: {setting_name}"
            )

        changed = await self._execute(
            f"""
            UPDATE parent_student_settings
            SET
                {setting_name} = CASE
                    WHEN {setting_name} = 1 THEN 0
                    ELSE 1
                END,
                updated_at = CURRENT_TIMESTAMP

            WHERE parent_user_id = ?
            AND student_id = ?

            AND EXISTS (
                SELECT 1
                FROM users AS adult
                JOIN student_profiles AS student
                    ON student.id = ?
                WHERE adult.user_id = ?
                    AND adult.user_id = parent_student_settings.parent_user_id
                    AND adult.role IN ('parent', 'observer')
                    AND adult.family_id = student.family_id
                    AND student.is_active = 1
            )
            """,
            (
                parent_user_id,
                student_id,

                student_id,
                parent_user_id,
            ),
        )

        return changed == 1

    async def is_family_admin_for_student(
        self,
        *,
        admin_user_id: int,
        student_id: int,
    ) -> bool:
        """
        Проверяет, является ли Telegram-пользователь family admin
        семьи, которой принадлежит student profile.
        """
        row = await self._fetch_one(
            """
            SELECT 1 AS is_admin
            FROM student_profiles AS student
            JOIN families AS family
                ON family.id = student.family_id

            WHERE student.id = ?
            AND student.is_active = 1
            AND family.admin_user_id = ?
            """,
            (
                student_id,
                admin_user_id,
            ),
        )

        return row is not None

    async def get_adult_student_extra_classes_permissions(
        self,
        *,
        admin_user_id: int,
        student_id: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Возвращает права всех non-admin adults семьи
        на допзанятия выбранного student profile.

        None:
        инициатор не является family admin.

        []:
        family admin существует, но других взрослых в семье нет.
        """
        is_admin = await self.is_family_admin_for_student(
            admin_user_id=admin_user_id,
            student_id=student_id,
        )

        if not is_admin:
            return None

        return await self._fetch_all(
            """
            SELECT
                adult.user_id AS adult_user_id,

                COALESCE(
                    NULLIF(TRIM(adult.name), ''),
                    CAST(adult.user_id AS TEXT)
                ) AS adult_name,

                adult.role AS adult_role,

                settings.student_id,

                settings.can_manage_extra_classes

            FROM parent_student_settings AS settings
            JOIN student_profiles AS student
                ON student.id = settings.student_id
            JOIN families AS family
                ON family.id = student.family_id
            JOIN users AS adult
                ON adult.user_id = settings.parent_user_id

            WHERE settings.student_id = ?
            AND family.admin_user_id = ?
            AND adult.role IN ('parent', 'observer')
            AND adult.user_id != family.admin_user_id
            AND adult.family_id = student.family_id

            ORDER BY
                CASE adult.role
                    WHEN 'parent' THEN 0
                    ELSE 1
                END,
                adult_name COLLATE NOCASE,
                adult.user_id
            """,
            (
                student_id,
                admin_user_id,
            ),
        )
        
    async def set_adult_student_extra_classes_permission(
        self,
        *,
        admin_user_id: int,
        adult_user_id: int,
        student_id: int,
        can_manage: bool,
    ) -> bool:
        """
        Family admin выдаёт/отзывает право другому adult
        управлять занятиями указанного student profile.

        Admin не может отозвать собственное implicit право:
        его право не хранится как ограничение в UI.
        """
        changed = await self._execute(
            """
            UPDATE parent_student_settings
            SET
                can_manage_extra_classes = ?,
                updated_at = CURRENT_TIMESTAMP

            WHERE parent_user_id = ?
            AND student_id = ?

            AND EXISTS (
                SELECT 1
                FROM student_profiles AS student
                JOIN families AS family
                    ON family.id = student.family_id
                JOIN users AS adult
                    ON adult.user_id = parent_student_settings.parent_user_id

                WHERE student.id = ?
                    AND student.is_active = 1
                    AND family.admin_user_id = ?
                    AND adult.user_id = ?
                    AND adult.user_id != family.admin_user_id
                    AND adult.role IN ('parent', 'observer')
                    AND adult.family_id = student.family_id
            )
            """,
            (
                int(can_manage),
                adult_user_id,
                student_id,

                student_id,
                admin_user_id,
                adult_user_id,
            ),
        )

        return changed == 1
    
    #---------------------------------------------
    # Управление настройками уведомлений у ребенка
    #----------------------------------------------    
    async def get_student_telegram_settings_for_admin(
        self,
        *,
        admin_user_id: int,
        student_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает Telegram-настройки student profile.

        Вернёт None, если:
        - initiator не family admin;
        - student не существует;
        - student virtual, то есть Telegram ещё не подключён.
        """
        return await self._fetch_one(
            """
            SELECT
                student.id AS student_id,
                student.telegram_user_id,

                student.name AS student_name,
                student.class_id,
                student.group_id,

                child.is_notifications_enabled,
                child.morning_summary_time,
                child.pre_lesson_offset_minutes,
                child.receive_schedule_changes,
                child.receive_extra_class_reminders,
                child.can_manage_own_extra_classes,

                settings.child_notification_settings_locked

            FROM student_profiles AS student
            JOIN families AS family
                ON family.id = student.family_id
            JOIN users AS child
                ON child.user_id = student.telegram_user_id
            LEFT JOIN parent_student_settings AS settings
                ON settings.student_id = student.id
            AND settings.parent_user_id = family.admin_user_id

            WHERE student.id = ?
            AND student.is_active = 1
            AND student.telegram_user_id IS NOT NULL
            AND child.role = 'child'
            AND family.admin_user_id = ?
            """,
            (
                student_id,
                admin_user_id,
            ),
        )
        
    async def toggle_student_telegram_boolean_setting(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        field_name: str,
    ) -> bool:
        """
        Family admin переключает personal boolean setting
        Telegram-linked student profile.
        """
        allowed_fields = {
            "is_notifications_enabled",
            "receive_schedule_changes",
            "receive_extra_class_reminders",
            "can_manage_own_extra_classes",
        }

        if field_name not in allowed_fields:
            raise ValueError(
                f"Unsupported student Telegram setting: {field_name}"
            )

        changed = await self._execute(
            f"""
            UPDATE users
            SET
                {field_name} = CASE
                    WHEN {field_name} = 1 THEN 0
                    ELSE 1
                END,
                updated_at = CURRENT_TIMESTAMP

            WHERE user_id = (
                SELECT student.telegram_user_id
                FROM student_profiles AS student
                JOIN families AS family
                    ON family.id = student.family_id

                WHERE student.id = ?
                AND student.is_active = 1
                AND student.telegram_user_id IS NOT NULL
                AND family.admin_user_id = ?
            )
            AND role = 'child'
            """,
            (
                student_id,
                admin_user_id,
            ),
        )

        return changed == 1

    async def update_student_telegram_integer_setting(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        field_name: str,
        value: int,
    ) -> bool:
        """
        Family admin меняет personal integer setting
        Telegram-linked student.
        """
        allowed_fields = {
            "pre_lesson_offset_minutes",
        }

        if field_name not in allowed_fields:
            raise ValueError(
                f"Unsupported student Telegram integer setting: "
                f"{field_name}"
            )

        if not 0 <= value <= 180:
            raise ValueError(
                "pre_lesson_offset_minutes must be in range 0..180"
            )

        changed = await self._execute(
            f"""
            UPDATE users
            SET
                {field_name} = ?,
                updated_at = CURRENT_TIMESTAMP

            WHERE user_id = (
                SELECT student.telegram_user_id
                FROM student_profiles AS student
                JOIN families AS family
                    ON family.id = student.family_id

                WHERE student.id = ?
                AND student.is_active = 1
                AND student.telegram_user_id IS NOT NULL
                AND family.admin_user_id = ?
            )
            AND role = 'child'
            """,
            (
                value,
                student_id,
                admin_user_id,
            ),
        )

        return changed == 1

    async def update_student_telegram_morning_summary_time(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        time_str: str | None,
    ) -> bool:
        """
        Family admin включает, выключает или задаёт время
        личной утренней сводки Telegram-ребёнка.
        """
        changed = await self._execute(
            """
            UPDATE users
            SET
                morning_summary_time = ?,
                updated_at = CURRENT_TIMESTAMP

            WHERE user_id = (
                SELECT student.telegram_user_id
                FROM student_profiles AS student
                JOIN families AS family
                    ON family.id = student.family_id

                WHERE student.id = ?
                AND student.is_active = 1
                AND student.telegram_user_id IS NOT NULL
                AND family.admin_user_id = ?
            )
            AND role = 'child'
            """,
            (
                time_str,
                student_id,
                admin_user_id,
            ),
        )

        return changed == 1

    async def set_student_notification_settings_locked(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        locked: bool,
    ) -> bool:
        """
        Family admin блокирует или разблокирует personal Telegram settings
        выбранного student profile.

        Lock хранится в parent_student_settings admin → student.
        """
        changed = await self._execute(
            """
            UPDATE parent_student_settings
            SET
                child_notification_settings_locked = ?,
                updated_at = CURRENT_TIMESTAMP

            WHERE parent_user_id = ?
            AND student_id = ?

            AND EXISTS (
                SELECT 1
                FROM student_profiles AS student
                JOIN families AS family
                    ON family.id = student.family_id

                WHERE student.id = ?
                    AND student.telegram_user_id IS NOT NULL
                    AND student.is_active = 1
                    AND family.admin_user_id = ?
            )
            """,
            (
                int(locked),
                admin_user_id,
                student_id,

                student_id,
                admin_user_id,
            ),
        )

        return changed == 1

    async def is_telegram_child_notification_settings_locked(
        self,
        *,
        telegram_user_id: int,
    ) -> bool:
        """
        Проверяет lock personal settings Telegram-child.

        Standalone child:
        - student.family_id IS NULL;
        - lock отсутствует;
        - возвращает False.

        Family child:
        - lock хранится в parent_student_settings
        family admin → student.
        """
        row = await self._fetch_one(
            """
            SELECT
                settings.child_notification_settings_locked AS locked

            FROM student_profiles AS student
            JOIN families AS family
                ON family.id = student.family_id
            LEFT JOIN parent_student_settings AS settings
                ON settings.student_id = student.id
            AND settings.parent_user_id = family.admin_user_id

            WHERE student.telegram_user_id = ?
            AND student.is_active = 1
            """,
            (telegram_user_id,),
        )

        return bool(row and row["locked"])