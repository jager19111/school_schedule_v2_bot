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

from services.web_sessions_service import WebSessionContext
from web.deps import require_family_allowed
from web.extra_classes_helpers import (
    WEEKDAYS_RU,
    extra_class_to_web,
    group_by_weekday,
)
from web.idempotency import IdempotencyStore

logger = logging.getLogger(__name__)
router = APIRouter()

_STUDENT_COOKIE = "web_student"

def _extra_service(request: Request):
    return request.app.state.extra_classes_web_service

def _templates(request: Request):
    return request.app.state.templates

def _idempotency(request: Request) -> IdempotencyStore:
    return request.app.state.idempotency

def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"

async def _resolve_access(
    request: Request,
    context: WebSessionContext,
    student_id: Optional[int],
):
    """Доступ actor -> student для доп. занятий (cookie target по умолчанию)."""
    if student_id is None:
        raw = request.cookies.get(_STUDENT_COOKIE, "")
        try:
            student_id = int(raw) if raw else None
        except ValueError:
            student_id = None
        if student_id is None:
            # Первый доступный target actor'а (модель selector).
            targets = await request.app.state.schedule_targets_service.get_targets_for_user(
                user_id=context.user_id
            )
            if not targets or targets[0].student_id is None:
                raise HTTPException(
                    status_code=403,
                    detail="Доп. занятия недоступны для этого профиля.",
                )
            student_id = targets[0].student_id

    access = await _extra_service(request).resolve_access(
        actor_user_id=context.user_id, student_id=student_id
    )
    if access is None:
        raise HTTPException(status_code=403, detail="Нет доступа к занятиям ученика.")
    return access

def _form_context(
    request: Request,
    context: WebSessionContext,
    *,
    mode: str,
    item=None,
    error: Optional[str] = None,
    student_id: int,
) -> dict:
    return {
        "mode": mode,
        "item": item,
        "error": error,
        "weekdays": sorted(WEEKDAYS_RU.items()),
        "idempotency_key": _idempotency(request).new_key() if mode == "create" else "",
        "student_id": student_id,
        "csrf_token": context.csrf_token,
    }


# ==============================================================
# Список
# ==============================================================


@router.get("/extra-classes", response_class=HTMLResponse)
async def extra_classes_list(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
    student: Optional[int] = None,
):
    access = await _resolve_access(request, context, student)
    items = await _extra_service(request).list_items(access)
    view = [extra_class_to_web(row) for row in items]
    template = (
        "extra/_extra_content.html" if _is_htmx(request) else "extra/extra.html"
    )
    return _templates(request).TemplateResponse(
        request,
        template,
        {
            "groups": group_by_weekday(view),
            "student_name": access.student_name,
            "student_id": access.student_id,
            "csrf_token": context.csrf_token,
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
    item = await _extra_service(request).get_item(access, extra_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Занятие не найдено.")
    return _templates(request).TemplateResponse(
        request,
        "extra/_extra_form.html",
        _form_context(
            request, context, mode="edit", item=item,
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
        submitted_item = {
            "title": title, "day_of_week": day_of_week,
            "time_start": time_start, "time_end": time_end,
            "location": location, "reminder_minutes": _int_in(reminder_minutes, 0, 180, 30)
        }
        return _templates(request).TemplateResponse(
            request,
            "extra/_extra_form.html",
            _form_context(
                request, context, mode="create", item=submitted_item,
                error=result.detail, student_id=access.student_id
            ),
        )

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
        
        submitted_item = {
            "id": extra_id, "title": title, "day_of_week": day_of_week,
            "time_start": time_start, "time_end": time_end,
            "location": location, "reminder_minutes": _int_in(reminder_minutes, 0, 180, 30)
        }
        return _templates(request).TemplateResponse(
            request,
            "extra/_extra_form.html",
            _form_context(
                request, context, mode="edit", item=submitted_item,
                error=result.detail, student_id=access.student_id
            ),
        )

    return Response(status_code=200, headers={"HX-Redirect": f"/extra-classes?student={access.student_id}"})

@router.post("/extra-classes/{extra_id}/delete")
async def extra_classes_delete(
    request: Request,
    extra_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
    student: Optional[int] = None,
):
    access = await _resolve_access(request, context, student)
    result = await _extra_service(request).delete(access, extra_id)
    if not result.success:
        raise HTTPException(status_code=404, detail=result.detail)
    return Response(status_code=200, headers={"HX-Redirect": f"/extra-classes?student={access.student_id}"})