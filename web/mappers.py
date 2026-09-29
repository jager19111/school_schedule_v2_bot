# web/mappers.py
#
# Mapping domain DTO -> Web* схемы (ТЗ 44).
# Routes не собирают web-представления из DTO сами — только через mappers.

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

from core.models.dto import (
    AdultStudentExtraClassesPermissionDTO,
    ClassListDTO,
    DayChangesDetailDTO,
    DayScheduleDTO,
    FamilyInviteDTO,
    FamilyMemberDTO,
    FreeRoomsStatusDTO,
    LessonDTO,
    RoomListDTO,
    StudentClaimInviteDTO,
    StudentProfileDTO,
    TeacherListDTO,
    WeekSummaryDTO,
)

from services.schedule_targets_service import ScheduleTarget
from web.schemas import (
    WebChange,
    WebDayChanges,
    WebDaySchedule,
    WebDaySummary,
    WebFamilyMember,
    WebFreeRoomItem,
    WebFreeRooms,
    WebInviteItem,
    WebInviteResult,
    WebLesson,
    WebPermissionItem,
    WebSchoolItem,
    WebSearchResults,
    WebStudent,
    WebStudentCard,
    WebWeekSchedule,
    LessonKind,
    LessonStatus,
    LessonViewMode,
    WebChangeItem,
    WebChangedValue,
    WebExtraClass,
    WebExtraClassDay,
    WebLessonEntry,
    WebRoomBadge,
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

ROLE_LABELS = {
    "parent": "Родитель",
    "observer": "Наблюдатель",
    "child": "Ребёнок",
    "teacher": "Учитель",
}
INVITE_ROLE_LABELS = {
    "child": "Ребёнок с Telegram",
    "parent": "Родитель",
    "observer": "Наблюдатель",
}


def _parse(date_iso: str) -> date:
    return date.fromisoformat(date_iso)


def _text_or_none(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized or normalized in {"—", "нет занятий", "Нет занятий"}:
        return None

    return normalized

_WHOLE_CLASS_GROUP_LABEL = "весь класс"


def _group_or_none(value: str | None) -> str | None:
    """
    Нормализует group display value.

    «Весь класс» — не группа для UI и никогда не должен попадать
    в строку teacher/group lesson metadata.
    """
    normalized = _text_or_none(value)

    if normalized is None:
        return None

    if normalized.casefold() == _WHOLE_CLASS_GROUP_LABEL:
        return None

    return normalized


def _group_changed_value(
    current_value: str | None,
    original_value: str | None,
) -> WebChangedValue | None:
    current = _group_or_none(current_value)
    original = _group_or_none(original_value)

    if current is None:
        return None

    return WebChangedValue(
        value=current,
        changed=original is not None and original != current,
    )


def _is_trud_or_technology(lesson: LessonDTO) -> bool:
    """
    Временное согласование с существующей логикой
    ScheduleService._filter_by_groups().

    Когда в LessonDTO появится current subject_id, этот helper следует
    перевести с display-name matching на subject-id matching.
    """
    subject_name = (lesson.subject_name or "").casefold()

    return (
        "труд" in subject_name
        or "технологи" in subject_name
    )


def _should_show_group(
    lesson: LessonDTO,
    *,
    view_mode: LessonViewMode,
    show_profile_groups: bool,
) -> bool:
    """
    Решение presentation layer.

    Personal student/parent target:
    - normal group already fixed in profile -> hidden;
    - labour/technology groups remain visible;
    - when target has ALL, UI is effectively class-wide -> groups visible.

    School views:
    - class, teacher and room views show actual groups.
    """
    if _group_or_none(lesson.group_name) is None:
        return False

    if view_mode in {
        LessonViewMode.CLASS,
        LessonViewMode.TEACHER,
        LessonViewMode.ROOM,
    }:
        return True

    if show_profile_groups:
        return True

    return _is_trud_or_technology(lesson)


def _cancelled_subject_value(
    lesson: LessonDTO,
) -> WebChangedValue | None:
    """
    NIKA/DB cancellation entry may have subject_name='ОТМЕНА'.
    User must see the actual cancelled subject from original_subject_name.
    """
    original_subject = _text_or_none(lesson.original_subject_name)

    if original_subject is not None:
        return WebChangedValue(
            value=original_subject,
            changed=False,
        )

    return _changed_value(
        lesson.subject_name,
        lesson.original_subject_name,
    )
    
def _format_time(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return "—"

    if len(normalized) == 4 and normalized[1] == ":":
        return f"0{normalized}"

    return normalized[:5]

def _display_number(lesson: LessonDTO) -> str | None:
    """
    User-facing lesson number prepared by ScheduleService.

    lesson_num remains the absolute school slot.
    display_num may be relative for a student/parent second shift.
    """
    if lesson.lesson_num is None:
        return None

    return lesson.display_num or str(lesson.lesson_num)

def _lesson_kind(lesson: LessonDTO) -> LessonKind:
    if lesson.is_extra:
        return LessonKind.EXTRA

    if lesson.is_methodological:
        return LessonKind.METHODOLOGICAL

    if lesson.is_window:
        return LessonKind.WINDOW

    return LessonKind.REGULAR


def _lesson_status(lesson: LessonDTO) -> LessonStatus:
    if lesson.is_cancelled:
        return LessonStatus.CANCELLED

    if lesson.is_exchange:
        original_subject = _text_or_none(lesson.original_subject_name)
        if original_subject is None:
            return LessonStatus.ADDED
        return LessonStatus.CHANGED

    return LessonStatus.NORMAL


def _changed_value(
    current_value: str | None,
    original_value: str | None,
) -> WebChangedValue | None:
    current = _text_or_none(current_value)
    original = _text_or_none(original_value)

    if current is None:
        return None

    return WebChangedValue(
        value=current,
        changed=original is not None and original != current,
    )


def _room_badge(lesson: LessonDTO) -> WebRoomBadge | None:
    if lesson.is_cancelled:
        return None

    room = _text_or_none(lesson.room_name)
    if room is None:
        return None

    original_room = _text_or_none(lesson.original_room_name)
    return WebRoomBadge(
        value=room,
        changed=original_room is not None and original_room != room,
    )


def lesson_entry_to_web(
    lesson: LessonDTO,
    *,
    view_mode: LessonViewMode,
    show_profile_groups: bool,
) -> WebLessonEntry:
    subject = (
        _cancelled_subject_value(lesson)
        if lesson.is_cancelled
        else _changed_value(
            lesson.subject_name,
            lesson.original_subject_name,
        )
    )

    return WebLessonEntry(
        subject=subject,
        teacher=_changed_value(
            lesson.teacher_name,
            lesson.original_teacher_name,
        ),
        group=_group_changed_value(
            lesson.group_name,
            lesson.original_group_name,
        ),
        show_group=_should_show_group(
            lesson,
            view_mode=view_mode,
            show_profile_groups=show_profile_groups,
        ),
        class_name=_changed_value(
            lesson.class_name,
            lesson.original_class_name,
        ),
        room=_room_badge(lesson),
    )


def _lesson_key(lesson: LessonDTO) -> str:
    if lesson.id:
        return f"lesson-{lesson.id}"

    number = lesson.lesson_num if lesson.lesson_num is not None else "extra"
    return (
        f"lesson-{lesson.date_iso or 'unknown'}-"
        f"{number}-{_format_time(lesson.start_time)}"
    )


def _lesson_aria_label(
    *,
    number: int | None,
    display_number: str | None,
    start_time: str,
    end_time: str,
    kind: LessonKind,
    status: LessonStatus,
    entries: list[WebLessonEntry],
    window_label: str | None = None,
) -> str:
    parts: list[str] = []

    if kind == LessonKind.EXTRA:
        parts.append("Дополнительное занятие")
    elif kind == LessonKind.WINDOW:
        parts.append(window_label or "Свободное время")
    elif display_number is not None:
        parts.append(f"Урок {display_number}")
    elif number is not None:
        parts.append(f"Урок {number}")

    parts.append(f"{start_time}–{end_time}")

    if status == LessonStatus.CANCELLED:
        parts.append("отменён")
    elif status == LessonStatus.ADDED:
        parts.append("добавлен")
    elif status == LessonStatus.CHANGED:
        parts.append("изменение расписания")

    for entry in entries:
        if entry.subject and entry.subject.value:
            parts.append(entry.subject.value)
        if entry.class_name and entry.class_name.value:
            parts.append(entry.class_name.value)
        if entry.group and entry.group.value:
            parts.append(entry.group.value)
        if entry.teacher and entry.teacher.value:
            parts.append(entry.teacher.value)
        if entry.room:
            parts.append(f"кабинет {entry.room.value}")

    return ". ".join(parts)


def _shared_subject(entries: list[WebLessonEntry]) -> bool:
    subjects = [
        entry.subject.value
        for entry in entries
        if entry.subject is not None and entry.subject.value is not None
    ]

    return len(subjects) > 1 and len(set(subjects)) == 1

def _shared_room(
    entries: list[WebLessonEntry],
) -> WebRoomBadge | None:
    rooms = [
        entry.room
        for entry in entries
        if entry.room is not None
    ]

    if len(rooms) != len(entries) or not rooms:
        return None

    room_values = {room.value for room in rooms}
    if len(room_values) != 1:
        return None

    first_room = rooms[0]
    return WebRoomBadge(
        value=first_room.value,
        changed=any(room.changed for room in rooms),
    )

def _single_lesson_to_web(
    lesson: LessonDTO,
    *,
    view_mode: LessonViewMode,
    is_current: bool = False,
    show_profile_groups: bool = False,
) -> WebLesson:
    entry = lesson_entry_to_web(
        lesson,
        view_mode=view_mode,
        show_profile_groups=show_profile_groups,
    )
    kind = _lesson_kind(lesson)
    status = _lesson_status(lesson)
    start_time = _format_time(lesson.start_time)
    end_time = _format_time(lesson.end_time)
    display_number = _display_number(lesson)
    change_details = _inline_change_details(
        [lesson],
        status=status,
    )
    return WebLesson(
        key=_lesson_key(lesson),
        number=lesson.lesson_num,
        display_number=display_number,
        start_time=start_time,
        end_time=end_time,
        view_mode=view_mode,
        kind=kind,
        status=status,
        is_current=is_current,
        entries=[entry],
        shared_subject=False,
        shared_room=entry.room,
        window_label=lesson.window_label,

        # Interactive только при real field-level changes.
        # Orange card without readable details не становится button.
        has_inline_changes=bool(change_details),
        change_details=change_details,

        history_url=None,
        aria_label=_lesson_aria_label(
            number=lesson.lesson_num,
            display_number=display_number,
            start_time=start_time,
            end_time=end_time,
            kind=kind,
            status=status,
            entries=[entry],
            window_label=lesson.window_label,
        ),
    )


def _slot_identity(
    lesson: LessonDTO,
    *,
    kind: LessonKind,
    status: LessonStatus,
) -> tuple[
    str | None,
    int | None,
    str,
    str,
    LessonKind,
    LessonStatus,
]:
    return (
        lesson.date_iso,
        lesson.lesson_num,
        _format_time(lesson.start_time),
        _format_time(lesson.end_time),
        kind,
        status,
    )


def _teacher_entry_identity(
    lesson: LessonDTO,
) -> tuple[str, tuple[str, ...]]:
    entry = lesson_entry_to_web(
        lesson,
        view_mode=LessonViewMode.TEACHER,
        show_profile_groups=True,
    )
    subject = (
        entry.subject.value.casefold()
        if entry.subject is not None and entry.subject.value is not None
        else ""
    )
    rooms = (
        (entry.room.value.casefold(),)
        if entry.room is not None
        else ()
    )

    return subject, tuple(sorted(rooms))


def _slot_to_web(
    lessons: list[LessonDTO],
    *,
    view_mode: LessonViewMode,
    is_current: bool,
    show_profile_groups: bool,
) -> list[WebLesson]:
    if not lessons:
        return []

    first = lessons[0]
    kind = _lesson_kind(first)
    status = _lesson_status(first)
    start_time = _format_time(first.start_time)
    end_time = _format_time(first.end_time)
    display_number = _display_number(first)
    if view_mode == LessonViewMode.TEACHER:
        partitions: dict[
            tuple[str, tuple[str, ...]],
            list[LessonDTO],
        ] = {}

        for lesson in lessons:
            partitions.setdefault(
                _teacher_entry_identity(lesson),
                [],
            ).append(lesson)

        grouped_lesson_sets = list(partitions.values())
    else:
        grouped_lesson_sets = [lessons]

    result: list[WebLesson] = []

    for lesson_set in grouped_lesson_sets:
        first_entry_lesson = lesson_set[0]

        entries = [
            lesson_entry_to_web(
                lesson,
                view_mode=view_mode,
                show_profile_groups=show_profile_groups,
            )
            for lesson in lesson_set
        ]

        change_details = _inline_change_details(
            lesson_set,
            status=status,
        )

        result.append(
            WebLesson(
                key=_lesson_key(first_entry_lesson),
                number=first_entry_lesson.lesson_num,
                display_number=display_number,
                start_time=start_time,
                end_time=end_time,
                view_mode=view_mode,
                kind=kind,
                status=status,
                is_current=is_current,
                entries=entries,
                shared_subject=_shared_subject(entries),
                shared_room=_shared_room(entries),
                window_label=first_entry_lesson.window_label,

                # Только changed card с actual readable diff является interactive.
                has_inline_changes=bool(change_details),
                change_details=change_details,

                history_url=None,
                aria_label=_lesson_aria_label(
                    number=first_entry_lesson.lesson_num,
                    display_number=display_number,
                    start_time=start_time,
                    end_time=end_time,
                    kind=kind,
                    status=status,
                    entries=entries,
                    window_label=first_entry_lesson.window_label,
                ),
            )
        )

    return result


def lessons_to_web(
    lessons: Iterable[LessonDTO],
    *,
    view_mode: LessonViewMode,
    is_current: bool = False,
    show_profile_groups: bool,
) -> list[WebLesson]:
    grouped: dict[
        tuple[
            str | None,
            int | None,
            str,
            str,
            LessonKind,
            LessonStatus,
        ],
        list[LessonDTO],
    ] = {}

    for lesson in lessons:
        kind = _lesson_kind(lesson)
        status = _lesson_status(lesson)

        grouped.setdefault(
            _slot_identity(
                lesson,
                kind=kind,
                status=status,
            ),
            [],
        ).append(lesson)

    result: list[WebLesson] = []

    for slot_lessons in grouped.values():
        result.extend(
            _slot_to_web(
                slot_lessons,
                view_mode=view_mode,
                is_current=is_current,
                show_profile_groups=show_profile_groups,
            )
        )

    return sorted(
        result,
        key=lambda lesson: (
            lesson.start_time,
            lesson.end_time,
            lesson.number if lesson.number is not None else 999,
            lesson.key,
        ),
    )


def _date_parts(date_iso: str, today_iso: str) -> tuple[str, str]:
    d = _parse(date_iso)
    prefix = "сегодня, " if date_iso == today_iso else ""
    return (
        f"{prefix}{d.day} {_MONTHS_GEN[d.month - 1]}",
        _WEEKDAYS_FULL[d.weekday()],
    )
    
def _class_schedule_header_context(
    *,
    class_name: str,
    group_name: str,
) -> str:
    """
    Контекст шапки для личного расписания ученика.

    Примеры:
    - «6а · 2 группа»
    - «6а»
    - «»
    """
    parts = [
        value.strip()
        for value in (class_name, group_name)
        if value and value.strip()
    ]

    return " · ".join(parts)


def day_to_web(
    dto: DayScheduleDTO,
    *,
    target: ScheduleTarget,
    today_iso: str,
    is_smart_today: bool = False,
    stale_warning: str | None = None,
) -> WebDaySchedule:
    view_mode = (
        LessonViewMode.TEACHER
        if dto.origin == "teacher"
        else LessonViewMode.STUDENT
    )
    show_profile_groups = (
        view_mode == LessonViewMode.STUDENT
        and target.group_id in {"", "ALL"}
    )

    lessons = lessons_to_web(
        dto.lessons,
        view_mode=view_mode,
        show_profile_groups=show_profile_groups,
    )
    d = _parse(dto.date_iso)

    class_name = dto.class_name or ""
    group_name = _group_or_none(dto.group_name) or ""

    header_context = (
        target.name.strip()
        if target.teacher_id
        else _class_schedule_header_context(
            class_name=class_name,
            group_name=group_name,
        )
    )

    return WebDaySchedule(
        date_iso=dto.date_iso,
        date_display=f"{d.day} {_MONTHS_GEN[d.month - 1]}",
        weekday_display=_WEEKDAYS_FULL[d.weekday()],
        class_name=class_name,
        group_name=group_name,
        student_name=target.name,
        header_context=header_context,
        lessons=lessons,
        has_permutation=dto.has_permutation,
        exchange_count=sum(
            1
            for lesson in lessons
            if lesson.status in {
                LessonStatus.CHANGED,
                LessonStatus.CANCELLED,
                LessonStatus.ADDED,
            }
        ),
        is_smart_today=is_smart_today,
        stale_warning=stale_warning,
    )


def school_day_to_web(
    dto: DayScheduleDTO,
    *,
    title: str,
    today_iso: str,
    view_mode: LessonViewMode,
    stale_warning: str | None = None,
) -> WebDaySchedule:
    """День school-справочника (класс/учитель/кабинет) -> WebDaySchedule."""
    lessons = lessons_to_web(
        dto.lessons,
        view_mode=view_mode,
        show_profile_groups=True,
    )
    d = _parse(dto.date_iso)

    date_display = (
        f"{d.day} {_MONTHS_GEN[d.month - 1]}"
    )

    weekday = _WEEKDAYS_FULL[d.weekday()]

    return WebDaySchedule(
        date_iso=dto.date_iso,
        date_display=date_display,
        weekday_display=weekday,
        class_name=dto.class_name or "",
        group_name="",
        student_name=title,
        header_context=title,
        lessons=lessons,
        has_permutation=dto.has_permutation,
        exchange_count=sum(
            1
            for lesson in lessons
            if lesson.status in {
                LessonStatus.CHANGED,
                LessonStatus.CANCELLED,
                LessonStatus.ADDED,
            }
        ),
        stale_warning=stale_warning,
    )


def _changes_for_lesson(lesson: LessonDTO) -> list[WebChange]:
    changes: list[WebChange] = []

    current_subject = _text_or_none(lesson.subject_name)
    original_subject = _text_or_none(lesson.original_subject_name)
    if original_subject is not None and original_subject != current_subject:
        changes.append(
            WebChange(
                field="subject",
                old_value=original_subject,
                new_value=current_subject,
            )
        )

    current_teacher = _text_or_none(lesson.teacher_name)
    original_teacher = _text_or_none(lesson.original_teacher_name)
    if original_teacher is not None and original_teacher != current_teacher:
        changes.append(
            WebChange(
                field="teacher",
                old_value=original_teacher,
                new_value=current_teacher,
            )
        )

    current_room = _text_or_none(lesson.room_name)
    original_room = _text_or_none(lesson.original_room_name)
    if original_room is not None and original_room != current_room:
        changes.append(
            WebChange(
                field="room",
                old_value=original_room,
                new_value=current_room,
            )
        )

    current_group = _text_or_none(lesson.group_name)
    original_group = _text_or_none(lesson.original_group_name)
    if original_group is not None and original_group != current_group:
        changes.append(
            WebChange(
                field="group",
                old_value=original_group,
                new_value=current_group,
            )
        )

    current_class = _text_or_none(lesson.class_name)
    original_class = _text_or_none(lesson.original_class_name)
    if original_class is not None and original_class != current_class:
        changes.append(
            WebChange(
                field="class",
                old_value=original_class,
                new_value=current_class,
            )
        )

    return changes

def _inline_change_details(
    lessons: Iterable[LessonDTO],
    *,
    status: LessonStatus,
) -> list[WebChange]:
    """
    Возвращает details только для orange changed card.

    Cancelled card уже полностью объясняется main LessonCard:
    original subject, red semantic state и strike-through.
    Added card визуально самодостаточна через green state.

    Для grouped lesson объединяет field changes всех entries и удаляет
    только точные дубликаты, сохраняя исходный порядок.
    """
    if status != LessonStatus.CHANGED:
        return []

    result: list[WebChange] = []
    seen: set[tuple[str, str | None, str | None]] = set()

    for lesson in lessons:
        for change in _changes_for_lesson(lesson):
            identity = (
                change.field,
                change.old_value,
                change.new_value,
            )

            if identity in seen:
                continue

            seen.add(identity)
            result.append(change)

    return result

def changes_to_web(
    dto: DayChangesDetailDTO,
    *,
    target: ScheduleTarget,
) -> WebDayChanges:
    view_mode = (
        LessonViewMode.TEACHER
        if dto.origin == "teacher"
        else LessonViewMode.STUDENT
    )

    show_profile_groups = (
        view_mode == LessonViewMode.STUDENT
        and target.group_id in {"", "ALL"}
    )

    change_items = [
        WebChangeItem(
            lesson=_single_lesson_to_web(
                lesson,
                view_mode=view_mode,
                show_profile_groups=show_profile_groups,
            ),
            changes=_changes_for_lesson(lesson),
        )
        for lesson in dto.lessons
    ]
    d = _parse(dto.date_iso)

    return WebDayChanges(
        date_iso=dto.date_iso,
        date_display=f"{d.day} {_MONTHS_GEN[d.month - 1]}",
        weekday_display=_WEEKDAYS_FULL[d.weekday()],
        class_name="",
        student_name=target.name,
        changes=change_items,
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


def prev_next_dates(date_iso: str) -> tuple[str, str]:
    d = _parse(date_iso)
    prev = date.fromordinal(d.toordinal() - 1).isoformat()
    nxt = date.fromordinal(d.toordinal() + 1).isoformat()
    return prev, nxt


def day_navigation_label(date_iso: str) -> str:
    """
    Подпись соседнего дня для server-rendered day navigation.

    Используется только presentation layer:
    - route кладёт значение в day_navigation;
    - Jinja рендерит data-day-label;
    - JavaScript только читает готовую строку.

    JavaScript не вычисляет и не форматирует даты.
    """
    d = _parse(date_iso)

    return (
        f"{_WEEKDAYS_FULL[d.weekday()].capitalize()}, "
        f"{d.day} {_MONTHS_GEN[d.month - 1]}"
    )


# Phase 3: «Школа»


def school_items_to_web(
    items: Dict[str, str],
) -> list[WebSchoolItem]:
    result = [
        WebSchoolItem(
            id=str(item_id),
            name=str(item_name),
        )
        for item_id, item_name in items.items()
        if str(item_name).strip() and str(item_name) != "—"
    ]

    return sorted(
        result,
        key=lambda item: item.name,
    )


def _search_school_items(
    items: Dict[str, str],
    *,
    query: str,
    limit: int,
) -> list[WebSchoolItem]:
    normalized_query = query.strip().lower()

    matches = [
        WebSchoolItem(
            id=str(item_id),
            name=str(item_name),
        )
        for item_id, item_name in items.items()
        if str(item_name).strip()
        and str(item_name) != "—"
        and (
            normalized_query in str(item_id).lower()
            or normalized_query in str(item_name).lower()
        )
    ]

    return sorted(
        matches,
        key=lambda item: item.name,
    )[:limit]


def search_school(
    *,
    query: str,
    classes: ClassListDTO,
    teachers: TeacherListDTO,
    rooms: RoomListDTO,
    limit: int = 20,
) -> WebSearchResults:
    """Поиск по строго типизированным school dictionary DTO."""

    if not query.strip():
        return WebSearchResults(
            query=query,
            classes=[],
            teachers=[],
            rooms=[],
        )

    return WebSearchResults(
        query=query,
        classes=_search_school_items(
            classes.classes,
            query=query,
            limit=limit,
        ),
        teachers=_search_school_items(
            teachers.teachers,
            query=query,
            limit=limit,
        ),
        rooms=_search_school_items(
            rooms.rooms,
            query=query,
            limit=limit,
        ),
    )

def free_rooms_to_web(
    status: FreeRoomsStatusDTO,
    rooms: Dict[str, str],
) -> WebFreeRooms:
    is_finished = status.is_finished
    is_break = status.is_break
    target_num = status.target_num
    start = status.start_time
    end = status.end_time
    current_time = status.current_time_str or ""

    if is_finished:
        slot_display = "уроки завершены"
    elif target_num is None:
        slot_display = "школа закрыта"
    else:
        state = "перемена" if is_break else f"идет {target_num} урок"
        slot_display = (
            f"{state} {start}–{end}"
            if start and end
            else state
        )

    status_line = (
        f"{current_time} ({slot_display})"
        if current_time
        else slot_display
    )

    room_items = [
        WebFreeRoomItem(
            id=str(room_id),
            name=str(room_name),
        )
        for room_id, room_name in sorted(
            rooms.items(),
            key=lambda item: item[1],
        )
    ]

    return WebFreeRooms(
        status_line=status_line,
        is_empty=not room_items,
        current_time=current_time,
        is_finished=is_finished,
        is_break=is_break,
        target_num=target_num,
        slot_start=start,
        slot_end=end,
        slot_display=slot_display,
        rooms=room_items,
    )
# ==============================================================
# Phase 4: «Семья» (ТЗ 33-34)
# ==============================================================


def _format_dt(value: datetime | str | None) -> str:
    """aware-UTC datetime / ISO-строка -> 'дд.мм чч:мм'."""

    if value is None:
        return "—"

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value

    return value.strftime("%d.%m %H:%M")


def family_members_to_web(
    members: Iterable[FamilyMemberDTO],
    *,
    current_user_id: int,
    family_admin_user_id: int | None = None,
) -> List[WebFamilyMember]:
    """FamilyMemberDTO -> WebFamilyMember без dynamic attribute lookup."""

    result: list[WebFamilyMember] = []

    for member in members:
        role = member.role or ""
        result.append(
            WebFamilyMember(
                user_id=member.user_id,
                name=member.name or f"Участник {member.user_id}",
                role=role,
                role_label=ROLE_LABELS.get(role, role or "—"),
                is_current=member.user_id == current_user_id,
                is_family_admin=member.user_id == family_admin_user_id,
            )
        )

    return result


def student_cards_to_web(
    students: Iterable[StudentProfileDTO],
    *,
    classes: Dict[str, str],
    groups: Dict[str, str],
) -> List[WebStudentCard]:
    """StudentProfileDTO -> typed cards family page."""

    result: list[WebStudentCard] = []

    for student in students:
        class_id = student.class_id or ""
        group_id = student.group_id or "ALL"
        is_virtual = student.telegram_user_id is None

        result.append(
            WebStudentCard(
                student_id=student.id,
                name=student.name or f"Ученик {student.id}",
                class_name=classes.get(class_id, class_id or "—"),
                group_name=(
                    groups.get(group_id, f"Группа {group_id}")
                    if group_id not in ("ALL", "")
                    else "Весь класс"
                ),
                is_virtual=is_virtual,
                can_delete=is_virtual,
            )
        )

    return result


def invites_to_web(invites: Iterable[FamilyInviteDTO]) -> List[WebInviteItem]:
    """FamilyInviteDTO -> typed family invite rows."""

    result: list[WebInviteItem] = []

    for invite in invites:
        role = invite.intended_role or ""
        result.append(
            WebInviteItem(
                invite_id=invite.id,
                role_label=INVITE_ROLE_LABELS.get(role, "Участник"),
                short_code=invite.short_code or "—",
                expires_display=_format_dt(invite.expires_at),
            )
        )

    return result


def invite_result_to_web(
    invite: FamilyInviteDTO | StudentClaimInviteDTO,
    *,
    kind: str = "family",
    bot_username: Optional[str] = None,
) -> WebInviteResult:
    """Invite DTO -> result shown after family/claim invite creation."""

    deep_link = None
    if bot_username and invite.token:
        prefix = "claim" if kind == "claim" else "join"
        deep_link = f"https://t.me/{bot_username}?start={prefix}_{invite.token}"

    if kind == "claim":
        if not isinstance(invite, StudentClaimInviteDTO):
            raise TypeError("StudentClaimInviteDTO required for claim invite")

        role_label = invite.student_name or "Ученик"
    else:
        if not isinstance(invite, FamilyInviteDTO):
            raise TypeError("FamilyInviteDTO required for family invite")

        role_label = INVITE_ROLE_LABELS.get(
            invite.intended_role,
            "Участник",
        )

    short_code = (
        invite.short_code or "—"
        if isinstance(invite, FamilyInviteDTO)
        else "—"
    )

    return WebInviteResult(
        role_label=role_label,
        short_code=short_code,
        deep_link=deep_link,
        expires_display=_format_dt(invite.expires_at),
        kind=kind,
    )


def permissions_to_web(
    permissions: Iterable[AdultStudentExtraClassesPermissionDTO],
    *,
    admin_user_id: int,
    members_by_id: Dict[int, str],
) -> List[WebPermissionItem]:
    """Typed adult/student permissions -> typed web rows."""

    result: list[WebPermissionItem] = []

    for permission in permissions:
        adult_user_id = permission.adult_user_id
        result.append(
            WebPermissionItem(
                adult_user_id=adult_user_id,
                adult_name=members_by_id.get(
                    adult_user_id,
                    permission.adult_name or f"Участник {adult_user_id}",
                ),
                can_manage=permission.can_manage_extra_classes,
                is_self=adult_user_id == admin_user_id,
            )
        )

    return result