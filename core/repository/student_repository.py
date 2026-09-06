from __future__ import annotations

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
        Изменяет профиль ученика только family admin.
        """
        fields = []
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
            cursor = await db.execute(
                f"""
                UPDATE student_profiles
                SET {", ".join(fields)}
                WHERE id = ?
                  AND EXISTS (
                      SELECT 1
                      FROM families AS family
                      WHERE family.id = student_profiles.family_id
                        AND family.admin_user_id = ?
                  )
                """,
                (
                    *params,
                    student_id,
                    admin_user_id,
                ),
            )

            await db.commit()

        return cursor.rowcount == 1

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
            family_id: int,
            name: str,
            class_id: str,
            group_id: str,
        ) -> Optional[Dict[str, Any]]:
            """
            Инкапсулирует логику создания/обновления Telegram-ребёнка
            и синхронизации прав доступа в рамках одной транзакции.
            """
            async with self._connection() as db:
                await db.execute("BEGIN")
                try:
                    # 1. Проверяем наличие профиля
                    cursor = await db.execute(
                        "SELECT id FROM student_profiles WHERE telegram_user_id = ?",
                        (telegram_user_id,)
                    )
                    row = await cursor.fetchone()

                    # 2. Обновляем или создаем запись
                    if row:
                        await db.execute(
                            """
                            UPDATE student_profiles
                            SET family_id = ?, name = ?, class_id = ?, group_id = ?, is_active = 1, updated_at = CURRENT_TIMESTAMP
                            WHERE telegram_user_id = ?
                            """,
                            (family_id, name, class_id, group_id, telegram_user_id)
                        )
                    else:
                        await db.execute(
                            """
                            INSERT INTO student_profiles (family_id, telegram_user_id, name, class_id, group_id, is_active)
                            VALUES (?, ?, ?, ?, ?, 1)
                            """,
                            (family_id, telegram_user_id, name, class_id, group_id)
                        )

                    # Cleanup неактуальных прав при смене семьи
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

                    # 3. Синхронизируем настройки взрослых (метод уже есть в репозитории)
                    await self._ensure_parent_student_settings_for_family(db=db, family_id=family_id)
                    
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

            return await self.get_student_by_telegram_user_id(telegram_user_id=telegram_user_id)