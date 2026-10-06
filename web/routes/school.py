# web/routes/school.py
#
# Экран «Школа» (Phase 3, ТЗ 29-32):
# - справочники: классы / учителя / кабинеты;
# - расписание класса/учителя/кабинета (день/неделя);
# - свободные кабинеты сейчас;
# - поиск по справочникам с группировкой результатов.
#
# Никакого SQL в routes и дублирования domain-логики.

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
)

from services.web_sessions_service import WebSessionContext
from services.watch_targets_service import WatchTargetsService
from web.deps import require_family_allowed
from web.mappers import (
    day_navigation_label,
    free_rooms_to_web,
    school_day_to_web,
    school_items_to_web,
    search_school,
    week_summary_to_web,
    class_items_to_web,
)
from web.schemas import LessonViewMode

logger = logging.getLogger(__name__)
router = APIRouter()

_KINDS = {
    "class": {"title": "", "icon": ""},
    "teacher": {"title": "Учитель", "icon": ""},
    "room": {"title": "", "icon": ""},
}


def _schedule_service(request: Request):
    return request.app.state.schedule_service

def _watch_targets_service(
    request: Request,
) -> WatchTargetsService:
    return request.app.state.watch_targets_service

def _time_service(request: Request):
    return request.app.state.time_service


def _templates(request: Request):
    return request.app.state.templates


def _today_iso(request: Request) -> str:
    return _time_service(request).get_now_base().date().isoformat()

def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"

def _is_app_shell_navigation(request: Request) -> bool:
    """
    True только для top-level HTMX navigation.

    Такие запросы target'ят #app-shell, поэтому server обязан вернуть
    full template с #app-shell, а не локальный content fragment.
    """
    return (
        _is_htmx(request)
        and request.headers.get("HX-Target") == "app-shell"
    )

def _room_origin(
    *,
    kind_name: str,
    origin: str | None,
) -> str | None:
    """
    Разрешает origin только для room detail.

    Не используем произвольный next/back URL: origin — закрытый allowlist.
    """
    if (
        kind_name == "room"
        and origin == "free-rooms"
    ):
        return "free-rooms"

    return None


def _origin_query(origin: str | None) -> str:
    """
    Query suffix для URL без существующих query parameters.
    """
    return (
        "?origin=free-rooms"
        if origin == "free-rooms"
        else ""
    )


def _week_origin_query(origin: str | None) -> str:
    """
    Query suffix для week URL, где ?week= уже существует.
    """
    return (
        "&origin=free-rooms"
        if origin == "free-rooms"
        else ""
    )


def _school_back_navigation(
    *,
    kind_name: str,
    origin: str | None,
) -> dict[str, str]:
    """
    Готовый back link для template.

    Template не вычисляет происхождение экрана и не конструирует URL.
    """
    if (
        kind_name == "room"
        and origin == "free-rooms"
    ):
        return {
            "back_url": "/school/free-rooms",
            "back_label": "К свободным кабинетам",
        }

    return {
        "back_url": f"/school/{kind_name}/list",
        "back_label": "К списку",
    }
        
def _school_day_navigation(
    *,
    kind_name: str,
    item_id: str,
    selected_date_iso: str,
    today_iso: str,
    origin: str | None,
) -> dict[str, str | bool]:
    """
    Навигация между датами school schedule.

    URL и подписи соседних дней формируются на сервере. Шаблон получает
    готовые labels, а JavaScript не работает с календарной арифметикой.
    """
    selected_date = date.fromisoformat(selected_date_iso)
    week_start_iso = (
        selected_date
        - timedelta(days=selected_date.weekday())
    ).isoformat()
    previous_date_iso = (
        selected_date - timedelta(days=1)
    ).isoformat()

    next_date_iso = (
        selected_date + timedelta(days=1)
    ).isoformat()

    root_url = f"/school/{kind_name}/{item_id}"
    origin_query = _origin_query(origin)
    week_origin_query = _week_origin_query(origin)
    return {
        "previous_url": (
            f"{root_url}/day/{previous_date_iso}"
            f"{origin_query}"
        ),
        "next_url": (
            f"{root_url}/day/{next_date_iso}"
            f"{origin_query}"
        ),
        "previous_label": day_navigation_label(
            previous_date_iso
        ),
        "next_label": day_navigation_label(
            next_date_iso
        ),
        "today_url": (
            f"{root_url}{origin_query}"
        ),
        "week_url": (
            f"{root_url}/week"
            f"?week={week_start_iso}"
            f"{week_origin_query}"
        ),
        "is_today": selected_date_iso == today_iso,
    }

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
    """
    NIKA outage (ТЗ 53): источник с ошибкой при живом кеше.
    Умная проверка: предупреждение показывается только если сайт 
    недоступен дольше 2 часов.
    """
    from datetime import datetime, timezone, timedelta

    try:
        health = await _schedule_service(request).get_nika_health_status()
    except Exception:
        return None

    # Строгое обращение к контракту NikaSourceHealthDTO
    if not health.last_error:
        return None

    # 1. Проверяем таймаут: 2 часа с момента последней УСПЕШНОЙ проверки
    if health.last_checked_at:
        try:
            last_ok = datetime.fromisoformat(health.last_checked_at)
            if last_ok.tzinfo is None:
                last_ok = last_ok.replace(tzinfo=timezone.utc)
                
            # Если сбой длится меньше 2 часов — молчим, данные ещё актуальны
            if datetime.now(timezone.utc) - last_ok < timedelta(hours=2):
                return None
        except ValueError:
            pass

    # 2. Формируем спокойный и понятный текст
    formatted = (
        _time_service(request).format_base(health.last_changed_at)
        if health.last_changed_at
        else "неизвестно"
    )

    return (
        f"⚠️ Сайт расписания временно недоступен. "
        f"Показана сохранённая копия (от {formatted})."
    )

def _ctx(request: Request, context: WebSessionContext, extra: dict) -> dict:
    base = {"csrf_token": context.csrf_token, "app": request.app.state.web_settings}
    base.update(extra)
    return base

async def _class_watch_context(
    request: Request,
    context: WebSessionContext,
    *,
    class_id: str,
    error: str | None = None,
) -> dict:
    """
    Подготавливает owner-specific whole-class star state.

    Star всегда относится только к:
    class_id=<class_id>, group_id="ALL".

    Group-specific watch targets здесь намеренно игнорируются.
    """
    whole_class_target = (
        await _watch_targets_service(
            request,
        ).get_whole_class_target(
            owner_user_id=context.user_id,
            class_id=class_id,
        )
    )

    return {
        "show_class_watch_toggle": True,
        "watch_class_id": class_id,
        "is_whole_class_watched": (
            whole_class_target is not None
        ),
        "whole_class_watch_target_id": (
            whole_class_target.id
            if whole_class_target is not None
            else None
        ),
        "class_watch_error": error,
    }


async def _render_class_watch_toggle(
    request: Request,
    context: WebSessionContext,
    *,
    class_id: str,
    error: str | None = None,
):
    """
    Возвращает только small HTMX star fragment.

    Normal browser POST получает redirect на class day page.
    """
    if not _is_htmx(request):
        return RedirectResponse(
            url=f"/school/class/{class_id}",
            status_code=303,
        )

    return _templates(request).TemplateResponse(
        request,
        "components/school/class_watch_toggle.html",
        _ctx(
            request,
            context,
            await _class_watch_context(
                request,
                context,
                class_id=class_id,
                error=error,
            ),
        ),
    )

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
        source_items = (await service.get_classes_list()).classes
    elif kind_name == "teacher":
        source_items = (await service.get_teachers_list()).teachers
    else:
        source_items = (await service.get_rooms_list()).rooms

    return _templates(request).TemplateResponse(
        request,
        "school/list.html",
        _ctx(
            request,
            context,
            {
                "kind": kind_name,
                "kind_title": kind["title"],
                "kind_icon": kind["icon"],
                "items": (
                    class_items_to_web(source_items)
                    if kind_name == "class"
                    else school_items_to_web(source_items)
                ),
            },
        ),
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
    origin: str | None = None,
):
    """День по умолчанию: сегодня (кабинет — smart date из сервиса)."""
    _kind(kind_name)
    if kind_name == "class":
        date_iso = await _schedule_service(
            request
        ).get_smart_class_target_date(class_id=item_id)

    elif kind_name == "teacher":
        date_iso = await _schedule_service(
            request
        ).get_smart_teacher_target_date(teacher_id=item_id)

    else:
        date_iso = await _schedule_service(
            request
        ).get_smart_room_target_date(room_id=item_id)
    return await _render_school_day(
        request,
        context,
        kind_name,
        item_id,
        date_iso,
        origin=origin,
    )


@router.get("/school/{kind_name}/{item_id}/day/{date_iso}", response_class=HTMLResponse)
async def school_item_day(
    request: Request,
    kind_name: str,
    item_id: str,
    date_iso: str,
    context: WebSessionContext = Depends(require_family_allowed),
    origin: str | None = None,
):
    try:
        date.fromisoformat(date_iso)
    except ValueError:
        raise HTTPException(status_code=404, detail="Некорректная дата.")
    return await _render_school_day(
        request,
        context,
        kind_name,
        item_id,
        date_iso,
        origin=origin,
    )


async def _render_school_day(
    request: Request,
    context: WebSessionContext,
    kind_name: str,
    item_id: str,
    date_iso: str,
    *,
    origin: str | None = None,
):
    kind = _kind(kind_name)
    origin = _room_origin(
        kind_name=kind_name,
        origin=origin,
    )
    service = _schedule_service(request)
    title = await _item_name(request, kind_name, item_id)

    if kind_name == "class":
        dto = await service.get_daily_schedule_for_class(item_id, date_iso)
    elif kind_name == "teacher":
        dto = await service.get_daily_schedule_for_teacher(item_id, date_iso)
    else:
        dto = await service.get_daily_schedule_for_room(item_id, date_iso)

    view_mode = {
        "class": LessonViewMode.CLASS,
        "teacher": LessonViewMode.TEACHER,
        "room": LessonViewMode.ROOM,
    }[kind_name]

    header_context = (
        f"Кабинет {title}"
        if kind_name == "room"
        else title
    )

    now_base = _time_service(request).get_now_base()
    today_iso = now_base.date().isoformat()

    view = school_day_to_web(
        dto,
        title=header_context,
        today_iso=today_iso,
        now_base=now_base,
        view_mode=view_mode,
        stale_warning=await _nika_stale_warning(request),
    )

    day_navigation = _school_day_navigation(
        kind_name=kind_name,
        item_id=item_id,
        selected_date_iso=view.date_iso,
        today_iso=today_iso,
        origin=origin,
    )

    template_name = (
        "school/day.html"
        if (
            not _is_htmx(request)
            or _is_app_shell_navigation(request)
        )
        else "school/_day_content.html"
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
                "kind": kind_name,
                "item_id": item_id,
                "item_title": title,
                "origin": origin,
                "origin_query": _origin_query(origin),
                **_school_back_navigation(
                    kind_name=kind_name,
                    origin=origin,
                ),
                **(
                    await _class_watch_context(
                        request,
                        context,
                        class_id=item_id,
                    )
                    if kind_name == "class"
                    else {
                        "show_class_watch_toggle": False,
                        "watch_class_id": None,
                        "is_whole_class_watched": False,
                        "whole_class_watch_target_id": None,
                        "class_watch_error": None,
                    }
                ),
            },
        ),
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
    origin: str | None = None,
):
    kind = _kind(kind_name)
    origin = _room_origin(
        kind_name=kind_name,
        origin=origin,
    )
    service = _schedule_service(request)
    title = await _item_name(request, kind_name, item_id)

    smart_week = await service.get_smart_week_start()
    
    if week:
        try:
            week_start = date.fromisoformat(week).isoformat()
        except ValueError:
            raise HTTPException(status_code=404, detail="Некорректная неделя.")
    else:
        week_start = smart_week

    week_day_url = (
        f"/school/{kind_name}/{item_id}"
        f"/day/{week_start}"
        f"{_origin_query(origin)}"
    )        
    is_current_week = (week_start == smart_week)

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
        _ctx(request, context, 
        {
            "week": view,
            "is_current_week": is_current_week,                            # <-- НОВОЕ
            "smart_week_url": (
                f"/school/{kind_name}/{item_id}/week"
                f"{_origin_query(origin)}"
            ),
            "week_day_url": week_day_url,
            "kind": kind_name,
            "item_id": item_id,
            "item_title": title,
            "kind_icon": kind["icon"],
            "prev_week": prev_week,
            "next_week": next_week,
            "origin": origin,
            "origin_query": _origin_query(origin),
            "week_origin_query": _week_origin_query(origin),
            **_school_back_navigation(
                kind_name=kind_name,
                origin=origin,
            ),
            **(
                await _class_watch_context(
                    request,
                    context,
                    class_id=item_id,
                )
                if kind_name == "class"
                else {
                    "show_class_watch_toggle": False,
                    "watch_class_id": None,
                    "is_whole_class_watched": False,
                    "whole_class_watch_target_id": None,
                    "class_watch_error": None,
                }
            ),
        },
      ),
    )

# ==============================================================
# Whole-class watch star
# ==============================================================


@router.post(
    "/school/class/{class_id}/watch",
    response_class=HTMLResponse,
)
async def add_whole_class_watch_target(
    request: Request,
    class_id: str,
    context: WebSessionContext = Depends(require_family_allowed),
):
    """
    Добавляет whole-class watch target.

    Target всегда создаётся с group_id="ALL".
    Class ID проверяется WatchTargetsService по current NIKA dictionaries.
    """
    schedule_service = _schedule_service(request)

    try:
        dictionaries = (
            await schedule_service.get_school_dictionaries()
        )
    except Exception as exc:
        logger.warning(
            "Не удалось получить school dictionaries "
            "для class watch add user=%s class=%s: %s",
            context.user_id,
            class_id,
            exc,
        )
        return await _render_class_watch_toggle(
            request,
            context,
            class_id=class_id,
            error=(
                "Не удалось загрузить справочник школы. "
                "Попробуйте позже."
            ),
        )

    response = (
        await _watch_targets_service(
            request,
        ).add_target_from_school_dictionaries(
            owner_user_id=context.user_id,
            class_id=class_id,
            group_id="ALL",
            dictionaries=dictionaries,
        )
    )

    if not response.success:
        errors = {
            "duplicate": (
                "Этот класс уже добавлен в отслеживание."
            ),
            "limit_reached": (
                "Достигнут лимит отслеживаемых классов: 10."
            ),
            "invalid_class": (
                "Этот класс больше не найден "
                "в расписании школы."
            ),
        }

        return await _render_class_watch_toggle(
            request,
            context,
            class_id=class_id,
            error=errors.get(
                response.error_code,
                "Не удалось добавить класс в отслеживание.",
            ),
        )

    return await _render_class_watch_toggle(
        request,
        context,
        class_id=class_id,
    )


@router.post(
    "/school/class/{class_id}/watch/delete",
    response_class=HTMLResponse,
)
async def delete_whole_class_watch_target(
    request: Request,
    class_id: str,
    context: WebSessionContext = Depends(require_family_allowed),
):
    """
    Удаляет whole-class target current user.

    target_id не принимается от client:
    service заново разрешает owner-specific class_id + ALL target.
    """
    whole_class_target = (
        await _watch_targets_service(
            request,
        ).get_whole_class_target(
            owner_user_id=context.user_id,
            class_id=class_id,
        )
    )

    if whole_class_target is None:
        return await _render_class_watch_toggle(
            request,
            context,
            class_id=class_id,
            error=(
                "Отслеживаемый класс уже удалён "
                "или недоступен."
            ),
        )

    response = await _watch_targets_service(
        request,
    ).delete_target(
        owner_user_id=context.user_id,
        target_id=whole_class_target.id,
    )

    if not response.success:
        return await _render_class_watch_toggle(
            request,
            context,
            class_id=class_id,
            error=(
                "Не удалось удалить отслеживаемый класс."
            ),
        )

    return await _render_class_watch_toggle(
        request,
        context,
        class_id=class_id,
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
    
    # ФИКС: Отдаем только фрагмент при HTMX-запросах (кнопка "Обновить" или свайп "Назад")
    template_name = (
        "school/free_rooms.html"
        if (
            not _is_htmx(request)
            or _is_app_shell_navigation(request)
        )
        else "school/_free_rooms_content.html"
    )
    
    return _templates(request).TemplateResponse(
        request, template_name,
        _ctx(request, context, {"free_rooms": view}),
    )