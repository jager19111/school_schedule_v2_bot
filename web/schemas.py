# web/schemas.py
#
# Web-схемы (ТЗ 44-47): внутренние DTO бота НЕ становятся публичным
# контрактом. Flow: domain DTO -> web/mappers.py -> Web* schema ->
# Jinja2 / JSON (response_model).
#
# Даты — date-only строки YYYY-MM-DD; времена — HH:mm (ТЗ 55).

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ==============================================================
# Schedule presentation contract
# ==============================================================


class LessonViewMode(str, Enum):
    STUDENT = "student"
    CLASS = "class"
    TEACHER = "teacher"
    ROOM = "room"


class LessonKind(str, Enum):
    REGULAR = "regular"
    EXTRA = "extra"
    WINDOW = "window"
    METHODOLOGICAL = "methodological"


class LessonStatus(str, Enum):
    NORMAL = "normal"
    CHANGED = "changed"
    ADDED = "added"
    CANCELLED = "cancelled"


class WebStudent(BaseModel):
    """Профиль для переключателя расписания."""

    student_id: Optional[int]
    name: str
    is_current: bool = False


class WebChangedValue(BaseModel):
    """Значение поля урока и факт его изменения относительно original_*."""

    value: Optional[str] = None
    changed: bool = False


class WebRoomBadge(BaseModel):
    """Кабинет конкретной entry; не является свойством всей карточки."""

    value: str
    changed: bool = False


class WebLessonEntry(BaseModel):
    """Одна смысловая часть временного слота расписания."""

    subject: Optional[WebChangedValue] = None
    teacher: Optional[WebChangedValue] = None
    group: Optional[WebChangedValue] = None
    show_group: bool = False
    class_name: Optional[WebChangedValue] = None
    room: Optional[WebRoomBadge] = None


class WebChange(BaseModel):
    """Одно field-level изменение существующего LessonDTO."""

    field: Literal["subject", "teacher", "group", "class", "room"]
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    changed_at: Optional[str] = None


class WebLesson(BaseModel):
    """Полностью подготовленная mapper-ом presentation model урока."""

    key: str
    # Canonical absolute school slot:
    # 7 means seventh physical lesson of the day.
    number: Optional[int] = None

    # UI label:
    # child/parent second shift can be "1";
    # teacher/room remains "7".
    display_number: Optional[str] = None
    start_time: str
    end_time: str
    view_mode: LessonViewMode
    kind: LessonKind
    status: LessonStatus
    is_current: bool = False
    entries: List[WebLessonEntry] = Field(default_factory=list)
    shared_subject: bool = False
    shared_room: Optional[WebRoomBadge] = None
    # Context-aware label for LessonKind.WINDOW.
    # Teacher: «Свободное время».
    # Room: «Кабинет свободен».
    window_label: Optional[str] = None

    # Inline details доступны только для LessonStatus.CHANGED.
    # Cancelled и added lessons намеренно остаются non-interactive.
    has_inline_changes: bool = False
    change_details: List[WebChange] = Field(default_factory=list)

    # Пока не используется в inline-flow, но остаётся как future/fallback
    # contract для отдельной страницы или полного history view.
    history_url: Optional[str] = None

    aria_label: str
    
class WebChangeItem(BaseModel):
    """Текущая карточка изменённого урока и подготовленная история полей."""

    lesson: WebLesson
    changes: List[WebChange] = Field(default_factory=list)


class WebExtraClass(BaseModel):
    """
    Типизированное web-представление дополнительного занятия.

    `lesson` — reusable schedule presentation model для purple LessonCard.
    Extra class остаётся отдельной domain сущностью; WebLesson используется
    только как UI adapter.
    """

    id: int
    day_of_week: int
    weekday_display: str
    time_start: str
    time_end: str
    title: str
    location: Optional[str] = None
    reminder_minutes: int

    lesson: WebLesson


class WebExtraClassDay(BaseModel):
    """Типизированная группа дополнительных занятий одного дня недели."""

    day_of_week: int
    weekday_display: str
    items: List[WebExtraClass] = Field(default_factory=list)


class WebDayChanges(BaseModel):
    """Экран «Изменения» на дату."""

    date_iso: str
    date_display: str
    weekday_display: str
    class_name: str
    student_name: str
    changes: List[WebChangeItem]


class WebDaySchedule(BaseModel):
    """Расписание на день + контекст заголовка (в т.ч. school-экраны)."""

    date_iso: str
    date_display: str          # «сегодня, 26 сентября»
    weekday_display: str       # «суббота»
    class_name: str
    group_name: str
    student_name: str          # legacy display name; для school-экранов — название сущности

    # Единый контекст глобальной шапки:
    # «6а · 2 группа», «Иванов И.И.», «Кабинет 305», «8б».
    #
    # Header никогда не собирается в Jinja из raw полей и не зависит
    # от типа страницы: day.html / school/day.html используют одно поле.
    header_context: str = ""
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


class WebFreeRoomItem(BaseModel):
    id: str
    name: str


class WebFreeRooms(BaseModel):
    """Свободные кабинеты сейчас (ТЗ 32, FreeRoomsStatusDTO)."""
    status_line: str   # «14:05 (идёт 5 урок 13:15–14:00)»
    is_empty: bool
    current_time: str
    is_finished: bool
    is_break: bool
    target_num: Optional[int]
    slot_start: Optional[str]
    slot_end: Optional[str]
    slot_display: str
    rooms: List[WebFreeRoomItem]


# ==============================================================
# Phase 4: «Семья» (ТЗ 33-34)
# ==============================================================


class WebFamilyMember(BaseModel):
    user_id: Optional[int]
    name: str
    role: str
    role_label: str
    is_current: bool
    is_family_admin: bool


class WebStudentCard(BaseModel):
    student_id: int
    name: str
    class_name: str
    group_name: str
    is_virtual: bool      # без Telegram
    can_delete: bool      # virtual => можно удалить


class WebInviteItem(BaseModel):
    invite_id: int
    role_label: str
    short_code: str
    expires_display: str


class WebInviteResult(BaseModel):
    """Созданное приглашение: короткий код + deep link (если известен бот)."""

    role_label: str
    short_code: str
    deep_link: Optional[str] = None
    expires_display: str
    kind: str = "family"   # family | claim


class WebPermissionItem(BaseModel):
    adult_user_id: int
    adult_name: str
    can_manage: bool
    is_self: bool
