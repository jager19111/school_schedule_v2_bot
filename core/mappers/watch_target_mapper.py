# core/mappers/watch_target_mapper.py

from __future__ import annotations

from typing import Iterable, Mapping

from core.models.dto import (
    ScheduleWatchTargetDTO,
    SchoolDictionariesDTO,
    WatchTargetViewModel,
)


class WatchTargetMapper:
    """Преобразование DB-row -> DTO -> ViewModel для watch targets."""

    @staticmethod
    def to_dto(row: Mapping) -> ScheduleWatchTargetDTO:
        return ScheduleWatchTargetDTO(
            id=int(row["id"]),
            owner_user_id=int(row["owner_user_id"]),
            class_id=str(row["class_id"]),
            group_id=str(row.get("group_id") or "ALL"),
            title=row.get("title"),
            is_enabled=bool(row.get("is_enabled")),
            receive_schedule_changes=bool(
                row.get("receive_schedule_changes", 1)
            ),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    @staticmethod
    def to_dto_list(rows: Iterable[Mapping]) -> list[ScheduleWatchTargetDTO]:
        return [WatchTargetMapper.to_dto(row) for row in rows]

    @staticmethod
    def to_view_model(
        target: ScheduleWatchTargetDTO,
        dictionaries: SchoolDictionariesDTO,
    ) -> WatchTargetViewModel:
        class_name = dictionaries.get_readable_class(target.class_id)
        group_name = dictionaries.get_readable_group(target.group_id)
        title = target.title or class_name

        return WatchTargetViewModel(
            target_id=target.id,
            title=title,
            class_name=class_name,
            group_name=group_name,
            is_enabled_text=(
                "🟢 Активно" if target.is_enabled else "⚫ Пауза"
            ),
            changes_notify_text=(
                "🔔 Включены"
                if target.receive_schedule_changes
                else "🔕 Выключены"
            ),
            telegram_status="📱 Подписка активна",
            is_enabled=target.is_enabled,
            receive_schedule_changes=target.receive_schedule_changes,
        )

    @staticmethod
    def to_view_models(
        targets: Iterable[ScheduleWatchTargetDTO],
        dictionaries: SchoolDictionariesDTO,
    ) -> list[WatchTargetViewModel]:
        return [
            WatchTargetMapper.to_view_model(target, dictionaries)
            for target in targets
        ]
