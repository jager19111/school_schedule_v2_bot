# web/routes/stream.py
#
# SSE endpoint Phase 7 (ТЗ 51).
#
# - Аутентификация при установке соединения (require_family_allowed).
# - Периодическая server-side revalidation сессии (~60 сек): открытая
#   вкладка не продлевает idle session бесконечно (ТЗ 51.6).
# - Heartbeat (SSE comment) — без пользовательских данных (ТЗ 51.11).
# - logout/revoke закрывает соединение через SessionRevoked (ТЗ 51.7).
# - Персональные данные через SSE не передаются: только
#   {\"revision\": N} (ТЗ 51.4).
# - Rate limiting для SSE — отдельная политика establishment rate
#   (Phase 1, RateLimitMiddleware.SSE_PREFIX), не RPS-bucket.

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from services.web_sessions_service import SESSION_COOKIE_NAME, WebSessionContext
from web.deps import get_sessions_service, require_family_allowed
from web.sse import HEARTBEAT_INTERVAL, SESSION_REVALIDATION_EVERY

logger = logging.getLogger(__name__)
router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",  # nginx proxy_buffering off (ТЗ 51.10)
}


def _sse_manager(request: Request):
    return request.app.state.sse_manager


@router.get("/api/v1/schedule/stream")
async def schedule_stream(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    manager = _sse_manager(request)
    connection = manager.try_register(
        session_id=context.session_id, user_id=context.user_id
    )
    if connection is None:
        return JSONResponse(
            {"detail": "Слишком много открытых обновлений расписания."},
            status_code=429,
            headers=_SSE_HEADERS,
        )

    sessions_service = request.app.state.sessions_service
    raw_cookie = request.cookies.get(SESSION_COOKIE_NAME, "")

    async def event_stream():
        try:
            ticks = 0
            while True:
                try:
                    message = await asyncio.wait_for(
                        connection.queue.get(), timeout=HEARTBEAT_INTERVAL
                    )
                except asyncio.TimeoutError:
                    # Клиент ушёл — корректно завершаем (FastAPI не
                    # уведомляет генератор сам; нужен явный poll).
                    if await request.is_disconnected():
                        break

                    ticks += 1
                    # Revalidation сессии ~раз в минуту (ТЗ 51.6):
                    # touch_session внутри не чаще 1 раза в 5 минут.
                    if ticks % SESSION_REVALIDATION_EVERY == 0:
                        resolved = await sessions_service.resolve_session(raw_cookie)
                        if resolved is None:
                            break  # сессия истекла или отозвана
                    yield ": heartbeat\n\n"
                    continue

                if message is None:
                    break  # закрытие сервером (logout/revoke/close_all)
                yield message
        finally:
            manager.unregister(connection)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/api/v1/live/revalidate", status_code=204)
async def live_revalidate(
    context: WebSessionContext = Depends(require_family_allowed),
):
    """
    Лёгкий 204-эндпоинт для #live-monitor: htmx выполняет этот GET при
    событии sse:schedule_changed; app.js по завершении запроса делает
    revalidate текущего экрана. Персональных данных не содержит.
    """
    return None
