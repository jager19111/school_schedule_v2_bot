# core/repository/profile_repository.py
from __future__ import annotations

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
                child_id
            )
            SELECT
                adult.user_id,
                child.user_id
            FROM users AS adult
            JOIN users AS child
              ON child.family_id = adult.family_id
            WHERE adult.family_id = ?
              AND adult.role IN ('parent', 'observer')
              AND child.role = 'child'
            """,
            (family_id,),
        )
        
    # ========== FAMILIES ==========

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

    async def get_family_by_code(self, family_code: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает семью по коду.
        """
        return await self._fetch_one(
            "SELECT id, family_code, admin_user_id FROM families WHERE family_code = ?",
            (family_code,),
        )

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

    async def check_parent_child_same_family(
        self,
        parent_user_id: int,
        child_user_id: int,
    ) -> bool:
        """
        Проверяет наличие действующей связи взрослый → ребёнок.

        parent_child_settings является источником истины. Простого совпадения
        family_id недостаточно: взрослый может быть в семье, но не иметь
        разрешения на конкретного ребёнка.
        """
        return await self.parent_can_access_child(
            parent_user_id=parent_user_id,
            child_user_id=child_user_id,
        )

    async def get_parent_child_settings(
        self,
        parent_user_id: int,
        child_user_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает настройки конкретного взрослого относительно ребёнка.

        Возвращает None, если связи нет либо ребёнок не принадлежит взрослому.
        """
        return await self._fetch_one(
            """
            SELECT
                pcs.parent_id,
                pcs.child_id,
                pcs.receive_morning_summary,
                pcs.receive_pre_lesson_reminders,
                pcs.receive_schedule_changes,
                pcs.receive_extra_class_reminders,
                pcs.child_notification_settings_locked,
                pcs.can_manage_extra_classes
            FROM parent_child_settings AS pcs
            JOIN users AS adult
              ON adult.user_id = pcs.parent_id
            JOIN users AS child
              ON child.user_id = pcs.child_id
            WHERE pcs.parent_id = ?
              AND pcs.child_id = ?
              AND adult.family_id = child.family_id
              AND adult.role IN ('parent', 'observer')
              AND child.role = 'child'
            """,
            (parent_user_id, child_user_id),
        )

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
    
    # ========== CHILDREN LIST ==========

    async def get_children_for_parent_rows(self, parent_user_id: int) -> List[Dict[str, Any]]:
        """
        Возвращает список детей в виде dict-строк для родителя.
        """
        return await self._fetch_all(
            """
            SELECT user_id, name, class_id, group_id
            FROM users
            WHERE family_id = (SELECT family_id FROM users WHERE user_id = ?)
              AND role = 'child'
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

    async def toggle_boolean_flag(self, user_id: int, field_name: str) -> None:
        """Универсальный метод переключения boolean-флагов для защиты от инъекций валидируем field_name."""
        allowed_fields = {"is_notifications_enabled", "notify_parent_about_me", "parent_control_notifications", "can_edit_extra_classes"}
        if field_name not in allowed_fields:
            return
        await self._execute(
            f"UPDATE users SET {field_name} = CASE WHEN {field_name} = 1 THEN 0 ELSE 1 END WHERE user_id = ?",
            (user_id,)
        )
        
 # Сводка       
    async def update_morning_summary_time(self, user_id: int, time_str: str | None) -> None:
        """Обновляет время утренней сводки. Если None - сводка выключена."""
        await self._execute(
            "UPDATE users SET morning_summary_time = ? WHERE user_id = ?",
            (time_str, user_id),
        )
        
    # Перерегистрация   
# В файле core/repository/profile_repository.py

    async def reset_user(self, user_id: int) -> None:
        """Полностью очищает профиль пользователя для перерегистрации."""
        # Используем пустую строку '', чтобы обойти ограничение NOT NULL в БД.
        # Сервис корректно распознает её как "роль не выбрана".
        await self._execute(
            "UPDATE users SET role = '', family_id = NULL, class_id = NULL, group_id = NULL WHERE user_id = ?",
            (user_id,)
        )

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