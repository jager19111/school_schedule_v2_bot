# web/routes/settings.py
from __future__ import annotations


from fastapi import APIRouter, Depends, Request
from web.events import SessionRevoked
from fastapi.responses import HTMLResponse


from services.web_sessions_service import WebSessionContext
from services.web_sessions_service import WebSessionsService
from web.deps import (
    get_sessions_service,
    require_family_allowed,
)
from web.mappers import web_devices_to_web

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _ctx(
    request: Request,
    context: WebSessionContext,
    extra: dict,
) -> dict:
    base = {
        "csrf_token": context.csrf_token,
        "app": request.app.state.web_settings,
    }
    base.update(extra)
    return base

async def _devices_context(
    request: Request,
    context: WebSessionContext,
    sessions: WebSessionsService,
    *,
    error: str | None = None,
) -> dict:
    devices = await sessions.list_devices(
        user_id=context.user_id,
        current_session_hash=context.session_hash,
    )

    return _ctx(
        request,
        context,
        {
            "devices": web_devices_to_web(
                devices,
                time_service=request.app.state.time_service,
            ),
            "error": error,
        },
    )

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    """
    Настройки текущего пользователя.

    P1:
    - безопасность;
    - выход с current device.

    Будущие подразделы:
    - профиль;
    - уведомления;
    - устройства;
    - выход со всех устройств.
    """
    template_name = (
        "settings/_settings_content.html"
        if request.headers.get("HX-Request") == "true"
        else "settings/settings.html"
    )

    return _templates(request).TemplateResponse(
        request,
        template_name,
        _ctx(request, context, {}),
    )
    
@router.get(
    "/settings/devices",
    response_class=HTMLResponse,
)
async def settings_devices_page(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
    sessions: WebSessionsService = Depends(get_sessions_service),
):
    """
    Экран active web sessions текущего пользователя.

    Показывает только собственные sessions пользователя.
    """
    template_name = (
        "settings/_devices_content.html"
        if request.headers.get("HX-Request") == "true"
        else "settings/devices.html"
    )

    return _templates(request).TemplateResponse(
        request,
        template_name,
        await _devices_context(
            request,
            context,
            sessions,
        ),
    )
    
@router.post(
    "/settings/devices/{session_id}/revoke",
    response_class=HTMLResponse,
)
async def revoke_other_device(
    request: Request,
    session_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
    sessions: WebSessionsService = Depends(get_sessions_service),
):
    """
    Отзывает только другой web-сеанс пользователя.

    Current device здесь не отзываем: для него существует отдельное
    действие «Выйти с этого устройства».
    """
    if session_id == context.session_id:
        return _templates(request).TemplateResponse(
            request,
            "settings/_devices_content.html",
            await _devices_context(
                request,
                context,
                sessions,
                error=(
                    "Текущий сеанс нельзя завершить из списка устройств. "
                    "Используйте кнопку «Выйти с этого устройства»."
                ),
            ),
        )

    revoked = await sessions.revoke_session_by_id(
        session_id=session_id,
        user_id=context.user_id,
    )

    if not revoked:
        return _templates(request).TemplateResponse(
            request,
            "settings/_devices_content.html",
            await _devices_context(
                request,
                context,
                sessions,
                error=(
                    "Этот веб-сеанс уже завершён или недоступен."
                ),
            ),
        )

    bus = getattr(
        request.app.state,
        "event_bus",
        None,
    )

    if bus is not None:
        await bus.publish(
            SessionRevoked(
                user_id=context.user_id,
                session_id=session_id,
            )
        )

    return _templates(request).TemplateResponse(
        request,
        "settings/_devices_content.html",
        await _devices_context(
            request,
            context,
            sessions,
        ),
    )