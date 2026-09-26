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
    # Business date — только через TimeService (ТЗ 55.1).
    return _time_service(request).get_now_base().date().isoformat()


async def _nika_stale_warning(request: Request) -> str | None:
    """
    NIKA outage (ТЗ 53): источник с ошибкой при живом кеше.

    Только отображение существующего NikaSourceHealthDTO — без
    дополнительной NIKA-логики. «Последнее обновление» —
    last_changed_at в школьной таймзоне (TimeService.format_base).
    """
    try:
        health = await _schedule_service(request).get_nika_health_status()
    except Exception:
        logger.exception("get_nika_health_status failed")
        return None
    if not getattr(health, "last_error", None):
        return None
    changed_at = getattr(health, "last_changed_at", None)
    formatted = _time_service(request).format_base(changed_at) if changed_at else "неизвестно"
    return (
        f"⚠️ Последнее обновление расписания: {formatted}. "
        "Расписание может быть неактуальным."
    )


async def _resolve_target(
    request: Request,
    context: WebSessionContext,
) -> tuple[list, ScheduleTarget]:
    """Список целей actor'а + выбранная цель (cookie/первая)."""
    targets = await _targets_service(request).get_targets_for_user(
        user_id=context.user_id
    )
    if not targets:
        raise HTTPException(status_code=403, detail="Нет доступных профилей.")

    raw = request.cookies.get(_STUDENT_COOKIE, "")
    try:
        requested = int(raw) if raw else None
    except ValueError:
        requested = None

    target = _targets_service(request).find_target(targets, requested)
    if target is None:
        # Cookie протухла (ребёнок удалён из семьи) — fallback на первую.
        target = targets[0]
    return targets, target


# ==============================================================
# Dashboard «Сегодня»
# ==============================================================


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    targets, target = await _resolve_target(request, context)
    schedule_service = _schedule_service(request)

    # Smart-day (ТЗ 23): существующая бизнес-логика, не копия.
    dto = await schedule_service.get_smart_day_schedule_for_student(
        class_id=target.class_id,
        group_id=target.group_id,
        student_id=target.student_id,
    )
    view = day_to_web(
        dto,
        target=target,
        today_iso=_today_iso(request),
        is_smart_today=True,
        stale_warning=await _nika_stale_warning(request),
    )
    return _templates(request).TemplateResponse(
        request,
        "schedule/day.html",
        _ctx(request, context, {
            "day": view,
            "students": [student_to_web(t, current_id=target.student_id) for t in targets],
        }),
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
        date.fromisoformat(date_iso)  # date-only; некорректный формат -> 404
    except ValueError:
        raise HTTPException(status_code=404, detail="Некорректная дата.")

    targets, target = await _resolve_target(request, context)
    dto = await _schedule_service(request).get_daily_schedule_for_student(
        class_id=target.class_id,
        group_id=target.group_id,
        date_iso=date_iso,
        student_id=target.student_id,
    )
    view = day_to_web(
        dto,
        target=target,
        today_iso=_today_iso(request),
        stale_warning=await _nika_stale_warning(request),
    )
    return _templates(request).TemplateResponse(
        request,
        "schedule/day.html",
        _ctx(request, context, {
            "day": view,
            "students": [student_to_web(t, current_id=target.student_id) for t in targets],
            "fragment": request.headers.get("HX-Request") == "true",
        }),
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
        # Smart week start (ТЗ 27): воскресенье/суббота вечером -> след. неделя.
        week_start = await schedule_service.get_smart_week_start()

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
        _ctx(request, context, {
            "week": view,
            "students": [student_to_web(t, current_id=target.student_id) for t in targets],
            "prev_week": prev_week,
            "next_week": next_week,
        }),
    )


# ==============================================================
# Переключатель ребёнка (ТЗ 28): POST + CSRF, меняет target, не identity
# ==============================================================


@router.post("/api/v1/schedule/select/{student_id}")
async def select_student(
    request: Request,
    response: Response,
    student_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
):
    """
    Смена target student profile.

    POST-only (Phase 2.1: GET = no side effects). CSRF проверяется
    CSRFMiddleware по глобальному hx-headers. Доступ actor -> target
    валидируется через ScheduleTargetsService.
    """
    targets = await _targets_service(request).get_targets_for_user(
        user_id=context.user_id
    )
    target = _targets_service(request).find_target(targets, student_id)
    if target is None:
        raise HTTPException(status_code=403, detail="Профиль недоступен.")

    response.set_cookie(
        _STUDENT_COOKIE,
        str(student_id),
        max_age=90 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=request.app.state.web_settings.cookie_secure,
        path="/",
    )
    # HTMX: полная перезагрузка дашборда; не-HTMX (form) — обычный redirect.
    if request.headers.get("HX-Request") == "true":
        response.headers["HX-Redirect"] = "/"
        return {}
    return Response(status_code=303, headers={"Location": "/"})


def _ctx(request: Request, context: WebSessionContext, extra: dict) -> dict:
    """Общий контекст шаблонов: CSRF для hx-headers."""
    base = {
        "csrf_token": context.csrf_token,
        "app": request.app.state.web_settings,
    }
    base.update(extra)
    return base
