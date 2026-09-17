# core/mappers/extra_class_mapper.py
#
# ШАГ 1 плана рефакторинга: единый маппер доп. занятий.
# Вся перекладка полей (row -> DTO -> ViewModel) и хардкод
# названий дней недели вынесены из ExtraClassesService сюда.
#
# Паттерн соответствует NotificationMapper: маппер принимает
# Mapping-строки (после BaseRepository._process_row) и возвращает
# строго типизированные DTO/ViewModel.

from __future__ import annotations

from typing import Iterable, List, Mapping, Optional

from core.models.dto import (
    ExtraClassDTO,
    ExtraClassItemDTO,
    ExtraClassListDTO,
    ExtraClassViewModel,
)


class ExtraClassMapper:
    """Row -> ExtraClassDTO/ExtraClassItemDTO -> ExtraClassViewModel."""

    # Названия дней недели: принадлежат домену, не UI-слою.
    DAYS_RU: dict[int, str] = {
        1: "Понедельник",
        2: "Вторник",
        3: "Среда",
        4: "Четверг",
        5: "Пятница",
        6: "Суббота",
        7: "Воскресенье",
    }

    UNKNOWN_DAY_TEXT = "Неизвестно"
    LOCATION_FALLBACK = "Не указано"
    DEFAULT_REMINDER_MINUTES = 30

    # ==========================================================
    # Row -> DTO
    # ==========================================================

    @staticmethod
    def to_dto(row: Mapping) -> ExtraClassDTO:
        """Полное занятие (для update-логики и диагностики)."""
        return ExtraClassDTO(
            id=int(row["id"]),
            family_id=(
                int(row["family_id"])
                if row.get("family_id") is not None
                else None
            ),
            student_id=int(row["student_id"]),
            day_of_week=int(row["day_of_week"]),
            time_start=str(row["time_start"]),
            time_end=str(row["time_end"]),
            title=str(row["title"]),
            location=(
                str(row["location"])
                if row.get("location") is not None
                else None
            ),
            reminder_minutes=int(
                row.get("reminder_minutes")
                or ExtraClassMapper.DEFAULT_REMINDER_MINUTES
            ),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    @staticmethod
    def to_item_dto(row: Mapping) -> ExtraClassItemDTO:
        """Элемент списка занятий (лёгкий DTO без служебных полей)."""
        return ExtraClassItemDTO(
            id=int(row["id"]),
            day_of_week=int(row["day_of_week"]),
            time_start=str(row["time_start"]),
            time_end=str(row["time_end"]),
            title=str(row["title"]),
            location=(
                str(row["location"])
                if row.get("location") is not None
                else None
            ),
            reminder_minutes=int(
                row.get("reminder_minutes")
                or ExtraClassMapper.DEFAULT_REMINDER_MINUTES
            ),
        )

    @staticmethod
    def to_item_list(rows: Iterable[Mapping]) -> List[ExtraClassItemDTO]:
        return [ExtraClassMapper.to_item_dto(row) for row in rows]

    @staticmethod
    def to_list_dto(rows: Iterable[Mapping]) -> ExtraClassListDTO:
        return ExtraClassListDTO(items=ExtraClassMapper.to_item_list(rows))

    # ==========================================================
    # DTO -> ViewModel (рендер в UI)
    # ==========================================================

    @staticmethod
    def to_view_model(item: ExtraClassItemDTO) -> ExtraClassViewModel:
        """Day-of-week int -> текст, location -> fallback."""
        return ExtraClassViewModel(
            id=item.id,
            day_of_week=item.day_of_week,
            day_of_week_text=ExtraClassMapper.DAYS_RU.get(
                item.day_of_week,
                ExtraClassMapper.UNKNOWN_DAY_TEXT,
            ),
            time_start=item.time_start,
            time_end=item.time_end,
            title=item.title,
            location=(
                item.location
                if item.location
                else ExtraClassMapper.LOCATION_FALLBACK
            ),
            reminder_minutes=item.reminder_minutes,
        )

    @staticmethod
    def to_view_models(
        items: Iterable[ExtraClassItemDTO],
        *,
        sort: bool = True,
    ) -> List[ExtraClassViewModel]:
        """ViewModel-список; сортировка (day_of_week, time_start)."""
        view_models = [
            ExtraClassMapper.to_view_model(item)
            for item in items
        ]
        if sort:
            view_models.sort(
                key=lambda vm: (vm.day_of_week, vm.time_start),
            )
        return view_models
