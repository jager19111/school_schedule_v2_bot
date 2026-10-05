# web/routes/extra_classes.py
#
# Доп. занятия (Phase 5, ТЗ 25): list / create / edit / delete.
#
# Правила:
# - доступ actor -> student проверяет ExtraClassesWebService
#   (parent: can_manage_extra_classes/family admin; child: собственный
#   профиль + can_manage_own_extra_classes); подмена student_id -> 403;
# - SQL и владелец записи — в репозитории; конфликт-проверки и
#   валидация — в сервисе; routes — только transport;
# - все mutations — POST + CSRF (глобальный hx-headers);
# - create защищён Idempotency-Key (hidden поле формы, ТЗ 60):
#   double tap / повторная отправка — no-op.

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from web.events import ScheduleChanged
from services.extra_classes_web_service import (
    ExtraClassesUnavailableReason,
)
from services.web_sessions_service import WebSessionContext
from web.deps import require_family_allowed
from web.htmx import select_page_or_fragment_template
from web.extra_classes_helpers import (
    WEEKDAYS_RU,
    build_web_extra_class,
    extra_class_to_web,
    group_by_weekday,
)
from web.mappers import student_to_web
from web.schemas import WebExtraClass

from web.idempotency import IdempotencyStore

logger = logging.getLogger(__name__)
router = APIRouter()

# Typed selection cookie хранится в schedule.py.
#
# Примеры значений:
# - student:990027
# - teacher:T001
# - watch:42
#
# Extra classes применимы только к student target, но screen умеет
# корректно fallback-нуть на первого доступного ученика для watch target.
_SCHEDULE_TARGET_COOKIE = "web_schedule_target"

def _extra_service(request: Request):
    return request.app.state.extra_classes_web_service

def _templates(request: Request):
    return request.app.state.templates

def _idempotency(request: Request) -> IdempotencyStore:
    return request.app.state.idempotency

def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"

async def _resolve_current_extra_student_id(
    request: Request,
    context: WebSessionContext,
    explicit_student_id: Optional[int],
) -> Optional[int]:
    """
    Возвращает student_id для экрана дополнительных занятий.

    Приоритет:

    1. Явный ?student=<id>.
       Такой ID затем обязательно валидируется через ExtraClassesWebService.

    2. Текущий typed schedule target из web_schedule_target.
       Если выбран student:<id>, кружки открываются именно для него.

    3. Первый доступный student target.
       Это fallback для watch/teacher target и старых browser sessions,
       где typed cookie ещё отсутствует.

    Важно: функция только выбирает кандидат student_id. Доступ и права
    всегда проверяются ниже через ExtraClassesWebService.resolve_access().
    """
    if explicit_student_id is not None:
        return explicit_student_id

    selection_key = request.cookies.get(
        _SCHEDULE_TARGET_COOKIE,
        "",
    ).strip() or None

    resolution = await (
        request.app.state.schedule_targets_service
        .resolve_for_web_user(
            user_id=context.user_id,
            requested_selection_key=selection_key,
        )
    )

    selected_target = resolution.selected_target

    if (
        selected_target is not None
        and selected_target.student_id is not None
    ):
        return int(selected_target.student_id)

    # Teacher/watch target не может быть источником extra classes.
    # В этом случае безопасно ищем первый доступный student target.
    for target in resolution.targets:
        if target.student_id is not None:
            return int(target.student_id)

    return None

async def _render_unavailable(
    request: Request,
    context: WebSessionContext,
):
    """
    PWA-friendly page для user без применимого student target.

    Это normal 200 UI state, а не 403:
    - parent/observer без детей;
    - teacher;
    - child без student profile.

    Foreign explicit student_id сюда не попадает: он остаётся 403
    через resolve_access().
    """
    reason = await _extra_service(request).get_unavailable_reason(
        actor_user_id=context.user_id,
    )

    template = select_page_or_fragment_template(
        request,
        page_template="extra/extra.html",
        fragment_template="extra/_extra_unavailable.html",
    )

    return _templates(request).TemplateResponse(
        request,
        template,
        {
            "unavailable_reason": reason.value,
            "csrf_token": context.csrf_token,
        },
    )
    
async def _resolve_access(
    request: Request,
    context: WebSessionContext,
    student_id: Optional[int],
):
    """
    Разрешает actor → student access для extra classes.

    Если route не получил explicit ?student=<id>, student определяется
    через typed schedule target web_schedule_target.

    Никакой student_id не считается доверенным только потому, что он пришёл
    из URL или cookie: ExtraClassesWebService.resolve_access() выполняет
    окончательную server-side permission validation.
    """
    resolved_student_id = await _resolve_current_extra_student_id(
        request,
        context,
        student_id,
    )

    if resolved_student_id is None:
        return None

    access = await _extra_service(request).resolve_access(
        actor_user_id=context.user_id,
        student_id=resolved_student_id,
    )

    return access

async def _student_chips(
    request: Request,
    context: WebSessionContext,
    *,
    current_student_id: int,
):
    """
    Schedule targets -> typed WebStudent chips.

    Extra list still validates each requested student through
    ExtraClassesWebService.resolve_access(). Chips are UI only;
    they do not form a security boundary.
    """
    targets = await (
        request.app.state.schedule_targets_service
        .get_targets_for_user(
            user_id=context.user_id,
        )
    )

    return [
        student_to_web(
            target,
            current_id=current_student_id,
        )
        for target in targets
        if target.student_id is not None
    ]
    
def _require_manage(access) -> None:
    """
    UI hiding is not security.

    Every mutation route must enforce can_manage server-side,
    even when FAB/edit/delete buttons are not rendered.
    """
    if not access.can_manage:
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для изменения занятий.",
        )
        
def _form_context(
    request: Request,
    context: WebSessionContext,
    *,
    mode: str,
    item: WebExtraClass | None = None,
    error: Optional[str] = None,
    student_id: int,
) -> dict:
    """
    Shared create/edit form context.

    preview_lesson always exists:
    - edit: current persisted/submitted item;
    - invalid/conflict form: submitted values;
    - new form: safe default draft.
    """
    preview_item = item or _submitted_extra_class_to_web(
        extra_id=0,
        day_of_week=1,
        time_start="15:00",
        time_end="16:00",
        title="",
        location="",
        reminder_minutes=30,
    )

    return {
        "mode": mode,
        "item": item,
        "preview_lesson": preview_item.lesson,
        "error": error,
        "weekdays": sorted(WEEKDAYS_RU.items()),
        "idempotency_key": (
            _idempotency(request).new_key()
            if mode == "create"
            else ""
        ),
        "student_id": student_id,
        "csrf_token": context.csrf_token,
    }

def _submitted_extra_class_to_web(
    *,
    extra_id: int,
    day_of_week: int,
    time_start: str,
    time_end: str,
    title: str,
    location: str,
    reminder_minutes: int,
) -> WebExtraClass:
    """
    Submitted but not persisted form values -> complete web model.

    Используется при validation/conflict error, поэтому preview сохраняет
    actual values, которые пользователь уже ввёл в форму.
    """
    return build_web_extra_class(
        extra_id=extra_id,
        day_of_week=day_of_week,
        time_start=time_start,
        time_end=time_end,
        title=title,
        location=location,
        reminder_minutes=reminder_minutes,
    )

# ==============================================================
# Список
# ==============================================================


@router.get("/extra-classes", response_class=HTMLResponse)
async def extra_classes_list(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
    student: Optional[int] = None,
):
    """
    Список extra classes.

    Friendly empty state применяется только когда user НЕ передал
    explicit student target и у него нет student target вообще.

    Explicit ?student=... или valid cookie selection продолжает идти
    через resolve_access(): подстановка чужого student_id остаётся 403.
    """
    access = await _resolve_access(
        request,
        context,
        student,
    )

    if access is None:
        # Явный ?student=<id> является security-sensitive input.
        #
        # Если пользователь передал конкретный ID без доступа, не делаем
        # silent fallback на другого ребёнка.
        if student is not None:
            raise HTTPException(
                status_code=403,
                detail="Нет доступа к занятиям ученика.",
            )

        # Без explicit student это normal UI state:
        # teacher/watch target либо отсутствующий student profile.
        return await _render_unavailable(
            request,
            context,
        )
        
    items = await _extra_service(request).list_items(access)
    view = [
        extra_class_to_web(row)
        for row in items
    ]

    template = select_page_or_fragment_template(
        request,
        page_template="extra/extra.html",
        fragment_template="extra/_extra_content.html",
    )

    return _templates(request).TemplateResponse(
        request,
        template,
        {
            "groups": group_by_weekday(view),
            "students": await _student_chips(
                request,
                context,
                current_student_id=access.student_id,
            ),
            "student_name": access.student_name,
            "student_id": access.student_id,
            "can_manage": access.can_manage,
            "csrf_token": context.csrf_token,
            "unavailable_reason": None,
        },
    )
# ==============================================================
# Формы
# ==============================================================


@router.get("/extra-classes/new", response_class=HTMLResponse)
async def extra_classes_new(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
    student: Optional[int] = None,
):
    access = await _resolve_access(request, context, student)
    _require_manage(access)

    return _templates(request).TemplateResponse(
        request,
        "extra/_extra_form.html",
        _form_context(
            request, context, mode="create", student_id=access.student_id
        ),
    )

@router.get("/extra-classes/{extra_id}/edit", response_class=HTMLResponse)
async def extra_classes_edit(
    request: Request,
    extra_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
    student: Optional[int] = None,
):
    access = await _resolve_access(request, context, student)
    _require_manage(access)
    item = await _extra_service(request).get_item(access, extra_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Занятие не найдено.")

    return _templates(request).TemplateResponse(
        request,
        "extra/_extra_form.html",
        _form_context(
            request,
            context,
            mode="edit",
            item=extra_class_to_web(item),
            student_id=access.student_id,
        ),
    )


# ==============================================================
# Мутации
# ==============================================================


def _int_in(value: str, low: int, high: int, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if low <= result <= high else default

@router.post("/extra-classes")
async def extra_classes_create(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
    idempotency_key: str = Form(""),
    title: str = Form(...),
    day_of_week: str = Form(...),
    time_start: str = Form(...),
    time_end: str = Form(...),
    location: str = Form(""),
    reminder_minutes: str = Form("30"),
    student: Optional[int] = None,
):
    access = await _resolve_access(request, context, student)
    _require_manage(access)

    # Idempotency (ТЗ 60): повторная отправка с тем же ключом — no-op.
    if not _idempotency(request).consume(idempotency_key or ""):
        return Response(status_code=200, headers={"HX-Redirect": f"/extra-classes?student={access.student_id}"})

    result = await _extra_service(request).create(
        access,
        title=title,
        day_of_week=_int_in(day_of_week, 1, 7, 0),
        time_start=time_start,
        time_end=time_end,
        location=location,
        reminder_minutes=_int_in(reminder_minutes, 0, 180, 30),
    )

    if not result.success:
        # При ошибке возвращаем форму со статусом 200, чтобы HTMX показал её юзеру
        submitted_item = _submitted_extra_class_to_web(
            extra_id=0,
            day_of_week=_int_in(day_of_week, 1, 7, 0),
            time_start=time_start,
            time_end=time_end,
            title=title,
            location=location,
            reminder_minutes=_int_in(
                reminder_minutes,
                0,
                180,
                30,
            ),
        )

        return _templates(request).TemplateResponse(
            request,
            "extra/_extra_form.html",
            _form_context(
                request,
                context,
                mode="create",
                item=submitted_item,
                error=result.detail,
                student_id=access.student_id,
            ),
        )
    bus = getattr(request.app.state, "event_bus", None)
    if bus is not None:
        await bus.publish(ScheduleChanged(revision=bus.next_revision()))
    return Response(status_code=200, headers={"HX-Redirect": f"/extra-classes?student={access.student_id}"})

@router.post("/extra-classes/{extra_id}/edit")
async def extra_classes_update(
    request: Request,
    extra_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
    title: str = Form(...),
    day_of_week: str = Form(...),
    time_start: str = Form(...),
    time_end: str = Form(...),
    location: str = Form(""),
    reminder_minutes: str = Form("30"),
    student: Optional[int] = None,
):
    access = await _resolve_access(request, context, student)
    _require_manage(access)
    result = await _extra_service(request).update(
        access,
        extra_id,
        title=title,
        day_of_week=_int_in(day_of_week, 1, 7, 0),
        time_start=time_start,
        time_end=time_end,
        location=location,
        reminder_minutes=_int_in(reminder_minutes, 0, 180, 30),
    )

    if not result.success:
        if result.error_code == "not_found":
            raise HTTPException(status_code=404, detail=result.detail)

        submitted_item = _submitted_extra_class_to_web(
            extra_id=extra_id,
            day_of_week=_int_in(day_of_week, 1, 7, 0),
            time_start=time_start,
            time_end=time_end,
            title=title,
            location=location,
            reminder_minutes=_int_in(
                reminder_minutes,
                0,
                180,
                30,
            ),
        )

        return _templates(request).TemplateResponse(
            request,
            "extra/_extra_form.html",
            _form_context(
                request,
                context,
                mode="edit",
                item=submitted_item,
                error=result.detail,
                student_id=access.student_id,
            ),
        )

    bus = getattr(request.app.state, "event_bus", None)
    if bus is not None:
        await bus.publish(ScheduleChanged(revision=bus.next_revision()))
    return Response(status_code=200, headers={"HX-Redirect": f"/extra-classes?student={access.student_id}"})

@router.post("/extra-classes/{extra_id}/delete")
async def extra_classes_delete(
    request: Request,
    extra_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
    student: Optional[int] = None,
):
    access = await _resolve_access(request, context, student)
    _require_manage(access)
    result = await _extra_service(request).delete(access, extra_id)
    if not result.success:
        raise HTTPException(status_code=404, detail=result.detail)
    bus = getattr(request.app.state, "event_bus", None)
    if bus is not None:
        await bus.publish(ScheduleChanged(revision=bus.next_revision()))
    return Response(status_code=200, headers={"HX-Redirect": f"/extra-classes?student={access.student_id}"})