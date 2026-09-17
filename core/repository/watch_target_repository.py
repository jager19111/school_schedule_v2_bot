# core/repository/watch_target_repository.py

from __future__ import annotations

from typing import Optional

from core.mappers.watch_target_mapper import WatchTargetMapper
from core.models.dto import ScheduleWatchTargetDTO
from core.repository.base_repository import BaseRepository
from services.time_service import TimeService

_WATCH_TARGET_COLUMNS = """
            id,
            owner_user_id,
            class_id,
            group_id,
            title,
            is_enabled,
            receive_schedule_changes,
            created_at,
            updated_at
"""


class WatchTargetRepository(BaseRepository):
    """DTO-first repository for user's school schedule watch targets."""

    def __init__(self, db_path, time_service: TimeService) -> None:
        super().__init__(db_path, time_service)

    async def create_watch_target(
        self,
        *,
        owner_user_id: int,
        class_id: str,
        group_id: str,
        title: Optional[str] = None,
    ) -> ScheduleWatchTargetDTO | None:
        """Создаёт target; None означает duplicate по UNIQUE-ограничению."""
        now_utc = self._now_utc_str()

        async with self._write_lock():
            async with self._connection() as db:
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
                    await db.commit()
                except Exception as exc:
                    await db.rollback()
                    if "unique constraint failed" in str(exc).lower():
                        return None
                    raise

                target_id = cursor.lastrowid

        # Один SELECT после INSERT больше не нужен: возвращаем DTO из
        # уже известных значений. Это экономит запрос на каждое создание.
        return ScheduleWatchTargetDTO(
            id=int(target_id),
            owner_user_id=owner_user_id,
            class_id=class_id,
            group_id=group_id,
            title=title,
            is_enabled=True,
            receive_schedule_changes=True,
            created_at=now_utc,
            updated_at=now_utc,
        )

    async def get_watch_target(
        self,
        *,
        owner_user_id: int,
        target_id: int,
    ) -> ScheduleWatchTargetDTO | None:
        """
        Возвращает одну цель только её владельцу.
        """
        row = await self._fetch_one(
            f"""
            SELECT {_WATCH_TARGET_COLUMNS}
            FROM schedule_watch_targets
            WHERE id = ? AND owner_user_id = ?
            """,
            (target_id, owner_user_id),
        )
        return WatchTargetMapper.to_dto(row) if row else None

    async def get_watch_targets(
        self,
        *,
        owner_user_id: int,
        enabled_only: bool = False,
    ) -> list[ScheduleWatchTargetDTO]:
        """
        Возвращает цели отслеживания пользователя.
        """
        enabled_clause = "AND is_enabled = 1" if enabled_only else ""
        rows = await self._fetch_all(
            f"""
            SELECT {_WATCH_TARGET_COLUMNS}
            FROM schedule_watch_targets
            WHERE owner_user_id = ? {enabled_clause}
            ORDER BY created_at, id
            """,
            (owner_user_id,),
        )
        return WatchTargetMapper.to_dto_list(rows)

    async def count_watch_targets(self, owner_user_id: int) -> int:
        row = await self._fetch_one(
            """
            SELECT COUNT(*) AS count
            FROM schedule_watch_targets
            WHERE owner_user_id = ?
            """,
            (owner_user_id,),
        )
        return int(row["count"]) if row else 0

    async def delete_watch_target(
        self,
        *,
        owner_user_id: int,
        target_id: int,
    ) -> bool:
        """
        Удаляет цель только её владельцу.
        """
        return (
            await self._execute(
                """
                DELETE FROM schedule_watch_targets
                WHERE id = ? AND owner_user_id = ?
                """,
                (target_id, owner_user_id),
            )
        ) == 1

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
        return (
            await self._execute(
                """
                UPDATE schedule_watch_targets
                SET is_enabled = ?, updated_at = ?
                WHERE id = ? AND owner_user_id = ?
                """,
                (
                    int(is_enabled),
                    self._now_utc_str(),
                    target_id,
                    owner_user_id,
                ),
            )
        ) == 1

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
        return (
            await self._execute(
                """
                UPDATE schedule_watch_targets
                SET receive_schedule_changes = ?, updated_at = ?
                WHERE id = ? AND owner_user_id = ?
                """,
                (
                    int(receive_schedule_changes),
                    self._now_utc_str(),
                    target_id,
                    owner_user_id,
                ),
            )
        ) == 1
