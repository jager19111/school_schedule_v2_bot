# web/mappers.py
#
# Mapping domain DTO -> Web* схемы (ТЗ 44).
# Routes не собирают web-представления из DTO сами — только через mappers.

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

from core.models.dto import DayChangesDetailDTO, DayScheduleDTO, WeekSummaryDTO
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


def _g(obj, name: str, default=""):
    value = getattr(obj, name, default)
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
    d = _parse(dto.date_iso)
    prefix = "сегодня, " if dto.date_iso == today_iso else ""
    return WebDaySchedule(
        date_iso=dto.date_iso,
        date_display=f"{prefix}{d.day} {_MONTHS_GEN[d.month - 1]}",
        weekday_display=_WEEKDAYS_FULL[d.weekday()],
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


def prev_next_dates(date_iso: str) -> tuple[str, str]:
    d = _parse(date_iso)
    prev = date.fromordinal(d.toordinal() - 1).isoformat()
    nxt = date.fromordinal(d.toordinal() + 1).isoformat()
    return prev, nxt


# Phase 3: «Школа»


def school_items_to_web(items: Dict[str, str] | Iterable) -> list[WebSchoolItem]:
    if hasattr(items, "items"):
        pairs = list(items.items())
    else:
        pairs = [(getattr(i, "id", ""), getattr(i, "name", "")) for i in items]
    result = [
        WebSchoolItem(id=str(k), name=str(v))
        for k, v in pairs
        if str(v).strip() and str(v) != "—"
    ]
    result.sort(key=lambda item: item.name)
    return result


def search_school(
    *,
    query: str,
    classes: Dict[str, str],
    teachers: Dict[str, str],
    rooms: Dict[str, str],
    limit: int = 20,
) -> WebSearchResults:
    """
    Поиск по справочникам школы (ТЗ 31).

    Фильтрация по подстроке — presentation-уровень, как и в bot/handlers/search.py
    (там список тоже фильтруется/рендерится в хендлере). SQL и domain-логика
    не дублируются: источники — существующие get_*_list DTO.
    """
    q = query.strip().lower()
    if not q:
        return WebSearchResults(query=query, classes=[], teachers=[], rooms=[])

    def match(items: Dict[str, str]) -> list[WebSchoolItem]:
        found = [
            WebSchoolItem(id=str(k), name=str(v))
            for k, v in items.items()
            if q in str(v).lower() or q in str(k).lower()
        ]
        found.sort(key=lambda item: item.name)
        return found[:limit]

    return WebSearchResults(
        query=query,
        classes=match(classes),
        teachers=match(teachers),
        rooms=match(rooms),
    )


def free_rooms_to_web(status, rooms: Dict[str, str]) -> WebFreeRooms:
    is_finished = bool(getattr(status, "is_finished", False))
    is_break = bool(getattr(status, "is_break", False))
    target_num = getattr(status, "target_num", None)
    start = getattr(status, "start_time", None)
    end = getattr(status, "end_time", None)
    current_time = str(getattr(status, "current_time_str", "") or "")

    if is_finished:
        slot_display = "уроки завершены"
    elif target_num is None:
        slot_display = "школа закрыта"
    else:
        state = "перемена" if is_break else f"идет {target_num} урок"
        slot_display = f"{state} {start}–{end}" if start and end else state

    status_line = f"{current_time} ({slot_display})" if current_time else slot_display
    
    room_items = [
        WebFreeRoomItem(id=str(k), name=str(v))
        for k, v in sorted(rooms.items(), key=lambda kv: kv[1])
    ]

    return WebFreeRooms(
        status_line=status_line,
        is_empty=len(room_items) == 0,
        current_time=current_time,
        is_finished=is_finished,
        is_break=is_break,
        target_num=target_num,
        slot_start=start,
        slot_end=end,
        slot_display=slot_display,
        rooms=[
            WebFreeRoomItem(id=str(k), name=str(v))
            for k, v in sorted(rooms.items(), key=lambda kv: kv[1])
        ],
    )


# ==============================================================
# Phase 4: «Семья» (ТЗ 33-34)
# ==============================================================


def _format_dt(value) -> str:
    """aware-UTC datetime / ISO-строка -> 'дд.мм чч:мм' (без timezone-логики)."""
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return value
    return value.strftime("%d.%m %H:%M")


def family_members_to_web(members, *, current_user_id: int) -> List[WebFamilyMember]:
    result = []
    for m in (members or []):
        user_id = _g(m, "user_id", None)
        user_id = int(user_id) if user_id is not None else None
        result.append(
            WebFamilyMember(
                user_id=user_id,
                name=str(_g(m, "name") or f"Участник {user_id}"),
                role=str(_g(m, "role") or ""),
                role_label=ROLE_LABELS.get(str(_g(m, "role")), str(_g(m, "role") or "—")),
                is_current=user_id == current_user_id,
                is_family_admin=bool(getattr(m, "is_family_admin", False)),
            )
        )
    return result


def student_cards_to_web(
    students,
    *,
    classes: Dict[str, str],
    groups: Dict[str, str],
) -> List[WebStudentCard]:
    result = []
    for s in (students or []):
        class_id = str(_g(s, "class_id") or "")
        group_id = str(_g(s, "group_id") or "ALL")
        is_virtual = _g(s, "telegram_user_id", None) is None
        result.append(
            WebStudentCard(
                student_id=int(_g(s, "id", 0)),
                name=str(_g(s, "name") or f"Ученик {_g(s, 'id')}"),
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


def invites_to_web(invites) -> List[WebInviteItem]:
    result = []
    for invite in (invites or []):
        result.append(
            WebInviteItem(
                invite_id=int(_g(invite, "id", 0)),
                role_label=INVITE_ROLE_LABELS.get(
                    str(_g(invite, "intended_role")), "Участник"
                ),
                short_code=str(_g(invite, "short_code") or "—"),
                expires_display=_format_dt(_g(invite, "expires_at", None)),
            )
        )
    return result


def invite_result_to_web(
    invite,
    *,
    kind: str = "family",
    bot_username: Optional[str] = None,
) -> WebInviteResult:
    token = _g(invite, "token", "")
    deep_link = None
    if bot_username and token:
        prefix = "claim" if kind == "claim" else "join"
        deep_link = f"https://t.me/{bot_username}?start={prefix}_{token}"
    return WebInviteResult(
        role_label=(
            str(_g(invite, "student_name") or "Ученик")
            if kind == "claim"
            else INVITE_ROLE_LABELS.get(str(_g(invite, "intended_role")), "Участник")
        ),
        short_code=str(_g(invite, "short_code") or "—"),
        deep_link=deep_link,
        expires_display=_format_dt(_g(invite, "expires_at", None)),
        kind=kind,
    )


def permissions_to_web(
    permissions,
    *,
    admin_user_id: int,
    members_by_id: Dict[int, str],
) -> List[WebPermissionItem]:
    result = []
    for p in (permissions or []):
        adult_user_id = int(_g(p, "adult_user_id", 0))
        result.append(
            WebPermissionItem(
                adult_user_id=adult_user_id,
                adult_name=members_by_id.get(adult_user_id, f"Участник {adult_user_id}"),
                can_manage=bool(getattr(p, "can_manage_extra_classes", False)),
                is_self=adult_user_id == admin_user_id,
            )
        )
    return result
