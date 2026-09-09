# core/repository/watch_target_repository.py
#
# РЕШЁННЫЕ ПРОБЛЕМЫ:
#
# 1. УДАЛЁН дубликат метода get_watch_target: метод был объявлен
#    в классе ДВАЖДЫ (второе определение перекрывало первое).
#    Это была реальная ошибка, мешавшая рефакторингу.
#
# 2. Strict Time Governance: CURRENT_TIMESTAMP в
#    set_watch_target_enabled и set_watch_target_receive_schedule_changes
#    заменён на параметр now_utc из TimeService.
#
# 3. create_watch_target явно передаёт created_at/updated_at —
#    дефолтов в схеме больше нет.
#
# 4. Транзакция INSERT обёрнута в self._write_lock().

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.repository.base_repository import BaseRepository


class WatchTargetRepository(BaseRepository):
    """
    CRUD самостоятельных целей отслеживания классов.

    Каждая запись принадлежит одному Telegram-пользователю.
    """

    async def create_watch_target(
        self,
        *,
        owner_user_id: int,
        class_id: str,
        group_id: str,
        title: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Создаёт новую цель отслеживания.

        Возвращает None при duplicate target.
        """
        now_utc = self._now_utc_str()
        async with self._write_lock():
            async with self._connection() as db:
                await db.execute("BEGIN")
                try:
                    cursor = await db.execute(
                        """
                        INSERT INTO schedule_watch_targets (
                            owner_user_id,
                            class_id,
                            group_id,
                            title,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            owner_user_id,
                            class_id,
                            group_id,
                            title,
                            now_utc,
                            now_utc,
                        ),
                    )
                    target_id = cursor.lastrowid
                    await db.commit()
                except Exception as exc:
                    await db.rollback()
                    message = str(exc).lower()
                    if "unique constraint failed" in message:
                        return None
                    raise

        return await self.get_watch_target(
            owner_user_id=owner_user_id,
            target_id=target_id,
        )

    async def get_watch_target(
        self,
        *,
        owner_user_id: int,
        target_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает одну цель только её владельцу.
        """
        return await self._fetch_one(
            """
            SELECT
                id,
                owner_user_id,
                class_id,
                group_id,
                title,
                is_enabled,
                receive_schedule_changes,
                created_at,
                updated_at
            FROM schedule_watch_targets
            WHERE id = ?
              AND owner_user_id = ?
            """,
            (
                target_id,
                owner_user_id,
            ),
        )

    async def get_watch_targets(
        self,
        *,
        owner_user_id: int,
        enabled_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает цели отслеживания пользователя.
        """
        if enabled_only:
            query = """
                SELECT
                    id,
                    owner_user_id,
                    class_id,
                    group_id,
                    title,
                    is_enabled,
                    receive_schedule_changes,
                    created_at,
                    updated_at
                FROM schedule_watch_targets
                WHERE owner_user_id = ?
                  AND is_enabled = 1
                ORDER BY created_at, id
            """
        else:
            query = """
                SELECT
                    id,
                    owner_user_id,
                    class_id,
                    group_id,
                    title,
                    is_enabled,
                    receive_schedule_changes,
                    created_at,
                    updated_at
                FROM schedule_watch_targets
                WHERE owner_user_id = ?
                ORDER BY created_at, id
            """

        return await self._fetch_all(
            query,
            (owner_user_id,),
        )

    async def delete_watch_target(
        self,
        *,
        owner_user_id: int,
        target_id: int,
    ) -> bool:
        """
        Удаляет цель только её владельцу.
        """
        changed = await self._execute(
            """
            DELETE FROM schedule_watch_targets
            WHERE id = ?
              AND owner_user_id = ?
            """,
            (
                target_id,
                owner_user_id,
            ),
        )

        return changed == 1

    async def set_watch_target_enabled(
        self,
        *,
        owner_user_id: int,
        target_id: int,
        is_enabled: bool,
    ) -> bool:
        """
        Включает или выключает цель без удаления.
        """
        changed = await self._execute(
            """
            UPDATE schedule_watch_targets
            SET
                is_enabled = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
            """,
            (
                int(is_enabled),
                self._now_utc_str(),
                target_id,
                owner_user_id,
            ),
        )

        return changed == 1

    async def set_watch_target_receive_schedule_changes(
        self,
        *,
        owner_user_id: int,
        target_id: int,
        receive_schedule_changes: bool,
    ) -> bool:
        """
        Включает или выключает уведомления об изменениях
        для одного watch target.
        """
        changed = await self._execute(
            """
            UPDATE schedule_watch_targets
            SET
                receive_schedule_changes = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
            """,
            (
                int(receive_schedule_changes),
                self._now_utc_str(),
                target_id,
                owner_user_id,
            ),
        )

        return changed == 1
