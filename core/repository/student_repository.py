from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.repository.base_repository import BaseRepository


class StudentRepository(BaseRepository):
    """
    Репозиторий доменной сущности ученика.

    student_profiles существует независимо от Telegram-аккаунта.
    """

    async def is_family_admin(
        self,
        *,
        user_id: int,
        family_id: int,
    ) -> bool:
        row = await self._fetch_one(
            """
            SELECT 1 AS is_admin
            FROM families
            WHERE id = ?
              AND admin_user_id = ?
            """,
            (
                family_id,
                user_id,
            ),
        )

        return row is not None

    async def _ensure_parent_student_settings_for_family(
        self,
        *,
        db,
        family_id: int,
    ) -> None:
        """
        Создаёт недостающие связи adult → student.

        Parent получает право управления допзанятиями по умолчанию.
        Observer получает просмотр и уведомления, но без CRUD-доступа.
        """
        await db.execute(
            """
            INSERT OR IGNORE INTO parent_student_settings (
                parent_user_id,
                student_id,
                can_manage_extra_classes
            )
            SELECT
                adult.user_id,
                student.id,
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

    async def get_student(
        self,
        *,
        student_id: int,
    ) -> Optional[Dict[str, Any]]:
        return await self._fetch_one(
            """
            SELECT
                id,
                family_id,
                telegram_user_id,
                name,
                class_id,
                group_id,
                is_active,
                created_at,
                updated_at
            FROM student_profiles
            WHERE id = ?
            """,
            (student_id,),
        )

    async def get_student_for_adult(
        self,
        *,
        adult_user_id: int,
        student_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает ученика только при наличии family relationship.

        Family admin получает доступ ко всем активным ученикам семьи.
        Parent/observer — только через parent_student_settings.
        """
        return await self._fetch_one(
            """
            SELECT
                student.id,
                student.family_id,
                student.telegram_user_id,
                student.name,
                student.class_id,
                student.group_id,
                student.is_active,
                student.created_at,
                student.updated_at,

                CASE
                    WHEN family.admin_user_id = adult.user_id THEN 1
                    ELSE 0
                END AS is_family_admin,

                CASE
                    WHEN family.admin_user_id = adult.user_id THEN 1
                    WHEN settings.parent_user_id IS NOT NULL THEN 1
                    ELSE 0
                END AS can_view,

                CASE
                    WHEN family.admin_user_id = adult.user_id THEN 1
                    WHEN COALESCE(
                        settings.can_manage_extra_classes,
                        0
                    ) = 1 THEN 1
                    ELSE 0
                END AS can_manage_extra_classes

            FROM student_profiles AS student

            JOIN families AS family
              ON family.id = student.family_id

            LEFT JOIN users AS adult
              ON adult.user_id = ?

            LEFT JOIN parent_student_settings AS settings
              ON settings.parent_user_id = adult.user_id
             AND settings.student_id = student.id

            WHERE student.id = ?
              AND student.is_active = 1
              AND adult.role IN ('parent', 'observer')
              AND adult.family_id = student.family_id
            """,
            (
                adult_user_id,
                student_id,
            ),
        )

    async def get_students_for_adult(
        self,
        *,
        adult_user_id: int,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает всех учеников, доступных конкретному adult.

        Family admin видит всех учеников семьи.
        Parent/observer видит учеников с parent_student_settings.
        """
        return await self._fetch_all(
            """
            SELECT
                student.id,
                student.family_id,
                student.telegram_user_id,
                student.name,
                student.class_id,
                student.group_id,
                student.is_active,
                student.created_at,
                student.updated_at,

                CASE
                    WHEN family.admin_user_id = adult.user_id THEN 1
                    ELSE 0
                END AS is_family_admin,

                CASE
                    WHEN family.admin_user_id = adult.user_id THEN 1
                    WHEN settings.parent_user_id IS NOT NULL THEN 1
                    ELSE 0
                END AS can_view,

                CASE
                    WHEN family.admin_user_id = adult.user_id THEN 1
                    WHEN COALESCE(
                        settings.can_manage_extra_classes,
                        0
                    ) = 1 THEN 1
                    ELSE 0
                END AS can_manage_extra_classes

            FROM users AS adult

            JOIN families AS family
              ON family.id = adult.family_id

            JOIN student_profiles AS student
              ON student.family_id = family.id
             AND student.is_active = 1

            LEFT JOIN parent_student_settings AS settings
              ON settings.parent_user_id = adult.user_id
             AND settings.student_id = student.id

            WHERE adult.user_id = ?
              AND adult.role IN ('parent', 'observer')
              AND (
                    family.admin_user_id = adult.user_id
                    OR settings.parent_user_id IS NOT NULL
                  )

            ORDER BY
                student.name COLLATE NOCASE,
                student.id
            """,
            (adult_user_id,),
        )

    async def create_virtual_student(
        self,
        *,
        admin_user_id: int,
        family_id: int,
        name: str,
        class_id: str,
        group_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Создаёт ученика без Telegram.

        Вернёт None, если инициатор не является family admin.
        """
        async with self._connection() as db:
            await db.execute("BEGIN")

            try:
                family_cursor = await db.execute(
                    """
                    SELECT id
                    FROM families
                    WHERE id = ?
                      AND admin_user_id = ?
                    """,
                    (
                        family_id,
                        admin_user_id,
                    ),
                )

                family = await family_cursor.fetchone()

                if family is None:
                    await db.rollback()
                    return None

                cursor = await db.execute(
                    """
                    INSERT INTO student_profiles (
                        family_id,
                        telegram_user_id,
                        name,
                        class_id,
                        group_id
                    )
                    VALUES (?, NULL, ?, ?, ?)
                    """,
                    (
                        family_id,
                        name,
                        class_id,
                        group_id,
                    ),
                )

                student_id = cursor.lastrowid

                await self._ensure_parent_student_settings_for_family(
                    db=db,
                    family_id=family_id,
                )

                await db.commit()

            except Exception:
                await db.rollback()
                raise

        return await self.get_student(
            student_id=student_id,
        )

    async def update_student_profile(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        name: Optional[str] = None,
        class_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> bool:
        """
        Обновляет student profile только от имени family admin.

        Если profile уже связан с Telegram-child, class/group
        синхронизируются также в users.

        Это сохраняет согласованность:
        student_profiles.class_id/group_id
        ↔ users.class_id/group_id.
        """
        fields: list[str] = []
        params: list[Any] = []

        if name is not None:
            fields.append("name = ?")
            params.append(name)

        if class_id is not None:
            fields.append("class_id = ?")
            params.append(class_id)

        if group_id is not None:
            fields.append("group_id = ?")
            params.append(group_id)

        if not fields:
            return False

        fields.append("updated_at = CURRENT_TIMESTAMP")

        async with self._connection() as db:
            await db.execute("BEGIN")

            try:
                student_cursor = await db.execute(
                    """
                    SELECT
                        student.id,
                        student.telegram_user_id,
                        student.family_id
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

                student = await student_cursor.fetchone()

                if student is None:
                    await db.rollback()
                    return False

                cursor = await db.execute(
                    f"""
                    UPDATE student_profiles
                    SET {", ".join(fields)}
                    WHERE id = ?
                    """,
                    (
                        *params,
                        student_id,
                    ),
                )

                if cursor.rowcount != 1:
                    await db.rollback()
                    return False

                # Для virtual student telegram_user_id=NULL:
                # обновлять users не требуется.
                #
                # Для Telegram-linked student:
                # обновляем только переданные class/group.
                if student["telegram_user_id"] is not None:
                    user_fields: list[str] = []
                    user_params: list[Any] = []

                    if class_id is not None:
                        user_fields.append("class_id = ?")
                        user_params.append(class_id)

                    if group_id is not None:
                        user_fields.append("group_id = ?")
                        user_params.append(group_id)

                    if name is not None:
                        user_fields.append("name = ?")
                        user_params.append(name)

                    if user_fields:
                        user_fields.append(
                            "updated_at = CURRENT_TIMESTAMP"
                        )

                        await db.execute(
                            f"""
                            UPDATE users
                            SET {", ".join(user_fields)}
                            WHERE user_id = ?
                            AND role = 'child'
                            """,
                            (
                                *user_params,
                                student["telegram_user_id"],
                            ),
                        )

                await db.commit()

            except Exception:
                await db.rollback()
                raise

        return True

    async def delete_virtual_student(
        self,
        *,
        admin_user_id: int,
        student_id: int,
    ) -> bool:
        """
        Полностью удаляет ученика без Telegram.

        Telegram-linked student нельзя удалить этим методом:
        сначала его нужно отвязать отдельным flow.
        """
        async with self._connection() as db:
            await db.execute("BEGIN")

            try:
                cursor = await db.execute(
                    """
                    DELETE FROM student_profiles
                    WHERE id = ?
                      AND telegram_user_id IS NULL
                      AND EXISTS (
                          SELECT 1
                          FROM families AS family
                          WHERE family.id = student_profiles.family_id
                            AND family.admin_user_id = ?
                      )
                    """,
                    (
                        student_id,
                        admin_user_id,
                    ),
                )

                await db.commit()

            except Exception:
                await db.rollback()
                raise

        return cursor.rowcount == 1
    
    async def get_student_by_telegram_user_id(
        self,
        *,
        telegram_user_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает активный student_profile, связанный с Telegram-ребёнком.
        """
        return await self._fetch_one(
            """
            SELECT
                id,
                family_id,
                telegram_user_id,
                name,
                class_id,
                group_id,
                is_active,
                created_at,
                updated_at
            FROM student_profiles
            WHERE telegram_user_id = ?
              AND is_active = 1
            """,
            (telegram_user_id,),
        )
            
    async def upsert_telegram_student(
        self,
        *,
        telegram_user_id: int,
        family_id: int | None,
        name: str,
        class_id: str,
        group_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Создаёт или обновляет student profile Telegram-ребёнка.

        family_id=None допустим для самостоятельного child profile.

        Если family_id задан:
        - создаются недостающие parent_student_settings;
        - удаляются неактуальные связи со взрослыми прежней семьи.
        """
        async with self._connection() as db:
            await db.execute("BEGIN")

            try:
                cursor = await db.execute(
                    """
                    SELECT id
                    FROM student_profiles
                    WHERE telegram_user_id = ?
                    """,
                    (telegram_user_id,),
                )

                existing = await cursor.fetchone()

                if existing is None:
                    await db.execute(
                        """
                        INSERT INTO student_profiles (
                            family_id,
                            telegram_user_id,
                            name,
                            class_id,
                            group_id,
                            is_active
                        )
                        VALUES (?, ?, ?, ?, ?, 1)
                        """,
                        (
                            family_id,
                            telegram_user_id,
                            name,
                            class_id,
                            group_id,
                        ),
                    )
                else:
                    await db.execute(
                        """
                        UPDATE student_profiles
                        SET
                            family_id = ?,
                            name = ?,
                            class_id = ?,
                            group_id = ?,
                            is_active = 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE telegram_user_id = ?
                        """,
                        (
                            family_id,
                            name,
                            class_id,
                            group_id,
                            telegram_user_id,
                        ),
                    )

                if family_id is not None:
                    await db.execute(
                        """
                        DELETE FROM parent_student_settings
                        WHERE student_id = (
                            SELECT id
                            FROM student_profiles
                            WHERE telegram_user_id = ?
                        )
                        AND parent_user_id NOT IN (
                            SELECT user_id
                            FROM users
                            WHERE family_id = ?
                                AND role IN ('parent', 'observer')
                        )
                        """,
                        (
                            telegram_user_id,
                            family_id,
                        ),
                    )

                    await self._ensure_parent_student_settings_for_family(
                        db=db,
                        family_id=family_id,
                    )

                await db.commit()

            except Exception:
                await db.rollback()
                raise

        return await self.get_student_by_telegram_user_id(
            telegram_user_id=telegram_user_id,
        )
        
    async def create_student_claim_invite(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        expires_in_hours: int = 24,
    ) -> Optional[Dict[str, Any]]:
        """
        Создаёт одноразовый claim invite для virtual student.

        Вернёт None, если:
        - инициатор не является family admin;
        - student не найден;
        - student уже связан с Telegram;
        - срок жизни токена невалиден.
        """
        if not 1 <= expires_in_hours <= 168:
            raise ValueError(
                "expires_in_hours must be in range 1..168"
            )

        token = secrets.token_urlsafe(24)

        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(hours=expires_in_hours)
        ).strftime("%Y-%m-%d %H:%M:%S")

        async with self._connection() as db:
            await db.execute("BEGIN")

            try:
                student_cursor = await db.execute(
                    """
                    SELECT
                        student.id,
                        student.family_id
                    FROM student_profiles AS student
                    JOIN families AS family
                        ON family.id = student.family_id
                    WHERE student.id = ?
                    AND student.is_active = 1
                    AND student.telegram_user_id IS NULL
                    AND family.admin_user_id = ?
                    """,
                    (
                        student_id,
                        admin_user_id,
                    ),
                )

                student = await student_cursor.fetchone()

                if student is None:
                    await db.rollback()
                    return None

                # Для одного virtual student держим только одну активную
                # claim-ссылку. Старые токены становятся невалидными.
                await db.execute(
                    """
                    UPDATE student_claim_invites
                    SET is_revoked = 1
                    WHERE student_id = ?
                    AND is_revoked = 0
                    AND used_at IS NULL
                    AND expires_at > CURRENT_TIMESTAMP
                    """,
                    (student_id,),
                )

                cursor = await db.execute(
                    """
                    INSERT INTO student_claim_invites (
                        token,
                        student_id,
                        created_by_user_id,
                        expires_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        token,
                        student_id,
                        admin_user_id,
                        expires_at,
                    ),
                )

                invite_id = cursor.lastrowid

                await db.commit()

            except Exception:
                await db.rollback()
                raise

        return await self.get_student_claim_invite_by_id(
            invite_id=invite_id,
        )
        
    async def get_student_claim_invite_by_id(
        self,
        *,
        invite_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает invite с данными student profile.

        Используется после создания, чтобы handler мог построить
        deep link и показать admin результат.
        """
        return await self._fetch_one(
            """
            SELECT
                invite.id,
                invite.token,

                invite.student_id,
                student.family_id,

                invite.created_by_user_id,

                invite.expires_at,
                invite.is_revoked,

                invite.used_by_user_id,
                invite.created_at,
                invite.used_at,

                student.name AS student_name,
                student.class_id AS student_class_id,
                student.group_id AS student_group_id,
                student.telegram_user_id

            FROM student_claim_invites AS invite
            JOIN student_profiles AS student
                ON student.id = invite.student_id

            WHERE invite.id = ?
            """,
            (invite_id,),
        )
        
    async def get_valid_student_claim_invite(
        self,
        *,
        token: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает пригодный claim invite.

        Token действителен, только если:
        - не отозван;
        - не использован;
        - не истёк;
        - student profile активен;
        - student всё ещё virtual, то есть telegram_user_id IS NULL.
        """
        return await self._fetch_one(
            """
            SELECT
                invite.id,
                invite.token,

                invite.student_id,
                student.family_id,

                invite.created_by_user_id,

                invite.expires_at,
                invite.is_revoked,

                invite.used_by_user_id,
                invite.created_at,
                invite.used_at,

                student.name AS student_name,
                student.class_id AS student_class_id,
                student.group_id AS student_group_id

            FROM student_claim_invites AS invite
            JOIN student_profiles AS student
                ON student.id = invite.student_id
            JOIN families AS family
                ON family.id = student.family_id

            WHERE invite.token = ?
            AND invite.is_revoked = 0
            AND invite.used_at IS NULL
            AND invite.used_by_user_id IS NULL
            AND invite.expires_at > CURRENT_TIMESTAMP
            AND student.is_active = 1
            AND student.telegram_user_id IS NULL
            """,
            (token,),
        )

    async def consume_student_claim_invite_with_merge(
        self,
        *,
        token: str,
        telegram_user_id: int,
        name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Атомарно привязывает Telegram к virtual family student profile.

        Если Telegram уже связан с самостоятельным active profile:
        - переносит его extra_classes на canonical family profile;
        - отключает standalone profile;
        - привязывает Telegram к family profile.

        Источник истины для class_id/group_id — target profile claim invite.
        Источник имени — явный ввод ребёнка.
        """
        async with self._connection() as db:
            await db.execute("BEGIN IMMEDIATE")

            try:
                invite_cursor = await db.execute(
                    """
                    SELECT
                        invite.id AS invite_id,
                        invite.student_id AS target_student_id,

                        target.family_id,
                        target.class_id,
                        target.group_id

                    FROM student_claim_invites AS invite

                    JOIN student_profiles AS target
                        ON target.id = invite.student_id

                    WHERE invite.token = ?
                    AND invite.is_revoked = 0
                    AND invite.used_at IS NULL
                    AND invite.used_by_user_id IS NULL
                    AND invite.expires_at > CURRENT_TIMESTAMP
                    AND target.is_active = 1
                    AND target.telegram_user_id IS NULL
                    """,
                    (token,),
                )

                invite = await invite_cursor.fetchone()

                if invite is None:
                    await db.rollback()
                    return None

                invite_id = invite["invite_id"]
                target_student_id = invite["target_student_id"]
                family_id = invite["family_id"]
                class_id = invite["class_id"]
                group_id = invite["group_id"]

                user_cursor = await db.execute(
                    """
                    SELECT
                        user_id,
                        family_id
                    FROM users
                    WHERE user_id = ?
                    """,
                    (telegram_user_id,),
                )

                telegram_user = await user_cursor.fetchone()

                if telegram_user is None:
                    await db.rollback()
                    return None

                # Пользователь уже в семье: запрещаем перенос
                # по claim link в другую или даже ту же семью.
                if telegram_user["family_id"] is not None:
                    await db.rollback()
                    return None

                source_cursor = await db.execute(
                    """
                    SELECT
                        id,
                        family_id
                    FROM student_profiles
                    WHERE telegram_user_id = ?
                    AND is_active = 1
                    """,
                    (telegram_user_id,),
                )

                source_student = await source_cursor.fetchone()

                # Если Telegram связан с profile другой семьи,
                # это не standalone merge, а запрещённый family transfer.
                if (
                    source_student is not None
                    and source_student["family_id"] is not None
                ):
                    await db.rollback()
                    return None

                source_student_id = (
                    source_student["id"]
                    if source_student is not None
                    else None
                )

                # 1. Сначала переносим занятия standalone child
                # в canonical family student profile.
                if source_student_id is not None:
                    await db.execute(
                        """
                        UPDATE extra_classes
                        SET
                            student_id = ?,
                            family_id = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE student_id = ?
                        """,
                        (
                            target_student_id,
                            family_id,
                            source_student_id,
                        ),
                    )

                    # 2. Telegram ID должен стать свободным до
                    # привязки к canonical profile.
                    detached_cursor = await db.execute(
                        """
                        UPDATE student_profiles
                        SET
                            telegram_user_id = NULL,
                            is_active = 0,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        AND telegram_user_id = ?
                        AND family_id IS NULL
                        AND is_active = 1
                        """,
                        (
                            source_student_id,
                            telegram_user_id,
                        ),
                    )

                    if detached_cursor.rowcount != 1:
                        await db.rollback()
                        return None

                # 3. Одноразово consume claim token.
                consume_cursor = await db.execute(
                    """
                    UPDATE student_claim_invites
                    SET
                        used_by_user_id = ?,
                        used_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    AND is_revoked = 0
                    AND used_at IS NULL
                    AND used_by_user_id IS NULL
                    AND expires_at > CURRENT_TIMESTAMP
                    """,
                    (
                        telegram_user_id,
                        invite_id,
                    ),
                )

                if consume_cursor.rowcount != 1:
                    await db.rollback()
                    return None

                # 4. Virtual student становится canonical Telegram profile.
                target_cursor = await db.execute(
                    """
                    UPDATE student_profiles
                    SET
                        telegram_user_id = ?,
                        name = ?,
                        is_active = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    AND family_id = ?
                    AND telegram_user_id IS NULL
                    AND is_active = 1
                    """,
                    (
                        telegram_user_id,
                        name,
                        target_student_id,
                        family_id,
                    ),
                )

                if target_cursor.rowcount != 1:
                    await db.rollback()
                    return None

                # 5. Имя ребёнка берётся из claim flow.
                # Class/group берём у family virtual student profile.
                await db.execute(
                    """
                    UPDATE users
                    SET
                        name = ?,
                        role = 'child',
                        family_id = ?,
                        class_id = ?,
                        group_id = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                    """,
                    (
                        name,
                        family_id,
                        class_id,
                        group_id,
                        telegram_user_id,
                    ),
                )

                # Единственная актуальная модель доступа взрослых к student profile.
                await self._ensure_parent_student_settings_for_family(
                    db=db,
                    family_id=family_id,
                )

                await db.commit()

            except Exception:
                await db.rollback()
                raise

        return await self.get_student_by_telegram_user_id(
            telegram_user_id=telegram_user_id,
        )