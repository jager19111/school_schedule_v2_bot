# services/watch_targets_service.py

from __future__ import annotations


from typing import Optional


from core.models.dto import (
    ActionResponseDTO,
    ScheduleWatchTargetDTO,
    SchoolDictionariesDTO,
)
from core.repository.watch_target_repository import WatchTargetRepository


MAX_TARGETS_PER_USER = 10


class WatchTargetsService:
    """
    Управление личными целями отслеживания расписания.

    Сервис является единственной точкой business-валидации:
    - class_id и group_id проверяются по актуальным NIKA-справочникам;
    - repository отвечает только за persistence и ownership;
    - bot и web не должны самостоятельно сохранять watch targets.
    """

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

    async def get_whole_class_target(
        self,
        *,
        owner_user_id: int,
        class_id: str,
    ) -> ScheduleWatchTargetDTO | None:
        """
        Возвращает personal target всего класса.

        Используется star toggle на school class pages.

        Group-specific targets не считаются whole-class target:
        - class_id="016", group_id="G1" → None;
        - class_id="016", group_id="ALL" → target.
        """
        normalized_class_id = self._normalize_class_id(
            class_id,
        )

        if not normalized_class_id:
            return None

        targets = await self.get_targets(
            owner_user_id=owner_user_id,
            enabled_only=False,
        )

        for target in targets:
            if (
                target.class_id == normalized_class_id
                and target.group_id.strip().upper() == "ALL"
            ):
                return target

        return None
    
    async def add_target_from_school_dictionaries(
        self,
        *,
        owner_user_id: int,
        class_id: str,
        group_id: str,
        dictionaries: SchoolDictionariesDTO,
        title: Optional[str] = None,
    ) -> ActionResponseDTO:
        """
        Создаёт watch target только для существующего класса/группы.

        `ALL` означает весь класс. Конкретные группы могут передаваться
        одной строкой через запятую, например: "G1,G2".

        Не доверяет данным UI: одинаково безопасен для Telegram и web form.
        """
        normalized_class_id = self._normalize_class_id(class_id)
        normalized_group_id = self._normalize_group_id(group_id)

        if not normalized_class_id:
            return ActionResponseDTO(
                success=False,
                error_code="invalid_class",
            )

        if normalized_class_id not in dictionaries.classes:
            return ActionResponseDTO(
                success=False,
                error_code="invalid_class",
            )

        if normalized_group_id is None:
            return ActionResponseDTO(
                success=False,
                error_code="invalid_group",
            )

        if normalized_group_id != "ALL":
            group_ids = normalized_group_id.split(",")

            if any(
                item not in dictionaries.groups
                for item in group_ids
            ):
                return ActionResponseDTO(
                    success=False,
                    error_code="invalid_group",
                )

        normalized_title = self._normalize_title(title)

        if normalized_title is None:
            readable_class_name = (
                dictionaries.get_readable_class(
                    normalized_class_id,
                ).strip()
            )
            normalized_title = (
                readable_class_name
                if readable_class_name and readable_class_name != "—"
                else normalized_class_id
            )

        return await self._add_target(
            owner_user_id=owner_user_id,
            class_id=normalized_class_id,
            group_id=normalized_group_id,
            title=normalized_title,
        )

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
        updated = (
            await self.repo.set_watch_target_receive_schedule_changes(
                owner_user_id=owner_user_id,
                target_id=target_id,
                receive_schedule_changes=receive_schedule_changes,
            )
        )
        return ActionResponseDTO(
            success=updated,
            error_code=None if updated else "not_found",
        )

    async def _add_target(
        self,
        *,
        owner_user_id: int,
        class_id: str,
        group_id: str,
        title: Optional[str],
    ) -> ActionResponseDTO:
        """
        Persistence-часть создания уже нормализованной и проверенной цели.

        Этот метод намеренно private: публичные callers должны использовать
        add_target_from_school_dictionaries(), а не обходить NIKA validation.
        """
        if (
            await self.repo.count_watch_targets(
                owner_user_id,
            )
            >= MAX_TARGETS_PER_USER
        ):
            return ActionResponseDTO(
                success=False,
                error_code="limit_reached",
            )

        target = await self.repo.create_watch_target(
            owner_user_id=owner_user_id,
            class_id=class_id,
            group_id=group_id,
            title=title,
        )

        if target is None:
            return ActionResponseDTO(
                success=False,
                error_code="duplicate",
            )

        return ActionResponseDTO(
            success=True,
            data=target,
        )

    @staticmethod
    def _normalize_class_id(
        class_id: str | None,
    ) -> str:
        return str(class_id or "").strip()

    @staticmethod
    def _normalize_title(
        title: str | None,
    ) -> str | None:
        normalized = str(title or "").strip()
        return normalized or None

    @staticmethod
    def _normalize_group_id(
        group_id: str | None,
    ) -> str | None:
        """
        Нормализует группу в canonical DB representation.

        Возвращает:
        - "ALL" для пустого значения и whole-class target;
        - "G1,G2" для нескольких конкретных групп;
        - None для недопустимой комбинации ALL с конкретной группой.
        """
        raw_value = str(group_id or "").strip()

        if not raw_value:
            return "ALL"

        if raw_value.upper() == "ALL":
            return "ALL"

        group_ids = [
            item.strip()
            for item in raw_value.split(",")
            if item.strip()
        ]

        if not group_ids:
            return "ALL"

        if any(
            item.upper() == "ALL"
            for item in group_ids
        ):
            return None

        return ",".join(group_ids)