from __future__ import annotations

from typing import List, Optional

from core.models.dto import (
    ActionResponseDTO,
    ScheduleWatchTargetDTO,
)
from core.repository.watch_target_repository import (
    WatchTargetRepository,
)


class WatchTargetsService:
    """
    Бизнес-логика самостоятельного отслеживания классов.
    """

    MAX_TARGETS_PER_USER = 10

    def __init__(
        self,
        repository: WatchTargetRepository,
    ):
        self.repo = repository

    @staticmethod
    def _dto_from_row(
        row: dict,
    ) -> ScheduleWatchTargetDTO:
        return ScheduleWatchTargetDTO(
            id=row["id"],
            owner_user_id=row["owner_user_id"],
            class_id=row["class_id"],
            group_id=row["group_id"],
            title=row.get("title"),
            is_enabled=bool(row["is_enabled"]),
            receive_schedule_changes=bool(
                row.get("receive_schedule_changes", True)
            ),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    async def get_targets(
        self,
        *,
        owner_user_id: int,
        enabled_only: bool = False,
    ) -> List[ScheduleWatchTargetDTO]:
        rows = await self.repo.get_watch_targets(
            owner_user_id=owner_user_id,
            enabled_only=enabled_only,
        )

        return [
            self._dto_from_row(row)
            for row in rows
        ]

    async def add_target(
        self,
        *,
        owner_user_id: int,
        class_id: str,
        group_id: str,
        title: Optional[str] = None,
    ) -> ActionResponseDTO:
        """
        Добавляет отслеживаемый класс.

        Ограничение в 10 целей защищает от случайного/массового добавления.
        """
        class_id = class_id.strip()
        group_id = group_id.strip() or "ALL"

        if not class_id:
            return ActionResponseDTO(
                success=False,
                error_code="invalid_class",
            )

        current_targets = await self.get_targets(
            owner_user_id=owner_user_id,
        )

        if len(current_targets) >= self.MAX_TARGETS_PER_USER:
            return ActionResponseDTO(
                success=False,
                error_code="limit_reached",
            )

        row = await self.repo.create_watch_target(
            owner_user_id=owner_user_id,
            class_id=class_id,
            group_id=group_id,
            title=title.strip() if title else None,
        )

        if row is None:
            return ActionResponseDTO(
                success=False,
                error_code="duplicate",
            )

        return ActionResponseDTO(
            success=True,
            data=self._dto_from_row(row),
        )

    async def delete_target(
        self,
        *,
        owner_user_id: int,
        target_id: int,
    ) -> ActionResponseDTO:
        deleted = await self.repo.delete_watch_target(
            owner_user_id=owner_user_id,
            target_id=target_id,
        )

        if not deleted:
            return ActionResponseDTO(
                success=False,
                error_code="not_found",
            )

        return ActionResponseDTO(success=True)
    
    
    async def set_target_enabled(
        self,
        *,
        owner_user_id: int,
        target_id: int,
        is_enabled: bool,
    ) -> ActionResponseDTO:
        updated = await self.repo.set_watch_target_enabled(
            owner_user_id=owner_user_id,
            target_id=target_id,
            is_enabled=is_enabled,
        )

        if not updated:
            return ActionResponseDTO(
                success=False,
                error_code="not_found",
            )

        return ActionResponseDTO(success=True)
    
    async def get_target(
        self,
        *,
        owner_user_id: int,
        target_id: int,
    ) -> Optional[ScheduleWatchTargetDTO]:
        """
        Возвращает watch target только его владельцу.
        """
        row = await self.repo.get_watch_target(
            owner_user_id=owner_user_id,
            target_id=target_id,
        )

        if row is None:
            return None

        return self._dto_from_row(row)
    
    async def set_target_receive_schedule_changes(
        self,
        *,
        owner_user_id: int,
        target_id: int,
        receive_schedule_changes: bool,
    ) -> ActionResponseDTO:
        """
        Включает или выключает уведомления об изменениях
        для самостоятельно отслеживаемого класса.
        """
        updated = await self.repo.set_watch_target_receive_schedule_changes(
            owner_user_id=owner_user_id,
            target_id=target_id,
            receive_schedule_changes=receive_schedule_changes,
        )

        if not updated:
            return ActionResponseDTO(
                success=False,
                error_code="not_found",
            )

        return ActionResponseDTO(success=True)