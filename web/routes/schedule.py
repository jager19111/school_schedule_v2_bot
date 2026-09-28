# web/routes/schedule.py
#
# Экраны Phase 2/2.1: Сегодня (smart-day), День, Неделя, Изменения,
# переключатель ребёнка (POST + CSRF).
#
# Actor/target (ТЗ 19): actor — из сессии; target (student_id) — из
# URL/cookie, но валидируется через ScheduleTargetsService на каждом
# запросе. Подмена student_id чужой семьи -> 403.
#
# Phase 2.1: смена target — ТОЛЬКО POST /api/v1/schedule/select/{id}
# (GET не имеет side effects); CSRF-middleware проверяет POST по
# глобальному hx-headers из base.html.

from __future__ import annotations

import logging
from datetime import date, timedelta
from urllib.parse import urlsplit

from dataclasses import replace
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from services.schedule_targets_service import (
    ScheduleTarget,
    ScheduleTargetsService,
)
from services.web_sessions_service import WebSessionContext
from web.deps import require_family_allowed
from web.mappers import (
    changes_to_web,
    day_to_web,
    student_to_web,
    week_summary_to_web,
)
from web.schemas import (
    LessonKind,
    LessonStatus,
    LessonViewMode,
    WebChangedValue,
    WebLesson,
    WebLessonEntry,
    WebRoomBadge,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_STUDENT_COOKIE = "web_student"

def _targets_service(request: Request) -> ScheduleTargetsService:
    return request.app.state.schedule_targets_service

def _schedule_service(request: Request):
    return request.app.state.schedule_service

def _time_service(request: Request):
    return request.app.state.time_service

def _templates(request: Request):
    return request.app.state.templates

def _today_iso(request: Request) -> str:
    return _time_service(request).get_now_base().date().isoformat()

def _day_navigation(
    *,
    selected_date_iso: str,
    today_iso: str,
) -> dict[str, str | bool]:
    """
    Контекст навигации для дневного расписания.

    Все ссылки рассчитываются на сервере. Шаблон и JavaScript не
    выполняют арифметику с датами и не знают правил URL-роутинга.
    """
    selected_date = date.fromisoformat(selected_date_iso)

    previous_date_iso = (
        selected_date - timedelta(days=1)
    ).isoformat()

    next_date_iso = (
        selected_date + timedelta(days=1)
    ).isoformat()

    return {
        "previous_url": (
            f"/schedule/day/{previous_date_iso}"
        ),
        "next_url": (
            f"/schedule/day/{next_date_iso}"
        ),
        "today_url": "/",
        "is_today": selected_date_iso == today_iso,
    }
    
def _safe_next_url(value: str | None) -> str:
    """
    Разрешает только internal relative redirects.

    Нельзя позволять caller-у передать:
    https://evil.example/...
    //evil.example/...
    javascript:...
    """
    if not value:
        return "/"

    parsed = urlsplit(value)

    if parsed.scheme or parsed.netloc:
        return "/"

    if not parsed.path.startswith("/"):
        return "/"

    result = parsed.path

    if parsed.query:
        result = f"{result}?{parsed.query}"

    return result

def _fixture_entry(
    *,
    subject: str | None = None,
    teacher: str | None = None,
    group: str | None = None,
    class_name: str | None = None,
    room: str | None = None,
    subject_changed: bool = False,
    teacher_changed: bool = False,
    group_changed: bool = False,
    class_changed: bool = False,
    room_changed: bool = False,
) -> WebLessonEntry:
    return WebLessonEntry(
        subject=(
            WebChangedValue(
                value=subject,
                changed=subject_changed,
            )
            if subject
            else None
        ),
        teacher=(
            WebChangedValue(
                value=teacher,
                changed=teacher_changed,
            )
            if teacher
            else None
        ),
        group=(
            WebChangedValue(
                value=group,
                changed=group_changed,
            )
            if group
            else None
        ),
        class_name=(
            WebChangedValue(
                value=class_name,
                changed=class_changed,
            )
            if class_name
            else None
        ),
        room=(
            WebRoomBadge(
                value=room,
                changed=room_changed,
            )
            if room
            else None
        ),
    )


def _fixture_lesson(
    *,
    key: str,
    number: int | None,
    start_time: str,
    end_time: str,
    view_mode: LessonViewMode,
    kind: LessonKind = LessonKind.REGULAR,
    status: LessonStatus = LessonStatus.NORMAL,
    is_current: bool = False,
    entries: list[WebLessonEntry],
    shared_subject: bool = False,
    shared_room: WebRoomBadge | None = None,
    aria_label: str,
) -> WebLesson:
    return WebLesson(
        key=key,
        number=number,
        start_time=start_time,
        end_time=end_time,
        view_mode=view_mode,
        kind=kind,
        status=status,
        is_current=is_current,
        entries=entries,
        shared_subject=shared_subject,
        shared_room=shared_room or _fixture_shared_room(entries),
        history_url=None,
        aria_label=aria_label,
    )

def _fixture_shared_room(
    entries: list[WebLessonEntry],
) -> WebRoomBadge | None:
    rooms = [
        entry.room
        for entry in entries
        if entry.room is not None
    ]

    if not rooms or len(rooms) != len(entries):
        return None

    if len({room.value for room in rooms}) != 1:
        return None

    return WebRoomBadge(
        value=rooms[0].value,
        changed=any(room.changed for room in rooms),
    )

def _schedule_component_fixtures() -> list[WebLesson]:
    return [
        _fixture_lesson(
            key="fixture-normal-student",
            number=1,
            start_time="08:15",
            end_time="09:00",
            view_mode=LessonViewMode.STUDENT,
            entries=[
                _fixture_entry(
                    subject="Биология",
                    teacher="Потапова М.В.",
                    group="Группа 2",
                    room="305",
                )
            ],
            aria_label="Урок 1. Биология. Потапова М.В. Кабинет 305.",
        ),
        _fixture_lesson(
            key="fixture-current",
            number=2,
            start_time="09:10",
            end_time="09:55",
            view_mode=LessonViewMode.STUDENT,
            is_current=True,
            entries=[
                _fixture_entry(
                    subject="Математика",
                    teacher="Иванов И.И.",
                    group="Группа 2",
                    room="214",
                )
            ],
            aria_label="Сейчас. Урок 2. Математика. Кабинет 214.",
        ),
        _fixture_lesson(
            key="fixture-shared-subject",
            number=3,
            start_time="10:15",
            end_time="11:00",
            view_mode=LessonViewMode.CLASS,
            shared_subject=True,
            entries=[
                _fixture_entry(
                    subject="Английский язык",
                    teacher="Победа А.А.",
                    group="Группа 1",
                    room="230",
                ),
                _fixture_entry(
                    subject="Английский язык",
                    teacher="Погорцева Г.К.",
                    group="Группа 2",
                    room="324",
                ),
            ],
            aria_label="Урок 3. Английский язык. Две группы.",
        ),
        _fixture_lesson(
            key="fixture-different-subjects",
            number=4,
            start_time="11:15",
            end_time="12:00",
            view_mode=LessonViewMode.CLASS,
            entries=[
                _fixture_entry(
                    subject="Ин. язык",
                    teacher="Корчмит О.О.",
                    group="Группа 1",
                    room="324а",
                ),
                _fixture_entry(
                    subject="Программирование",
                    teacher="Гурина А.А.",
                    group="Группа 2",
                    room="301",
                ),
            ],
            aria_label="Урок 4. Ин. язык и программирование.",
        ),
        _fixture_lesson(
            key="fixture-changed-subject",
            number=5,
            start_time="12:10",
            end_time="12:55",
            view_mode=LessonViewMode.STUDENT,
            status=LessonStatus.CHANGED,
            entries=[
                _fixture_entry(
                    subject="История",
                    teacher="Емалетдинов Т.А.",
                    room="232",
                    subject_changed=True,
                )
            ],
            aria_label="Изменение расписания. Предмет изменён на историю.",
        ),
        _fixture_lesson(
            key="fixture-cancelled",
            number=6,
            start_time="13:05",
            end_time="13:50",
            view_mode=LessonViewMode.STUDENT,
            status=LessonStatus.CANCELLED,
            entries=[
                _fixture_entry(
                    subject="Музыка",
                    teacher="Денисова Л.В.",
                )
            ],
            aria_label="Урок 6 отменён. Музыка.",
        ),
        _fixture_lesson(
            key="fixture-extra",
            number=None,
            start_time="17:30",
            end_time="18:30",
            view_mode=LessonViewMode.STUDENT,
            kind=LessonKind.EXTRA,
            entries=[
                _fixture_entry(
                    subject="Робототехника",
                    teacher="Кузнецов А.В.",
                    room="актовый зал",
                )
            ],
            aria_label="Дополнительное занятие. Робототехника.",
        ),
        _fixture_lesson(
            key="fixture-teacher",
            number=7,
            start_time="14:00",
            end_time="14:40",
            view_mode=LessonViewMode.TEACHER,
            shared_subject=True,
            entries=[
                _fixture_entry(
                    subject="Математика",
                    class_name="6а",
                    group="Группа 1",
                    room="201",
                ),
                _fixture_entry(
                    subject="Математика",
                    class_name="6б",
                    group="Группа 2",
                    room="201",
                ),
                _fixture_entry(
                    subject="Математика",
                    class_name="7а",
                    group="Группа 1",
                    room="201",
                ),
            ],
            aria_label="Урок 7. Математика. 6а, 6б, 7а. Кабинет 201.",
        ),
        _fixture_lesson(
            key="fixture-window",
            number=8,
            start_time="14:55",
            end_time="15:35",
            view_mode=LessonViewMode.TEACHER,
            kind=LessonKind.WINDOW,
            entries=[],
            aria_label="Урок 8. Свободное время.",
        ),
        _fixture_lesson(
            key="fixture-long-subject",
            number=9,
            start_time="15:50",
            end_time="16:30",
            view_mode=LessonViewMode.STUDENT,
            entries=[
                _fixture_entry(
                    subject="Основы естественно-научных исследований",
                    teacher="Перфилов М.В.",
                    room="207",
                )
            ],
            aria_label=(
                "Урок 9. Основы естественно-научных исследований. "
                "Кабинет 207."
            ),
        ),
        _fixture_lesson(
            key="fixture-changed-teacher",
            number=10,
            start_time="16:40",
            end_time="17:20",
            view_mode=LessonViewMode.STUDENT,
            status=LessonStatus.CHANGED,
            entries=[
                _fixture_entry(
                    subject="География",
                    teacher="Петрова Е.В.",
                    room="304",
                    teacher_changed=True,
                )
            ],
            aria_label=(
                "Изменение расписания. Преподаватель изменён. "
                "География. Петрова Е.В."
            ),
        ),
        _fixture_lesson(
            key="fixture-changed-room",
            number=11,
            start_time="17:30",
            end_time="18:10",
            view_mode=LessonViewMode.STUDENT,
            status=LessonStatus.CHANGED,
            entries=[
                _fixture_entry(
                    subject="Обществознание",
                    teacher="Сидоров В.В.",
                    room="214",
                    room_changed=True,
                )
            ],
            aria_label=(
                "Изменение расписания. Кабинет изменён на 214. "
                "Обществознание."
            ),
        ),
        _fixture_lesson(
            key="fixture-added",
            number=12,
            start_time="18:20",
            end_time="19:00",
            view_mode=LessonViewMode.STUDENT,
            status=LessonStatus.ADDED,
            entries=[
                _fixture_entry(
                    subject="Консультация по математике",
                    teacher="Иванов И.И.",
                    room="201",
                )
            ],
            aria_label=(
                "Добавленный урок 12. Консультация по математике. "
                "Кабинет 201."
            ),
        ),
        _fixture_lesson(
            key="fixture-shared-subject-three-groups",
            number=13,
            start_time="19:10",
            end_time="19:50",
            view_mode=LessonViewMode.CLASS,
            shared_subject=True,
            entries=[
                _fixture_entry(
                    subject="Английский язык",
                    teacher="Победа А.А.",
                    group="Группа 1",
                    room="230",
                ),
                _fixture_entry(
                    subject="Английский язык",
                    teacher="Погорцева Г.К.",
                    group="Группа 2",
                    room="324",
                ),
                _fixture_entry(
                    subject="Английский язык",
                    teacher="Корчмит О.О.",
                    group="Группа 3",
                    room="324а",
                ),
            ],
            aria_label=(
                "Урок 13. Английский язык. "
                "Три подгруппы в кабинетах 230, 324 и 324а."
            ),
        ),
        _fixture_lesson(
            key="fixture-different-subjects-three-groups",
            number=14,
            start_time="20:00",
            end_time="20:40",
            view_mode=LessonViewMode.CLASS,
            entries=[
                _fixture_entry(
                    subject="Ин. язык",
                    teacher="Корчмит О.О.",
                    group="Группа 1",
                    room="324а",
                ),
                _fixture_entry(
                    subject="Программирование",
                    teacher="Гурина А.А.",
                    group="Группа 2",
                    room="301",
                ),
                _fixture_entry(
                    subject="Робототехника",
                    teacher="Кузнецов А.В.",
                    group="Группа 3",
                    room="актовый зал",
                ),
            ],
            aria_label=(
                "Урок 14. Три разных предмета для трёх подгрупп."
            ),
        ),
        _fixture_lesson(
            key="fixture-room-mode",
            number=15,
            start_time="20:50",
            end_time="21:30",
            view_mode=LessonViewMode.ROOM,
            entries=[
                _fixture_entry(
                    subject="Физика",
                    teacher="Кузнецов С.П.",
                    class_name="8б",
                    group="Группа 1",
                    room="лаборатория",
                )
            ],
            aria_label=(
                "Урок 15. Физика. 8б, группа 1. "
                "Кабинет лаборатория."
            ),
        ),
        _fixture_lesson(
            key="fixture-methodological",
            number=16,
            start_time="21:40",
            end_time="22:20",
            view_mode=LessonViewMode.TEACHER,
            kind=LessonKind.METHODOLOGICAL,
            entries=[],
            aria_label="Урок 16. Методический час.",
        ),
    ]
    
async def _nika_stale_warning(request: Request) -> str | None:
    """
    NIKA outage (ТЗ 53): источник с ошибкой при живом кеше.

    Только отображение существующего NikaSourceHealthDTO — без
    дополнительной NIKA-логики. «Последнее обновление» —
    last_changed_at в школьной таймзоне (TimeService.format_base).
    """
    try:
        health = await _schedule_service(request).schedule_repo.get_nika_health_status()
    except Exception as exc:
        logger.warning("get_nika_health_status failed: %s", exc)
        return None

    if not health.last_error:
        return None

    formatted = (
        _time_service(request).format_base(health.last_changed_at)
        if health.last_changed_at
        else "неизвестно"
    )

    return (
        f"⚠️ Последнее обновление расписания: {formatted}. "
        "Расписание может быть неактуальным."
    )

async def _resolve_target(
    request: Request,
    context: WebSessionContext,
) -> tuple[list, ScheduleTarget]:
    targets = await _targets_service(request).get_targets_for_user(
        user_id=context.user_id
    )
    if not targets:
        raise HTTPException(
            status_code=403,
            detail="Нет доступных профилей.",
        )

    raw = request.cookies.get(_STUDENT_COOKIE, "")
    try:
        requested = int(raw) if raw else None
    except ValueError:
        requested = None

    target = _targets_service(request).find_target(
        targets,
        requested,
    )
    if target is None:
        target = targets[0]

    if target.teacher_id:
        try:
            teacher_name = await _schedule_service(
                request
            ).get_teacher_name(target.teacher_id)
        except Exception as exc:
            logger.warning(
                "get_teacher_name failed for %s: %s",
                target.teacher_id,
                exc,
            )
            teacher_name = None

        target = replace(
            target,
            name=(
                str(teacher_name).strip()
                if teacher_name
                else "Преподаватель"
            ),
        )

    return targets, target

@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    targets, target = await _resolve_target(request, context)
    schedule_service = _schedule_service(request)

    # Роутинг: Учитель или Ученик
    if target.teacher_id:
        dto = await schedule_service.get_smart_day_schedule_for_teacher(
            teacher_id=target.teacher_id,
        )
    else:
        dto = await schedule_service.get_smart_day_schedule_for_student(
            class_id=target.class_id,
            group_id=target.group_id,
            student_id=target.student_id,
        )
        
    today_iso = _today_iso(request)

    view = day_to_web(
        dto,
        target=target,
        today_iso=today_iso,
        is_smart_today=True,
        stale_warning=await _nika_stale_warning(request),
    )

    day_navigation = _day_navigation(
        selected_date_iso=view.date_iso,
        today_iso=today_iso,
    )
    template_name = (
        "schedule/_day_content.html"
        if request.headers.get("HX-Request") == "true"
        else "schedule/day.html"
    )

    return _templates(request).TemplateResponse(
        request,
        template_name,
        _ctx(
            request,
            context,
            {
                "day": view,
                "day_navigation": day_navigation,
                "students": [
                    student_to_web(
                        target_item,
                        current_id=target.student_id,
                    )
                    for target_item in targets
                ],
                "selection_redirect": "/",
            },
        ),
    )

# ==============================================================
# Dev showcase: reusable schedule components
# ==============================================================


@router.get("/dev/schedule-components", response_class=HTMLResponse)
async def schedule_components_showcase(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    return _templates(request).TemplateResponse(
        request,
        "dev/schedule_components.html",
        _ctx(
            request,
            context,
            {
                "lessons": _schedule_component_fixtures(),
            },
        ),
    )
    
# ==============================================================
# День (полная страница и HTMX-fragment)
# ==============================================================


@router.get("/schedule/day/{date_iso}", response_class=HTMLResponse)
async def day_page(
    request: Request,
    date_iso: str,
    context: WebSessionContext = Depends(require_family_allowed),
):
    try:
        date.fromisoformat(date_iso)
    except ValueError:
        raise HTTPException(status_code=404, detail="Некорректная дата.")

    targets, target = await _resolve_target(request, context)
    
    # Роутинг: Учитель или Ученик
    if target.teacher_id:
        dto = await _schedule_service(request).get_daily_schedule_for_teacher(
            teacher_id=target.teacher_id,
            date_iso=date_iso,
        )
    else:
        dto = await _schedule_service(request).get_daily_schedule_for_student(
            class_id=target.class_id,
            group_id=target.group_id,
            date_iso=date_iso,
            student_id=target.student_id,
        )
        
    today_iso = _today_iso(request)

    view = day_to_web(
        dto,
        target=target,
        today_iso=today_iso,
        stale_warning=await _nika_stale_warning(request),
    )

    day_navigation = _day_navigation(
        selected_date_iso=view.date_iso,
        today_iso=today_iso,
    )
    template_name = (
        "schedule/_day_content.html"
        if request.headers.get("HX-Request") == "true"
        else "schedule/day.html"
    )

    return _templates(request).TemplateResponse(
        request,
        template_name,
        _ctx(
            request,
            context,
            {
                "day": view,
                "day_navigation": day_navigation,
                "students": [
                    student_to_web(
                        target_item,
                        current_id=target.student_id,
                    )
                    for target_item in targets
                ],
                "selection_redirect": (
                    f"/schedule/day/{date_iso}"
                ),
            },
        ),
    )


# ==============================================================
# Изменения (ТЗ 24: замена/отмена/добавление; Phase 2.1)
# ==============================================================


@router.get("/schedule/changes/{date_iso}", response_class=HTMLResponse)
async def day_changes(
    request: Request,
    date_iso: str,
    context: WebSessionContext = Depends(require_family_allowed),
):
    try:
        date.fromisoformat(date_iso)
    except ValueError:
        raise HTTPException(status_code=404, detail="Некорректная дата.")

    targets, target = await _resolve_target(request, context)
    
    # Роутинг: Учитель или Ученик
    if target.teacher_id:
        dto = await _schedule_service(request).get_day_changes_detail(
            teacher_id=target.teacher_id,
            date_iso=date_iso,
            origin="teacher",
        )
    else:
        dto = await _schedule_service(request).get_day_changes_detail(
            class_id=target.class_id,
            date_iso=date_iso,
            origin="class",
        )

    view = changes_to_web(dto, target=target)
    return _templates(request).TemplateResponse(
        request,
        "schedule/_changes_content.html",
        _ctx(request, context, {"changes": view}),
    )

# ==============================================================
# Неделя (сводка + переходы на дни)
# ==============================================================


@router.get("/schedule/week", response_class=HTMLResponse)
async def week_page(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
    week: str | None = None,
):
    targets, target = await _resolve_target(request, context)
    schedule_service = _schedule_service(request)

    if week:
        try:
            week_start = date.fromisoformat(week).isoformat()
        except ValueError:
            raise HTTPException(status_code=404, detail="Некорректная неделя.")
    else:
        week_start = await schedule_service.get_smart_week_start()

    # Роутинг: Учитель или Ученик
    if target.teacher_id:
        summary = await schedule_service.get_teacher_week_schedule_summary(
            teacher_id=target.teacher_id,
            week_start_iso=week_start,
        )
    else:
        summary = await schedule_service.get_week_schedule_summary(
            class_id=target.class_id,
            group_id=target.group_id,
            week_start_iso=week_start,
            student_id=target.student_id,
        )
        
    view = week_summary_to_web(summary)
    prev_week = (date.fromisoformat(week_start) - timedelta(days=7)).isoformat()
    next_week = (date.fromisoformat(week_start) + timedelta(days=7)).isoformat()
    return _templates(request).TemplateResponse(
        request,
        "schedule/week.html",
        _ctx(
            request,
            context,
            {
                "week": view,
                "students": [
                    student_to_web(
                        target_item,
                        current_id=target.student_id,
                    )
                    for target_item in targets
                ],
                "prev_week": prev_week,
                "next_week": next_week,
                "selection_redirect": (
                    f"/schedule/week?week={week_start}"
                ),
            },
        ),
    )


# ==============================================================
# Переключатель ребёнка (ТЗ 28): POST + CSRF, меняет target, не identity
# ==============================================================


@router.post("/api/v1/schedule/select/{student_id}")
async def select_student(
    request: Request,
    student_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
    next_url: str | None = None,
):
    """
    Смена schedule target.

    POST-only:
    - access actor -> selected student validated server-side;
    - CSRF is handled by global hx-headers / middleware;
    - redirect stays strictly internal and preserves current page context.
    """
    targets = await _targets_service(request).get_targets_for_user(
        user_id=context.user_id
    )
    target = _targets_service(request).find_target(
        targets,
        student_id,
    )

    if target is None:
        raise HTTPException(
            status_code=403,
            detail="Профиль недоступен.",
        )

    redirect_url = _safe_next_url(next_url)

    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = redirect_url
    else:
        response = Response(
            status_code=303,
            headers={"Location": redirect_url},
        )

    response.set_cookie(
        _STUDENT_COOKIE,
        str(student_id),
        max_age=90 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=request.app.state.web_settings.cookie_secure,
        path="/",
    )

    return response

def _ctx(request: Request, context: WebSessionContext, extra: dict) -> dict:
    """Общий контекст шаблонов: CSRF для hx-headers."""
    base = {
        "csrf_token": context.csrf_token,
        "app": request.app.state.web_settings,
    }
    base.update(extra)
    return base