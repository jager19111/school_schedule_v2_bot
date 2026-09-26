# web/routes/school.py
#
# Экран «Школа» (Phase 3, ТЗ 29-32):
# - справочники: классы / учителя / кабинеты;
# - расписание класса/учителя/кабинета (день/неделя);
# - свободные кабинеты сейчас;
# - поиск по справочникам с группировкой результатов.
#
# Только существующие сервисные методы (верифицированы по 588700f):
# get_classes_list / get_teachers_list / get_rooms_list,
# get_daily_schedule_for_class/teacher/room,
# get_class/teacher/room_week_schedule_summary,
# get_smart_room_target_date, get_currently_free_rooms.
# Никакого SQL в routes и дублирования domain-логики.

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from services.web_sessions_service import WebSessionContext
from web.deps import require_family_allowed
from web.mappers import (
    free_rooms_to_web,
    school_day_to_web,
    search_school,
    week_summary_to_web,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_KINDS = {
    "class": {"title": "Класс", "icon": "🎓"},
    "teacher": {"title": "Преподаватель", "icon": "👨‍🏫"},
    "room": {"title": "Кабинет", "icon": "🚪"},
}


def _schedule_service(request: Request):
    return request.app.state.schedule_service


def _time_service(request: Request):
    return request.app.state.time_service


def _templates(request: Request):
    return request.app.state.templates


def _today_iso(request: Request) -> str:
    return _time_service(request).get_now_base().date().isoformat()


def _kind(kind_name: str) -> dict:
    if kind_name not in _KINDS:
        raise HTTPException(status_code=404, detail="Неизвестный раздел.")
    return _KINDS[kind_name]


async def _item_name(request: Request, kind_name: str, item_id: str) -> str:
    service = _schedule_service(request)
    if kind_name == "class":
        return await service.get_class_name(item_id)
    if kind_name == "teacher":
        return await service.get_teacher_name(item_id)
    return await service.get_room_name(item_id)


async def _nika_stale_warning(request: Request) -> str | None:
    try:
        health = await _schedule_service(request).get_nika_health_status()
    except Exception:
        return None
    if not getattr(health, "last_error", None):
        return None
    changed_at = getattr(health, "last_changed_at", None)
    formatted = _time_service(request).format_base(changed_at) if changed_at else "неизвестно"
    return (
        f"⚠️ Последнее обновление расписания: {formatted}. "
        "Расписание может быть неактуальным."
    )


def _ctx(request: Request, context: WebSessionContext, extra: dict) -> dict:
    base = {"csrf_token": context.csrf_token, "app": request.app.state.web_settings}
    base.update(extra)
    return base


# ==============================================================
# Меню «Школа» + поиск
# ==============================================================


@router.get("/school", response_class=HTMLResponse)
async def school_index(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    return _templates(request).TemplateResponse(
        request, "school/index.html", _ctx(request, context, {}),
    )


@router.get("/school/search", response_class=HTMLResponse)
async def school_search(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
    q: str = "",
):
    """Поиск (ТЗ 31): 🔎 10А / Иванов / 305; группировка по типам."""
    service = _schedule_service(request)
    results = search_school(
        query=q,
        classes=await service.get_classes_list(),
        teachers=await service.get_teachers_list(),
        rooms=await service.get_rooms_list(),
    )
    return _templates(request).TemplateResponse(
        request, "school/search.html",
        _ctx(request, context, {"results": results}),
    )


# ==============================================================
# Справочники (регистрируется ДО /school/{kind}/{item})
# ==============================================================


@router.get("/school/{kind_name}/list", response_class=HTMLResponse)
async def school_list(
    request: Request,
    kind_name: str,
    context: WebSessionContext = Depends(require_family_allowed),
):
    kind = _kind(kind_name)
    service = _schedule_service(request)

    if kind_name == "class":
        dto = await service.get_classes_list()
        items = sorted(dto.classes.items(), key=lambda kv: kv[1])
    elif kind_name == "teacher":
        dto = await service.get_teachers_list()
        items = sorted(dto.teachers.items(), key=lambda kv: kv[1])
    else:
        dto = await service.get_rooms_list()
        items = sorted(dto.rooms.items(), key=lambda kv: kv[1])

    return _templates(request).TemplateResponse(
        request, "school/list.html",
        _ctx(request, context, {
            "kind": kind_name,
            "kind_title": kind["title"],
            "kind_icon": kind["icon"],
            "items": [
                {"id": k, "name": v}
                for k, v in items
                if str(v).strip() and str(v) != "—"
            ],
        }),
    )


# ==============================================================
# Расписание: день
# ==============================================================


@router.get("/school/{kind_name}/{item_id}", response_class=HTMLResponse)
async def school_item_today(
    request: Request,
    kind_name: str,
    item_id: str,
    context: WebSessionContext = Depends(require_family_allowed),
):
    """День по умолчанию: сегодня (кабинет — smart date из сервиса)."""
    _kind(kind_name)
    if kind_name == "room":
        # Существующая smart-логика кабинета (после 19:00/вс -> след. день).
        date_iso = await _schedule_service(request).get_smart_room_target_date(item_id)
    else:
        date_iso = _today_iso(request)
    return await _render_school_day(request, context, kind_name, item_id, date_iso)


@router.get("/school/{kind_name}/{item_id}/day/{date_iso}", response_class=HTMLResponse)
async def school_item_day(
    request: Request,
    kind_name: str,
    item_id: str,
    date_iso: str,
    context: WebSessionContext = Depends(require_family_allowed),
):
    try:
        date.fromisoformat(date_iso)
    except ValueError:
        raise HTTPException(status_code=404, detail="Некорректная дата.")
    return await _render_school_day(request, context, kind_name, item_id, date_iso)


async def _render_school_day(
    request: Request,
    context: WebSessionContext,
    kind_name: str,
    item_id: str,
    date_iso: str,
):
    kind = _kind(kind_name)
    service = _schedule_service(request)
    title = await _item_name(request, kind_name, item_id)

    if kind_name == "class":
        dto = await service.get_daily_schedule_for_class(item_id, date_iso)
    elif kind_name == "teacher":
        dto = await service.get_daily_schedule_for_teacher(item_id, date_iso)
    else:
        dto = await service.get_daily_schedule_for_room(item_id, date_iso)

    view = school_day_to_web(
        dto,
        title=f"{kind['icon']} {title}",
        today_iso=_today_iso(request),
        stale_warning=await _nika_stale_warning(request),
    )
    return _templates(request).TemplateResponse(
        request, "school/day.html",
        _ctx(request, context, {
            "day": view,
            "kind": kind_name,
            "item_id": item_id,
            "item_title": title,
        }),
    )


# ==============================================================
# Расписание: неделя (сводка)
# ==============================================================


@router.get("/school/{kind_name}/{item_id}/week", response_class=HTMLResponse)
async def school_item_week(
    request: Request,
    kind_name: str,
    item_id: str,
    context: WebSessionContext = Depends(require_family_allowed),
    week: str | None = None,
):
    kind = _kind(kind_name)
    service = _schedule_service(request)
    title = await _item_name(request, kind_name, item_id)

    if week:
        try:
            week_start = date.fromisoformat(week).isoformat()
        except ValueError:
            raise HTTPException(status_code=404, detail="Некорректная неделя.")
    else:
        week_start = await service.get_smart_week_start()

    if kind_name == "class":
        summary = await service.get_class_week_schedule_summary(item_id, week_start)
    elif kind_name == "teacher":
        summary = await service.get_teacher_week_schedule_summary(
            teacher_id=item_id, week_start_iso=week_start
        )
    else:
        summary = await service.get_room_week_schedule_summary(item_id, week_start)

    view = week_summary_to_web(summary)
    prev_week = (date.fromisoformat(week_start) - timedelta(days=7)).isoformat()
    next_week = (date.fromisoformat(week_start) + timedelta(days=7)).isoformat()
    return _templates(request).TemplateResponse(
        request, "school/week.html",
        _ctx(request, context, {
            "week": view,
            "kind": kind_name,
            "item_id": item_id,
            "item_title": title,
            "kind_icon": kind["icon"],
            "prev_week": prev_week,
            "next_week": next_week,
        }),
    )


# ==============================================================
# Свободные кабинеты сейчас (ТЗ 32)
# ==============================================================


@router.get("/school/free-rooms", response_class=HTMLResponse)
async def free_rooms_now(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    service = _schedule_service(request)
    status_dto, free_rooms = await service.get_currently_free_rooms()
    view = free_rooms_to_web(status_dto, free_rooms)
    return _templates(request).TemplateResponse(
        request, "school/free_rooms.html",
        _ctx(request, context, {"free_rooms": view}),
    )
