# web/routes/auth.py
#
# Authentication endpoints Phase 1.
#
# Формат ссылки: {WEB_PUBLIC_URL}/auth#token=RAW (URL fragment, не query).
# Frontend (static/js/auth.js) читает fragment и делает POST exchange.
# Все auth-ошибки — обобщённые, без раскрытия состояния токена.

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from services.web_sessions_service import (
    SESSION_COOKIE_NAME,
    WebSessionContext,
    WebSessionsService,
)
from web.deps import (
    get_current_user_dto,
    get_session_context,
    get_sessions_service,
    require_family_allowed,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_AUTH_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Вход — School Schedule</title>
</head>
<body class="auth-page">
<main class="auth-card">
  <h1>📅 School Schedule</h1>
  <p id="status">Открываем веб-версию…</p>
</main>
<script src="/static/js/auth.js"></script>
</body>
</html>
"""


class ExchangeRequest(BaseModel):
    token: str = Field(min_length=8, max_length=256)


class ExchangeResponse(BaseModel):
    ok: bool = True
    redirect: str = "/"
    csrf_token: str


class LogoutResponse(BaseModel):
    ok: bool = True


class WebMeResponse(BaseModel):
    """Web-схема: наружу не уходят внутренние ID и служебные поля."""

    user_id: int
    role: str | None
    is_fully_registered: bool
    csrf_token: str


class WebSessionItem(BaseModel):
    session_id: int
    user_agent: str
    created_at: str | None
    last_seen_at: str | None
    current: bool


@router.get("/auth", response_class=HTMLResponse)
async def auth_page() -> HTMLResponse:
    """Страница входа: работает и в Safari, и во встроенном браузере Telegram."""
    return HTMLResponse(_AUTH_PAGE)


@router.post("/api/v1/auth/exchange", response_model=ExchangeResponse)
async def exchange(
    payload: ExchangeRequest,
    request: Request,
    response: Response,
    sessions: WebSessionsService = Depends(get_sessions_service),
) -> ExchangeResponse:
    """
    Одноразовый обмен magic-link токена на web-сессию.

    Повторное использование / истёкший / неизвестный токен -> 401
    с обобщённым сообщением (не раскрываем, какой именно случай).
    """
    user_id = await sessions.exchange_login_token(payload.token)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Ссылка недействительна или истекла. "
            "Запросите новую в Telegram-боте.",
        )

    raw, context = await sessions.create_session(
        user_id=user_id,
        user_agent=request.headers.get("user-agent"),
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
    # Token исчезает из URL: fragment не уходит на сервер и затирается
    # переходом на "/" (auth.js очищает location.hash).
    return ExchangeResponse(ok=True, redirect="/", csrf_token=context.csrf_token)


@router.post("/api/v1/auth/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    context: WebSessionContext = Depends(get_session_context),
    sessions: WebSessionsService = Depends(get_sessions_service),
) -> LogoutResponse:
    """Logout текущего устройства (отзывает только текущую сессию)."""
    raw = request.cookies.get(SESSION_COOKIE_NAME, "")
    await sessions.revoke_session(raw_token=raw, user_id=context.user_id)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return LogoutResponse(ok=True)


@router.post("/api/v1/auth/logout-all", response_model=LogoutResponse)
async def logout_all(
    response: Response,
    context: WebSessionContext = Depends(require_family_allowed),
    sessions: WebSessionsService = Depends(get_sessions_service),
) -> LogoutResponse:
    """Logout на всех устройствах."""
    await sessions.revoke_all_sessions(user_id=context.user_id)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return LogoutResponse(ok=True)


@router.get("/api/v1/me", response_model=WebMeResponse)
async def me(
    context: WebSessionContext = Depends(require_family_allowed),
    profile=Depends(get_current_user_dto),
) -> WebMeResponse:
    """Текущий actor: Telegram-профиль + CSRF-токен для HTMX hx-headers."""
    return WebMeResponse(
        user_id=context.user_id,
        role=getattr(profile, "role", None),
        is_fully_registered=bool(getattr(profile, "is_fully_registered", False)),
        csrf_token=context.csrf_token,
    )


@router.get("/api/v1/sessions", response_model=list[WebSessionItem])
async def list_sessions(
    context: WebSessionContext = Depends(require_family_allowed),
    sessions: WebSessionsService = Depends(get_sessions_service),
) -> list[WebSessionItem]:
    """Список активных устройств (Settings -> Активные устройства)."""
    devices = await sessions.list_devices(
        user_id=context.user_id,
        current_session_hash=context.session_hash,
    )
    return [
        WebSessionItem(
            session_id=d.session_id,
            user_agent=d.user_agent,
            created_at=d.created_at,
            last_seen_at=d.last_seen_at,
            current=d.current,
        )
        for d in devices
    ]


@router.post("/api/v1/sessions/{session_id}/revoke", response_model=LogoutResponse)
async def revoke_session(
    session_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
    sessions: WebSessionsService = Depends(get_sessions_service),
) -> LogoutResponse:
    """
    Отзыв конкретной сессии из device list.

    Владелец проверяется в SQL (WHERE user_id = ?): чужой session_id
    не может быть отозван подстановкой.
    """
    ok = await sessions.revoke_session_by_id(
        session_id=session_id, user_id=context.user_id
    )
    return LogoutResponse(ok=ok)
