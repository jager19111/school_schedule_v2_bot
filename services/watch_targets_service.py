# services/watch_targets_service.py

from __future__ import annotations

from typing import Optional

from core.models.dto import (
    ActionResponseDTO,
    ScheduleWatchTargetDTO,
)
from core.repository.watch_target_repository import WatchTargetRepository

MAX_TARGETS_PER_USER = 10


class WatchTargetsService:
    """Тонкий фасад управления watch targets: repo -> DTO/ActionResponseDTO."""

    def __init__(self, repository: WatchTargetRepository) -> None:
        self.repo = repository

    async def get_targets(
        self,
        *,
        owner_user_id: int,
        enabled_only: bool = False,
    ) -> list[ScheduleWatchTargetDTO]:
        return await self.repo.get_watch_targets(
            owner_user_id=owner_user_id,
            enabled_only=enabled_only,
        )

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

        # COUNT(*) вместо загрузки всех DTO: O(1) по памяти и меньше
        # данных через aiosqlite. Race condition всё равно закрывается
        # UNIQUE(owner_user_id, class_id, group_id) в INSERT.
        if await self.repo.count_watch_targets(owner_user_id) >= MAX_TARGETS_PER_USER:
            return ActionResponseDTO(
                success=False,
                error_code="limit_reached",
            )

        target = await self.repo.create_watch_target(
            owner_user_id=owner_user_id,
            class_id=class_id,
            group_id=group_id,
            title=title.strip() if title else None,
        )

        if target is None:
            return ActionResponseDTO(
                success=False,
                error_code="duplicate",
            )

        return ActionResponseDTO(success=True, data=target)

    async def get_target(
        self,
        *,
        owner_user_id: int,
        target_id: int,
    ) -> ScheduleWatchTargetDTO | None:
        return await self.repo.get_watch_target(
            owner_user_id=owner_user_id,
            target_id=target_id,
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
        return ActionResponseDTO(
            success=deleted,
            error_code=None if deleted else "not_found",
        )

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
        return ActionResponseDTO(
            success=updated,
            error_code=None if updated else "not_found",
        )

    async def set_target_receive_schedule_changes(
        self,
        *,
        owner_user_id: int,
        target_id: int,
        receive_schedule_changes: bool,
    ) -> ActionResponseDTO:
        updated = await self.repo.set_watch_target_receive_schedule_changes(
            owner_user_id=owner_user_id,
            target_id=target_id,
            receive_schedule_changes=receive_schedule_changes,
        )
        return ActionResponseDTO(
            success=updated,
            error_code=None if updated else "not_found",
        )
