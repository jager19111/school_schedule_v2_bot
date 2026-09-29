# web/sse.py
#
# SSEConnectionManager (Phase 7, ТЗ 51.6-51.7).
#
# Правила (решения Phase 0 + ТЗ):
# - каждый процесс один, connections хранятся in-memory;
# - максимальное число SSE connections на пользователя (anti-abuse);
# - закрытые connections обязательно удаляются (нет утечек памяти);
# - invalidation signal НЕ содержит персональных данных;
# - SessionRevoked -> закрыть все SSE пользователя best effort;
# - жизненный цикл SSE НЕ связан с NotificationService.

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from web.events import ApplicationEventBus, ScheduleChanged, SessionRevoked

logger = logging.getLogger(__name__)

# Heartbeat каждые 15 секунд; revalidation сессии ~раз в минуту.
HEARTBEAT_INTERVAL = 15.0
SESSION_REVALIDATION_EVERY = 4  # 4 * 15s = 60s


@dataclass(slots=True)
class SSEConnection:
    """Одно SSE-соединение, привязанное к web session (ТЗ 51.6)."""

    session_id: int
    user_id: int
    queue: "asyncio.Queue[Optional[str]]" = field(default_factory=asyncio.Queue)

    @property
    def closed(self) -> bool:
        return self.queue is None


class SSEConnectionManager:
    MAX_CONNECTIONS_PER_USER = 5

    def __init__(self, event_bus: ApplicationEventBus) -> None:
        self._bus = event_bus
        # session_id -> connection; user_id -> set(session_id)
        self._by_session: Dict[int, SSEConnection] = {}
        self._by_user: Dict[int, set] = {}
        self._closed = False

        # Подписки: события шины -> действия над соединениями.
        self._bus.subscribe(ScheduleChanged, self._on_schedule_changed)
        self._bus.subscribe(SessionRevoked, self._on_session_revoked)

    # ==========================================================
    # Регистрация/удаление
    # ==========================================================

    def try_register(self, *, session_id: int, user_id: int) -> Optional[SSEConnection]:
        """None — превышен лимит соединений пользователя (anti-abuse)."""
        active = self._by_user.setdefault(user_id, set())
        if len(active) >= self.MAX_CONNECTIONS_PER_USER:
            logger.warning(
                "SSE connection limit reached: user_id=%s", user_id
            )
            return None
        connection = SSEConnection(session_id=session_id, user_id=user_id)
        self._by_session[session_id] = connection
        active.add(session_id)
        return connection

    def unregister(self, connection: SSEConnection) -> None:
        """Обязательная очистка: соединение закрыто (нет утечек памяти)."""
        self._by_session.pop(connection.session_id, None)
        active = self._by_user.get(connection.user_id)
        if active is not None:
            active.discard(connection.session_id)
            if not active:
                self._by_user.pop(connection.user_id, None)

    def active_count(self) -> int:
        return len(self._by_session)

    # ==========================================================
    # Реакция на события шины
    # ==========================================================

    async def _on_schedule_changed(self, event: ScheduleChanged) -> None:
        """Минимальный invalidation signal всем открытым экранам (ТЗ 51.4)."""
        payload = json.dumps({"revision": event.revision})
        message = f"event: schedule_changed\ndata: {payload}\n\n"
        await self._broadcast(message)

    async def _on_session_revoked(
        self,
        event: SessionRevoked,
    ) -> None:
        """
        Закрывает SSE stream после server-side session revoke.

        session_id is None:
        - отозваны все web sessions пользователя;
        - закрываем все SSE connections этого пользователя.

        session_id задан:
        - отозвана одна конкретная web session;
        - закрываем SSE только этой session.

        Даже если закрытие не сработало мгновенно, следующая session
        revalidation в stream-цикле завершит connection, а reconnect
        отозванной session получит 401.
        """

        if event.session_id is not None:
            connection = self._by_session.get(
                event.session_id
            )

            if connection is None:
                return

            # Защита от ошибочного internal event payload.
            if connection.user_id != event.user_id:
                logger.warning(
                    "SSE session revoke user mismatch: "
                    "session_id=%s event_user_id=%s connection_user_id=%s",
                    event.session_id,
                    event.user_id,
                    connection.user_id,
                )
                return

            await self._close(connection)
            return

        session_ids = list(
            self._by_user.get(event.user_id, ())
        )

        for session_id in session_ids:
            connection = self._by_session.get(session_id)

            if connection is not None:
                await self._close(connection)

    # ==========================================================
    # Внутреннее
    # ==========================================================

    async def _broadcast(self, message: str) -> None:
        for connection in list(self._by_session.values()):
            try:
                connection.queue.put_nowait(message)
            except asyncio.QueueFull:
                # Переполненная очередь = «мёртвый» клиент: закрываем.
                logger.warning("SSE queue overflow, closing session %s", connection.session_id)
                await self._close(connection)

    async def _close(self, connection: SSEConnection) -> None:
        """Sentinel None завершает stream-генератор."""
        try:
            connection.queue.put_nowait(None)
        except asyncio.QueueFull:
            self.unregister(connection)

    def close_all(self) -> None:
        """Вызывается из shutdown main.py при остановке web-сервера."""
        for connection in list(self._by_session.values()):
            try:
                connection.queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._by_session.clear()
        self._by_user.clear()
