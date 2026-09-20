"""Доменные модели постера расписания.

Единственный формат данных для обеих реализаций RendererPort —
движок рендера не знает про NIKA, БД, Telegram и DayScheduleDTO.
Преобразование DayScheduleDTO -> PosterRequest появится в сервисе (этап 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LessonStatus(str, Enum):
    """Статус карточки урока — определяет цвет левой границы (раздел 6 ТЗ)."""

    NORMAL = "normal"              # синий — обычный урок
    EXCHANGE = "exchange"          # красный — замена предмета или кабинета
    CANCELLED = "cancelled"        # серый — отменённый урок
    EXTRA = "extra"                # фиолетовый — дополнительное занятие
    METHODICAL = "methodological"  # оранжевый — методический час/день


@dataclass(frozen=True, slots=True)
class PosterLessonCard:
    """Одна карточка урока на постере."""

    num: str                             # отображаемый номер: "2", "2*", "Доп."
    time_start: str
    time_end: str
    subject: str
    status: LessonStatus = LessonStatus.NORMAL
    teacher: str | None = None
    room: str | None = None
    group: str | None = None
    original_subject: str | None = None  # при замене: что было до неё


@dataclass(frozen=True, slots=True)
class PosterRequest:
    """Запрос на рендер постера; request_id = ключ кэшей L1/L2."""

    request_id: str
    date_text: str                        # "Понедельник, 21.09"
    title: str                            # "Расписание · 5А"
    lessons: tuple[PosterLessonCard, ...]
    subtitle: str | None = None           # "Иван · Группа 1"
    changes_count: int = 0                # для бейджа в шапке
    width: int = 1080                     # переживает JPEG-компрессию Telegram


@dataclass(frozen=True, slots=True)
class RenderedPoster:
    """Результат рендера: PNG-байты и габариты постера."""

    request_id: str
    png_bytes: bytes
    width: int
    height: int
