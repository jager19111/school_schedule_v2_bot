from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from core.models.dto import ExtraClassDTO, ExtraClassItemDTO
from web.schemas import (
    LessonKind,
    LessonStatus,
    LessonViewMode,
    WebChangedValue,
    WebExtraClass,
    WebExtraClassDay,
    WebLesson,
    WebLessonEntry,
    WebRoomBadge,
)


WEEKDAYS_RU = {
    1: "Понедельник",
    2: "Вторник",
    3: "Среда",
    4: "Четверг",
    5: "Пятница",
    6: "Суббота",
    7: "Воскресенье",
}


def extra_class_to_web_lesson(
    *,
    extra_id: int,
    title: str,
    time_start: str,
    time_end: str,
    location: str | None,
) -> WebLesson:
    """
    Extra-class data -> reusable purple LessonCard presentation model.

    This is web presentation mapping only:
    - no repository access;
    - no permission decision;
    - no domain mutation;
    - no fake LessonInstance creation.
    """
    normalized_title = (title or "").strip()
    normalized_location = (location or "").strip() or None

    display_title = normalized_title or "Без названия"

    entries = [
        WebLessonEntry(
            subject=WebChangedValue(
                value=display_title,
                changed=False,
            ),
            room=(
                WebRoomBadge(
                    value=normalized_location,
                    changed=False,
                )
                if normalized_location
                else None
            ),
        )
    ]

    aria_parts = [
        "Дополнительное занятие",
        display_title,
        f"{time_start}–{time_end}",
    ]

    if normalized_location:
        aria_parts.append(f"Место: {normalized_location}")

    return WebLesson(
        key=f"extra-{extra_id}",
        number=None,
        display_number=None,
        start_time=time_start,
        end_time=time_end,
        view_mode=LessonViewMode.STUDENT,
        kind=LessonKind.EXTRA,
        status=LessonStatus.NORMAL,
        is_current=False,
        entries=entries,
        shared_subject=False,
        shared_room=None,
        window_label=None,
        has_inline_changes=False,
        change_details=[],
        history_url=None,
        aria_label=". ".join(aria_parts),
    )


def build_web_extra_class(
    *,
    extra_id: int,
    day_of_week: int,
    time_start: str,
    time_end: str,
    title: str,
    location: str | None,
    reminder_minutes: int,
) -> WebExtraClass:
    """
    Builds the complete typed web model.

    This shared factory is used for:
    - persisted ExtraClassDTO / ExtraClassItemDTO;
    - submitted form values after validation/conflict error;
    - future client-side/preview adapters.
    """
    weekday_display = WEEKDAYS_RU.get(day_of_week, "—")
    normalized_title = (title or "").strip()
    normalized_location = (location or "").strip() or None

    return WebExtraClass(
        id=extra_id,
        day_of_week=day_of_week,
        weekday_display=weekday_display,
        time_start=time_start,
        time_end=time_end,
        title=normalized_title,
        location=normalized_location,
        reminder_minutes=reminder_minutes,
        lesson=extra_class_to_web_lesson(
            extra_id=extra_id,
            title=normalized_title,
            time_start=time_start,
            time_end=time_end,
            location=normalized_location,
        ),
    )


def extra_class_to_web(
    item: ExtraClassDTO | ExtraClassItemDTO,
) -> WebExtraClass:
    """Persisted extra-class DTO -> complete typed web presentation model."""

    return build_web_extra_class(
        extra_id=item.id,
        day_of_week=item.day_of_week,
        time_start=item.time_start,
        time_end=item.time_end,
        title=item.title,
        location=item.location,
        reminder_minutes=item.reminder_minutes,
    )


def group_by_weekday(
    items: Iterable[WebExtraClass],
) -> list[WebExtraClassDay]:
    """Groups typed extra-class web models by weekday."""

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