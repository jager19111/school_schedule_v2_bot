# web/schemas.py
#
# Web-схемы (ТЗ 44-47): внутренние DTO бота НЕ становятся публичным
# контрактом. Flow: domain DTO -> web/mappers.py -> Web* schema ->
# Jinja2 / JSON (response_model).
#
# Даты — date-only строки YYYY-MM-DD; времена — HH:mm (ТЗ 55).

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


# ==============================================================
# Schedule (Phase 2)
# ==============================================================


class WebStudent(BaseModel):
    """Student profile для переключателя (без внутренних ID лишних сущностей)."""

    student_id: Optional[int]
    name: str
    is_current: bool = False


class WebLesson(BaseModel):
    """Карточка урока (ТЗ 24): минимум полей, без служебных DTO-полей."""

    display_num: str
    start_time: str
    end_time: str
    subject_name: str
    teacher_name: str
    room_name: str
    class_name: str
    group_name: str
    status: str  # normal | exchange | cancelled | extra | methodological
    is_extra: bool = False
    is_cancelled: bool = False
    is_exchange: bool = False


class WebChange(BaseModel):
    """Изменённый/отменённый урок с полями «было» (ТЗ 24, Phase 2.1)."""

    display_num: str
    start_time: str
    end_time: str
    subject_name: str
    teacher_name: str
    room_name: str
    group_name: str
    original_subject_name: str
    original_teacher_name: str
    original_room_name: str
    is_cancelled: bool
    is_exchange: bool
    is_added: bool  # урока не было вовсе (пустое original_subject_name)


class WebDayChanges(BaseModel):
    """Экран «Изменения» на дату."""

    date_iso: str
    date_display: str
    weekday_display: str
    class_name: str
    student_name: str
    changes: List[WebChange]


class WebDaySchedule(BaseModel):
    """Расписание на день + контекст заголовка (в т.ч. school-экраны)."""

    date_iso: str
    date_display: str          # «сегодня, 26 сентября»
    weekday_display: str       # «суббота»
    class_name: str
    group_name: str
    student_name: str          # для school-экранов — название сущности
    lessons: List[WebLesson]
    has_permutation: bool = False
    exchange_count: int = 0
    is_smart_today: bool = False
    stale_warning: Optional[str] = None  # «Последнее обновление: …» при NIKA outage


class WebDaySummary(BaseModel):
    date_iso: str
    weekday_display: str
    date_short: str            # «26.09»
    lesson_count: int
    extra_count: int
    exchange_count: int
    has_changes: bool


class WebWeekSchedule(BaseModel):
    week_start_iso: str
    week_display: str           # «21–26 сентября»
    days: List[WebDaySummary]


# ==============================================================
# School (Phase 3, ТЗ 29-32)
# ==============================================================


class WebSchoolItem(BaseModel):
    """Элемент справочника школы (класс/учитель/кабинет)."""

    id: str
    name: str


class WebSearchResults(BaseModel):
    """Поиск (ТЗ 31): результаты, сгруппированные по типам."""

    query: str
    classes: List[WebSchoolItem]
    teachers: List[WebSchoolItem]
    rooms: List[WebSchoolItem]


class WebFreeRooms(BaseModel):
    """Свободные кабинеты сейчас (ТЗ 32, FreeRoomsStatusDTO)."""

    status_line: str   # «14:05 (идёт 5 урок 13:15–14:00)»
    is_empty: bool
    rooms: List[WebSchoolItem]
