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
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
                (user_id,),
            )
            await db.execute(
                "UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()

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

    async def get_user_profile_for_dto(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Возвращает только нужные поля для UserProfileDTO.
        """
        return await self._fetch_one(
            """
            SELECT role, class_id, group_id, family_id, parent_control_notifications
            FROM users WHERE user_id = ?
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

    # ========== FAMILIES ==========

    async def create_family_and_link(self, admin_user_id: int) -> str:
        """
        Создаёт семью и привязывает создателя как parent.

        Возвращает family_code.
        """
        family_code = str(uuid.uuid4())[:8].upper()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO families (family_code, admin_user_id, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (family_code, admin_user_id),
            )
            family_id = cursor.lastrowid

            await db.execute(
                "UPDATE users SET family_id = ?, role = 'parent' WHERE user_id = ?",
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

    async def link_user_to_family(self, user_id: int, family_id: int, role: str) -> None:
        """
        Привязывает пользователя к семье и обновляет роль.
        """
        await self._execute(
            "UPDATE users SET family_id = ?, role = ? WHERE user_id = ?",
            (family_id, role, user_id),
        )

    async def set_child_notifications_lock_flag(self, child_user_id: int, locked: bool) -> None:
        """
        Устанавливает флаг parent_control_notifications у ребёнка.
        """
        await self._execute(
            "UPDATE users SET parent_control_notifications = ? WHERE user_id = ?",
            (int(locked), child_user_id),
        )

    async def check_parent_child_same_family(self, parent_user_id: int, child_user_id: int) -> bool:
        """
        Проверяет, что parent и child в одной семье и parent действительно 'parent'.
        """
        row = await self._fetch_one(
            """
            SELECT u1.family_id AS parent_family_id, u2.family_id AS child_family_id, u1.role AS parent_role
            FROM users u1
            JOIN users u2 ON u1.family_id = u2.family_id
            WHERE u1.user_id = ? AND u2.user_id = ?
            """,
            (parent_user_id, child_user_id),
        )
        return bool(row and row.get("parent_role") == "parent")

    # ========== CHILDREN LIST ==========

    async def get_children_for_parent_rows(self, parent_user_id: int) -> List[Dict[str, Any]]:
        """
        Возвращает список детей в виде dict-строк для родителя.
        """
        return await self._fetch_all(
            """
            SELECT user_id, class_id
            FROM users
            WHERE family_id = (SELECT family_id FROM users WHERE user_id = ?)
              AND role = 'child'
            """,
            (parent_user_id,),
        )