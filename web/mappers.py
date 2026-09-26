# web/mappers.py
#
# Mapping domain DTO -> Web* схемы (ТЗ 44).
# Routes не собирают web-представления из DTO сами — только через mappers.
# Форматирование дат — чистая строковая логика по date-only ISO (ТЗ 55):
# без JS Date и без timezone-преобразований.

from __future__ import annotations

from datetime import date

from core.models.dto import (
    DayChangesDetailDTO,
    DayScheduleDTO,
    RoomListDTO,
    TeacherListDTO,
    WeekSummaryDTO,
)
from core.models.dto import ClassListDTO
from services.schedule_targets_service import ScheduleTarget
from web.schemas import (
    WebChange,
    WebDayChanges,
    WebDaySchedule,
    WebDaySummary,
    WebFreeRooms,
    WebLesson,
    WebSchoolItem,
    WebSearchResults,
    WebStudent,
    WebWeekSchedule,
)

_WEEKDAYS_FULL = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]
_WEEKDAYS_SHORT = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
_MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _parse(date_iso: str) -> date:
    return date.fromisoformat(date_iso)


def _lesson_status(lesson) -> str:
    if getattr(lesson, "is_cancelled", False):
        return "cancelled"
    if getattr(lesson, "is_extra", False):
        return "extra"
    if getattr(lesson, "is_exchange", False):
        return "exchange"
    if getattr(lesson, "is_methodological", False):
        return "methodological"
    return "normal"


def _g(lesson, name: str, default=""):
    value = getattr(lesson, name, default)
    return default if value is None else value


def lesson_to_web(lesson) -> WebLesson:
    """LessonDTO -> WebLesson (getattr-защита: поле DTO может отсутствовать)."""
    return WebLesson(
        display_num=str(_g(lesson, "display_num") or _g(lesson, "lesson_num") or "•"),
        start_time=str(_g(lesson, "start_time") or "—").zfill(5)[:5],
        end_time=str(_g(lesson, "end_time") or "—").zfill(5)[:5],
        subject_name=str(_g(lesson, "subject_name") or "Нет занятий"),
        teacher_name=str(_g(lesson, "teacher_name") or "—"),
        room_name=str(_g(lesson, "room_name") or "—"),
        class_name=str(_g(lesson, "class_name") or ""),
        group_name=str(_g(lesson, "group_name") or ""),
        status=_lesson_status(lesson),
        is_extra=bool(getattr(lesson, "is_extra", False)),
        is_cancelled=bool(getattr(lesson, "is_cancelled", False)),
        is_exchange=bool(getattr(lesson, "is_exchange", False)),
    )


def _date_parts(date_iso: str, today_iso: str) -> tuple[str, str]:
    d = _parse(date_iso)
    prefix = "сегодня, " if date_iso == today_iso else ""
    return (
        f"{prefix}{d.day} {_MONTHS_GEN[d.month - 1]}",
        _WEEKDAYS_FULL[d.weekday()],
    )


def day_to_web(
    dto: DayScheduleDTO,
    *,
    target: ScheduleTarget,
    today_iso: str,
    is_smart_today: bool = False,
    stale_warning: str | None = None,
) -> WebDaySchedule:
    lessons = [lesson_to_web(l) for l in (dto.lessons or [])]
    date_display, weekday = _date_parts(dto.date_iso, today_iso)
    return WebDaySchedule(
        date_iso=dto.date_iso,
        date_display=date_display,
        weekday_display=weekday,
        class_name=str(getattr(dto, "class_name", "") or ""),
        group_name=str(getattr(dto, "group_name", "") or ""),
        student_name=target.name,
        lessons=lessons,
        has_permutation=bool(getattr(dto, "has_permutation", False)),
        exchange_count=sum(1 for l in lessons if l.is_exchange or l.is_cancelled),
        is_smart_today=is_smart_today,
        stale_warning=stale_warning,
    )


def school_day_to_web(
    dto: DayScheduleDTO,
    *,
    title: str,
    today_iso: str,
    stale_warning: str | None = None,
) -> WebDaySchedule:
    """День school-справочника (класс/учитель/кабинет) -> WebDaySchedule."""
    lessons = [lesson_to_web(l) for l in (dto.lessons or [])]
    date_display, weekday = _date_parts(dto.date_iso, today_iso)
    return WebDaySchedule(
        date_iso=dto.date_iso,
        date_display=date_display,
        weekday_display=weekday,
        class_name=str(getattr(dto, "class_name", "") or ""),
        group_name="",
        student_name=title,
        lessons=lessons,
        has_permutation=bool(getattr(dto, "has_permutation", False)),
        exchange_count=sum(1 for l in lessons if l.is_exchange or l.is_cancelled),
        stale_warning=stale_warning,
    )


def changes_to_web(
    dto: DayChangesDetailDTO,
    *,
    target: ScheduleTarget,
) -> WebDayChanges:
    """DayChangesDetailDTO -> WebDayChanges («было -> стало», ТЗ 24)."""
    changes: list[WebChange] = []
    for l in (dto.lessons or []):
        original_subject = str(_g(l, "original_subject_name") or "")
        changes.append(
            WebChange(
                display_num=str(_g(l, "display_num") or _g(l, "lesson_num") or "•"),
                start_time=str(_g(l, "start_time") or "—").zfill(5)[:5],
                end_time=str(_g(l, "end_time") or "—").zfill(5)[:5],
                subject_name=str(_g(l, "subject_name") or "—"),
                teacher_name=str(_g(l, "teacher_name") or "—"),
                room_name=str(_g(l, "room_name") or "—"),
                group_name=str(_g(l, "group_name") or ""),
                original_subject_name=original_subject or "—",
                original_teacher_name=str(_g(l, "original_teacher_name") or "—"),
                original_room_name=str(_g(l, "original_room_name") or "—"),
                is_cancelled=bool(getattr(l, "is_cancelled", False)),
                is_exchange=bool(getattr(l, "is_exchange", False)),
                is_added=not original_subject or original_subject.lower() == "нет занятий",
            )
        )
    d = _parse(dto.date_iso)
    return WebDayChanges(
        date_iso=dto.date_iso,
        date_display=f"{d.day} {_MONTHS_GEN[d.month - 1]}",
        weekday_display=_WEEKDAYS_FULL[d.weekday()],
        class_name=str(getattr(dto, "class_name", "") or ""),
        student_name=target.name,
        changes=changes,
    )


def week_summary_to_web(dto: WeekSummaryDTO) -> WebWeekSchedule:
    days: list[WebDaySummary] = []
    for day in dto.days:
        d = _parse(day.date_iso)
        days.append(
            WebDaySummary(
                date_iso=day.date_iso,
                weekday_display=_WEEKDAYS_SHORT[d.weekday()],
                date_short=f"{d.day:02d}.{d.month:02d}",
                lesson_count=int(day.lesson_count),
                extra_count=int(day.extra_count),
                exchange_count=int(day.exchange_count),
                has_changes=int(day.exchange_count) > 0,
            )
        )
    first = _parse(dto.week_start_iso)
    last = _parse(days[-1].date_iso)
    if first.month == last.month:
        week_display = f"{first.day}–{last.day} {_MONTHS_GEN[last.month - 1]}"
    else:
        week_display = (
            f"{first.day} {_MONTHS_GEN[first.month - 1]} — "
            f"{last.day} {_MONTHS_GEN[last.month - 1]}"
        )
    return WebWeekSchedule(
        week_start_iso=dto.week_start_iso,
        week_display=week_display,
        days=days,
    )


def student_to_web(target: ScheduleTarget, *, current_id: int | None) -> WebStudent:
    return WebStudent(
        student_id=target.student_id,
        name=target.name,
        is_current=(
            target.student_id == current_id
            if target.student_id is not None
            else current_id is None
        ),
    )


# ==============================================================
# School (Phase 3)
# ==============================================================


def free_rooms_to_web(status, free_rooms: dict[str, str]) -> WebFreeRooms:
    """
    FreeRoomsStatusDTO + dict[room_id, room_name] -> WebFreeRooms.

    Формат статусной строки — как в bot/utils/ui_renderer.render_free_rooms_now
    (отображение, не бизнес-логика): «14:05 (идёт 5 урок 13:15–14:00)» /
    «14:05 (уроки завершены)».
    """
    if getattr(status, "is_finished", False):
        line = f"{status.current_time_str} (уроки завершены)"
    else:
        num = f"{status.target_num} " if getattr(status, "target_num", None) else ""
        state = "следующий" if getattr(status, "is_break", False) else "идёт"
        line = (
            f"{status.current_time_str} ({state} {num}урок "
            f"{status.start_time}–{status.end_time})"
        )
    rooms = [
        WebSchoolItem(id=str(r_id), name=name)
        for r_id, name in free_rooms.items()
    ]
    return WebFreeRooms(status_line=line, is_empty=not rooms, rooms=rooms)


def search_school(
    *,
    query: str,
    classes: ClassListDTO,
    teachers: TeacherListDTO,
    rooms: RoomListDTO,
) -> WebSearchResults:
    """
    Поиск по справочникам школы (ТЗ 31).

    Фильтрация по подстроке — presentation-уровень, как и в bot/handlers/search.py
    (там список тоже фильтруется/рендерится в хендлере). SQL и domain-логика
    не дублируются: источники — существующие get_*_list DTO.
    """
    q = (query or "").strip().lower()
    if len(q) < 2:
        return WebSearchResults(query=query or "", classes=[], teachers=[], rooms=[])

    def _match(items: dict) -> list[WebSchoolItem]:
        return [
            WebSchoolItem(id=str(k), name=v)
            for k, v in items.items()
            if q in str(v).lower() or q in str(k).lower()
        ]

    return WebSearchResults(
        query=query.strip(),
        classes=_match(classes.classes),
        teachers=_match(teachers.teachers),
        rooms=_match(rooms.rooms),
    )


def prev_next_dates(date_iso: str) -> tuple[str, str]:
    """Соседние даты для навигации ←/→ (date-only арифметика)."""
    d = _parse(date_iso)
    prev = date.fromordinal(d.toordinal() - 1).isoformat()
    nxt = date.fromordinal(d.toordinal() + 1).isoformat()
    return prev, nxt
