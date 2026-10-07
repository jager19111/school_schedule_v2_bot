# web/routes/telegram_app.py
#
# Telegram Mini App surface:
#   GET  /tg/app             — entry: bootstrap-экран внутри Telegram;
#   POST /tg/bootstrap       — initData -> валидация -> session(surface=telegram);
#   POST /tg/browser-handoff — одноразовый код -> external_url (только surface=telegram);
#   GET  /tg/browser/consume — consume кода -> browser session -> 303 на чистый URL.
#
# Правила:
# - /tg/bootstrap — public (как /api/v1/auth/exchange): CSRF не требуется,
#   авторизация — подписью Telegram initData;
# - /tg/browser-handoff — authenticated POST, X-CSRF-Token обязателен;
# - /tg/browser/consume — public одноразовый, Cache-Control: no-store.

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from services.browser_handoff_service import BrowserHandoffService
from services.telegram_webauth_service import TelegramWebAuthService
from services.web_sessions_service import (
    SESSION_COOKIE_NAME,
    WebSessionContext,
    WebSessionsService,
)
from web.deps import get_session_context, get_sessions_service

logger = logging.getLogger(__name__)
router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _handoff_service(request: Request) -> BrowserHandoffService:
    return request.app.state.browser_handoff_service


def _webauth_service(request: Request) -> TelegramWebAuthService:
    return request.app.state.telegram_webauth_service


class BootstrapRequest(BaseModel):
    init_data: str = Field(min_length=16, max_length=16384)


class BootstrapResponse(BaseModel):
    ok: bool = True
    redirect: str = "/"
    csrf_token: str
    surface: str = "telegram"


class BrowserHandoffResponse(BaseModel):
    external_url: str


@router.get("/tg/app", response_class=HTMLResponse)
async def tg_app_entry(request: Request) -> HTMLResponse:
    """Bootstrap-экран Mini App (session ещё нет — public)."""
    return _templates(request).TemplateResponse(
        request,
        "tg/app.html",
        {},
    )


@router.post("/tg/bootstrap", response_model=BootstrapResponse)
async def tg_bootstrap(
    payload: BootstrapRequest,
    request: Request,
    response: Response,
    webauth: TelegramWebAuthService = Depends(_webauth_service),
    sessions: WebSessionsService = Depends(get_sessions_service),
) -> BootstrapResponse:
    identity = webauth.validate_init_data(payload.init_data)
    if identity is None:
        raise HTTPException(
            status_code=401,
            detail="Не удалось подтвердить вход через Telegram. "
            "Откройте приложение заново из бота.",
        )
    # Уже есть живая telegram-сессия (повторное открытие Mini App) —
    # переиспользуем, не создаём новую строку в web_sessions.
    existing_raw = request.cookies.get(SESSION_COOKIE_NAME)
    if existing_raw:
        existing = await sessions.resolve_session(existing_raw)
        if existing is not None and existing.surface == "telegram":
            return BootstrapResponse(
                ok=True,
                redirect="/",
                csrf_token=existing.csrf_token,
                surface="telegram",
            )
            
    raw, context = await sessions.create_session(
        user_id=identity.user_id,
        user_agent=request.headers.get("user-agent"),
        surface="telegram",
    )
    settings = request.app.state.web_settings
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw,
        max_age=settings.session_cookie_max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return BootstrapResponse(
        ok=True,
        redirect="/",
        csrf_token=context.csrf_token,
        surface="telegram",
    )


@router.post("/tg/browser-handoff", response_model=BrowserHandoffResponse)
async def tg_browser_handoff(
    request: Request,
    context: WebSessionContext = Depends(get_session_context),
    handoff: BrowserHandoffService = Depends(_handoff_service),
) -> BrowserHandoffResponse:
    """Кнопка «Открыть в браузере»: только для Mini App сессии."""
    if context.surface != "telegram":
        raise HTTPException(
            status_code=403,
            detail="Переход доступен только из приложения Telegram.",
        )
    raw_code = await handoff.issue_handoff(user_id=context.user_id)
    settings = request.app.state.web_settings
    url = (
        f"{settings.public_url.rstrip('/')}"
        f"/tg/browser/consume?code={raw_code}"
    )
    return BrowserHandoffResponse(external_url=url)


@router.get("/tg/browser/consume", response_class=HTMLResponse)
async def tg_browser_consume(
    request: Request,
    response: Response,
    code: str = "",
    handoff: BrowserHandoffService = Depends(_handoff_service),
    sessions: WebSessionsService = Depends(get_sessions_service),
):
    payload = await handoff.consume_handoff(code)
    if payload is None:
        return _templates(request).TemplateResponse(
            request,
            "tg/bootstrap_error.html",
            {},
            status_code=410,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
            },
        )

    raw, _context = await sessions.create_session(
        user_id=payload.user_id,
        user_agent=request.headers.get("user-agent"),
        surface="browser",
    )
    settings = request.app.state.web_settings
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw,
        max_age=settings.session_cookie_max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return RedirectResponse(
        url=payload.target_path,
        status_code=303,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )