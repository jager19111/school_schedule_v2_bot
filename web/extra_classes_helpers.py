# web/extra_classes_helpers.py
#
# Typed mapping internal ExtraClassItemDTO -> WebExtraClass.
# Web schemas live in web/schemas.py; this module contains only
# presentation mapping/grouping rules and no generic dict/object access.

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from core.models.dto import ExtraClassDTO, ExtraClassItemDTO
from web.schemas import WebExtraClass, WebExtraClassDay


WEEKDAYS_RU = {
    1: "Понедельник",
    2: "Вторник",
    3: "Среда",
    4: "Четверг",
    5: "Пятница",
    6: "Суббота",
    7: "Воскресенье",
}


def extra_class_to_web(
    item: ExtraClassDTO | ExtraClassItemDTO,
) -> WebExtraClass:
    """ExtraClassItemDTO -> typed web presentation model."""

    day_of_week = item.day_of_week

    return WebExtraClass(
        id=item.id,
        day_of_week=day_of_week,
        weekday_display=WEEKDAYS_RU.get(day_of_week, "—"),
        time_start=item.time_start,
        time_end=item.time_end,
        title=item.title,
        location=item.location,
        reminder_minutes=item.reminder_minutes,
    )


def group_by_weekday(
    items: Iterable[WebExtraClass],
) -> list[WebExtraClassDay]:
    """Group typed extra-class web models by weekday without raw dicts."""

    grouped: dict[int, list[WebExtraClass]] = defaultdict(list)

    for item in items:
        grouped[item.day_of_week].append(item)

    return [
        WebExtraClassDay(
            day_of_week=day_of_week,
            weekday_display=WEEKDAYS_RU.get(day_of_week, "—"),
            items=sorted(
                day_items,
                key=lambda item: (
                    item.time_start,
                    item.time_end,
                    item.id,
                ),
            ),
        )
        for day_of_week, day_items in sorted(grouped.items())
    ]