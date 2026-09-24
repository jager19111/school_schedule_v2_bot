"""Доменные модели постера расписания.

Единственный формат данных для обеих реализаций RendererPort —
движок рендера не знает про NIKA, БД, Telegram и DayScheduleDTO.
Преобразование DayScheduleDTO -> PosterRequest появится в сервисе (этап 2).
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class LessonStatus(str, Enum):
    NORMAL = "normal"              # синий — обычный урок
    EXCHANGE = "exchange"          # оранжевый — замена предмета или кабинета
    CANCELLED = "cancelled"        # красный — отменённый урок
    EXTRA = "extra"                # фиолетовый — доп. занятие
    METHODICAL = "methodological"  # серый — методический час

@dataclass(frozen=True, slots=True)
class PosterItem:
    """Один элемент внутри временного слота (предмет + препод + кабинет)."""
    primary_text: str          # Ученик: Предмет / Учитель: Класс · Группа
    secondary_text: str | None # Ученик: Учитель / Учитель: Предмет
    room: str | None           # Кабинет
    is_cancelled: bool = False
    original_primary: str | None = None # Для зачеркивания старого значения
    
    # --- НОВЫЕ ФЛАГИ ДЛЯ УМНОЙ ПОДСВЕТКИ ---
    primary_changed: bool = False
    secondary_changed: bool = False
    room_changed: bool = False

@dataclass(frozen=True, slots=True)
class PosterLessonCard:
    """Карточка урока на постере (один блок времени)."""
    num: str                             
    time_start: str
    time_end: str
    status: LessonStatus
    items: tuple[PosterItem, ...]
    is_extra: bool = False

@dataclass(frozen=True, slots=True)
class PosterRequest:
    request_id: str
    date_text: str                        
    title: str                            
    lessons: tuple[PosterLessonCard, ...]
    subtitle: str | None = None           
    changes_count: int = 0                
    width: int = 1080                     

@dataclass(frozen=True, slots=True)
class RenderedPoster:
    """Результат рендера: PNG-байты и габариты постера."""

    request_id: str
    png_bytes: bytes
    width: int
    height: int