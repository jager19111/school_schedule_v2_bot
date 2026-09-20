"""Сборка PosterRequest из DayScheduleDTO и версионированные ключи кэша.

Ключи (ТЗ v2.2, раздел 3.3, с правками из обсуждения):
- глобальный (поиск по школе): 25 учеников класса = 1 рендер;
- персональный: принадлежит профилю РЕБЁНКА, а не смотрящему —
  мама, папа и сам ребёнок шарят один постер с доп. занятиями.

Версия расписания — semantic-хэш NIKA (см. services/image_render/version.py):
новая версия = новый ключ, инвалидация не нужна.
"""

from __future__ import annotations

import hashlib
from typing import Iterable

from core.models.dto import DayScheduleDTO, ExtraClassItemDTO
from services.image_render.models import (
    LessonStatus,
    PosterLessonCard,
    PosterRequest,
)


def build_global_request_id(
    schedule_version: str | int,
    class_id: str,
    group_id: str,
    date_iso: str,
) -> str:
    """Ключ L1/L2 для расписания класса+группы на дату."""
    return f"img_v{schedule_version}_{class_id}_{group_id or 'ALL'}_{date_iso}"


def build_personal_request_id(
    schedule_version: str | int,
    student_profile_id: int,
    date_iso: str,
    extra_hash: str,
) -> str:
    """Ключ L1/L2 для персонального постера ребёнка (с доп. занятиями)."""
    return f"imgp_v{schedule_version}_{student_profile_id}_{date_iso}_{extra_hash}"


def extra_classes_hash(items: Iterable[ExtraClassItemDTO]) -> str:
    """Стабильный хэш состава доп. занятий — часть персонального ключа."""
    payload = "|".join(
        f"{item.day_of_week}:{item.time_start}-{item.time_end}:{item.title}"
        for item in sorted(
            items,
            key=lambda i: (i.day_of_week, i.time_start or "", i.title or ""),
        )
    )
    if not payload:
        return "noextra"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def build_poster_request(
    *,
    request_id: str,
    dto: DayScheduleDTO,
    title: str,
    date_text: str,
    subtitle: str | None = None,
    width: int = 1080,
) -> PosterRequest:
    """DayScheduleDTO -> PosterRequest (маппинг статусов раздела 6 ТЗ)."""
    cards: list[PosterLessonCard] = []
    changes_count = 0
    for lesson in dto.lessons:
        if lesson.is_cancelled:
            status = LessonStatus.CANCELLED
        elif lesson.is_extra:
            status = LessonStatus.EXTRA
        elif lesson.is_exchange:
            status = LessonStatus.EXCHANGE
        elif lesson.is_methodological:
            status = LessonStatus.METHODICAL
        else:
            status = LessonStatus.NORMAL

        if lesson.is_extra:
            num = "Доп."
        else:
            num = str(lesson.display_num or lesson.lesson_num or "•")

        cards.append(
            PosterLessonCard(
                num=num,
                time_start=lesson.start_time or "—",
                time_end=lesson.end_time or "—",
                subject=lesson.subject_name or lesson.original_subject_name or "Урок",
                status=status,
                teacher=lesson.teacher_name,
                room=lesson.room_name,
                group=lesson.group_name,
                original_subject=(
                    lesson.original_subject_name if lesson.is_exchange else None
                ),
            )
        )
        if not lesson.is_extra and (lesson.is_exchange or lesson.is_cancelled):
            changes_count += 1

    return PosterRequest(
        request_id=request_id,
        date_text=date_text,
        title=title,
        lessons=tuple(cards),
        subtitle=subtitle,
        changes_count=changes_count,
        width=width,
    )
