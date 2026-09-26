# web/deps.py
#
# DI web-слоя: резолвция actor-контекста из session cookie.
#
# Правила:
# - actor_user_id берётся ТОЛЬКО из валидной web-сессии;
# - роль/family-admin/права НЕ берутся из cookie — разрешаются
#   заново на каждом запросе через ProfileService (ТЗ 13.3);
# - family allowlist (WEB_ACCESS_MODE) — дополнительный ограничитель
#   доступа, не механизм аутентификации (решение Phase 0, п. 11).
#
# Никаких X-User-ID/X-Role/X-Family-ID из запроса — никогда.

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request

from services.profiles_service import ProfileService
from services.web_sessions_service import SESSION_COOKIE_NAME, WebSessionContext
from services.web_sessions_service import WebSessionsService

logger = logging.getLogger(__name__)


def get_sessions_service(request: Request) -> WebSessionsService:
    return request.app.state.sessions_service


def get_profile_service(request: Request) -> ProfileService:
    return request.app.state.profile_service


async def get_session_context(
    request: Request,
    sessions: WebSessionsService = Depends(get_sessions_service),
) -> WebSessionContext:
    """Auth-зависимость: cookie -> валидная сессия -> actor-контекст."""
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        raise HTTPException(status_code=401, detail="Требуется вход.")
    context = await sessions.resolve_session(raw)
    if context is None:
        raise HTTPException(status_code=401, detail="Сессия недействительна.")
    return context


async def get_raw_session_token(request: Request) -> str:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        raise HTTPException(status_code=401, detail="Требуется вход.")
    return raw


async def get_current_user_dto(
    context: WebSessionContext = Depends(get_session_context),
    profile_service: ProfileService = Depends(get_profile_service),
):
    """
    Актуальный Telegram-профиль actor'а (роль/семья/права — из БД,
    не из cookie: изменение роли в Telegram подхватывается сразу).
    """
    dto = await profile_service.get_user_profile_dto(context.user_id)
    if dto is None:
        raise HTTPException(status_code=401, detail="Профиль не найден.")
    return dto


async def require_family_allowed(
    request: Request,
    context: WebSessionContext = Depends(get_session_context),
    profile_service: ProfileService = Depends(get_profile_service),
) -> WebSessionContext:
    """
    WEB_ACCESS_MODE=family_allowlist: session -> user -> family -> allowlist.

    Отдельный слой защиты для семейного deployment; public-режим
    снимает ограничение без изменения остального кода.
    """
    web_settings = request.app.state.web_settings
    if web_settings.access_mode != "family_allowlist":
        return context

    allowed_ids = web_settings.allowed_family_ids
    if not allowed_ids:
        # Allowlist задан режимом, но пуст -> закрытый доступ для всех.
        raise HTTPException(status_code=403, detail="Доступ закрыт.")

    dto = await profile_service.get_user_profile_dto(context.user_id)
    family_id = getattr(dto, "family_id", None)
    if family_id is None or int(family_id) not in allowed_ids:
        raise HTTPException(status_code=403, detail="Доступ закрыт.")
    return context
