# web/routes/stream.py
#
# SSE endpoint Phase 7 (ТЗ 51).
#
# - Аутентификация при установке соединения.
# - Периодическая server-side revalidation сессии (~60 сек).
# - Heartbeat каждые 15 сек.
# - logout/revoke закрывает соединение через SessionRevoked.
# - персональные данные через SSE не передаются.
# - rate-limit SSE establishment применяется внешним middleware.

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from services.web_sessions_service import (
    SESSION_COOKIE_NAME,
    WebSessionContext,
)
from web.deps import require_family_allowed
from web.sse import (
    HEARTBEAT_INTERVAL,
    SESSION_REVALIDATION_EVERY,
)


logger = logging.getLogger(__name__)
router = APIRouter()


_SSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
}

_SESSION_REVALIDATION_INTERVAL = (
    HEARTBEAT_INTERVAL
    * SESSION_REVALIDATION_EVERY
)


def _sse_manager(request: Request):
    return request.app.state.sse_manager


@router.get("/api/v1/schedule/stream")
async def schedule_stream(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    manager = _sse_manager(request)

    connection = manager.try_register(
        session_id=context.session_id,
        user_id=context.user_id,
    )

    if connection is None:
        return JSONResponse(
            {
                "detail": (
                    "Слишком много открытых обновлений расписания."
                ),
            },
            status_code=429,
            headers=_SSE_HEADERS,
        )

    sessions_service = request.app.state.sessions_service
    raw_cookie = request.cookies.get(SESSION_COOKIE_NAME, "")

    async def event_stream():
        """
        SSE loop.

        Важно: next_revalidation_at считается по monotonic loop.time(),
        а не по количеству heartbeat timeout. Иначе частые ScheduleChanged
        могли бы навсегда отложить server-side session revalidation.
        """
        loop = asyncio.get_running_loop()
        next_heartbeat_at = loop.time() + HEARTBEAT_INTERVAL
        next_revalidation_at = (
            loop.time()
            + _SESSION_REVALIDATION_INTERVAL
        )

        try:
            while True:
                now = loop.time()
                wait_seconds = max(
                    0.0,
                    next_heartbeat_at - now,
                )

                timed_out = False
                message = None

                try:
                    message = await asyncio.wait_for(
                        connection.queue.get(),
                        timeout=wait_seconds,
                    )
                except asyncio.TimeoutError:
                    timed_out = True

                now = loop.time()

                # Проверка session не должна зависеть от того, приходят ли
                # schedule events чаще heartbeat interval.
                if now >= next_revalidation_at:
                    resolved = await sessions_service.resolve_session(
                        raw_cookie,
                    )

                    if resolved is None:
                        break

                    next_revalidation_at = (
                        now
                        + _SESSION_REVALIDATION_INTERVAL
                    )

                if timed_out:
                    if await request.is_disconnected():
                        break

                    yield ": heartbeat\n\n"
                    next_heartbeat_at = now + HEARTBEAT_INTERVAL
                    continue

                if message is None:
                    # Server-side close: logout/revoke/queue overflow/shutdown.
                    break

                yield message

                # При непрерывном event traffic timeout может не случаться.
                # Heartbeat всё равно должен появляться регулярно, а также
                # служит точкой проверки disconnected client.
                if now >= next_heartbeat_at:
                    if await request.is_disconnected():
                        break

                    yield ": heartbeat\n\n"
                    next_heartbeat_at = now + HEARTBEAT_INTERVAL

        finally:
            manager.unregister(connection)

    # BackgroundTask — дополнительная гарантия cleanup.
    #
    # Normal flow уже вызывает manager.unregister(connection) в finally
    # внутри event_stream(). unregister() идемпотентен, поэтому второй
    # вызов безопасен.
    #
    # Это покрывает edge case, когда client disconnected после
    # try_register(), но до первого запуска async generator.
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
        background=BackgroundTask(
            manager.unregister,
            connection,
        ),
    )


@router.get("/api/v1/live/revalidate", status_code=204)
async def live_revalidate(
    context: WebSessionContext = Depends(require_family_allowed),
):
    """
    Лёгкий authenticated endpoint для #live-monitor.

    htmx вызывает его после schedule_changed; app.js после 204 выполняет
    reload current page. Endpoint не возвращает расписание или user data.
    """
    return None