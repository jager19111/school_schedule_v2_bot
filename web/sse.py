# web/sse.py
#
# SSEConnectionManager (Phase 7, ТЗ 51.6-51.7).
#
# Правила:
# - каждый процесс один, connections хранятся in-memory;
# - максимум пять SSE connections на пользователя;
# - одна web session может иметь несколько browser tabs;
# - каждая connection имеет уникальный connection_id;
# - очереди bounded: slow client не может бесконечно копить RAM;
# - закрытые connections удаляются из всех индексов;
# - ScheduleChanged не содержит персональных данных;
# - SessionRevoked закрывает одну session либо все sessions пользователя;
# - жизненный цикл SSE не связан с NotificationService.

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

from web.events import ApplicationEventBus, ScheduleChanged, SessionRevoked


logger = logging.getLogger(__name__)


# Heartbeat каждые 15 секунд; revalidation session — примерно раз в минуту.
HEARTBEAT_INTERVAL = 15.0
SESSION_REVALIDATION_EVERY = 4  # 4 * 15s = 60s

# ScheduleChanged — invalidation-only event. Очередь больше этого размера
# не имеет ценности: slow client должен reconnect/reload, а не копить RAM.
SSE_QUEUE_MAXSIZE = 32


@dataclass(slots=True)
class SSEConnection:
    """
    Одно SSE-соединение.

    connection_id идентифицирует конкретный HTTP/SSE stream.
    session_id идентифицирует web session и может иметь несколько tabs.
    """

    connection_id: int
    session_id: int
    user_id: int
    queue: asyncio.Queue[Optional[str]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=SSE_QUEUE_MAXSIZE),
    )
    closed: bool = False


class SSEConnectionManager:
    MAX_CONNECTIONS_PER_USER = 5

    def __init__(self, event_bus: ApplicationEventBus) -> None:
        self._bus = event_bus

        # connection_id -> connection
        self._by_connection: Dict[int, SSEConnection] = {}

        # session_id -> множество connection_id.
        # Одна сессия может быть открыта в нескольких browser tabs.
        self._connection_ids_by_session: Dict[int, set[int]] = {}

        # user_id -> множество connection_id.
        self._connection_ids_by_user: Dict[int, set[int]] = {}

        self._next_connection_id = 0
        self._closed = False

        self._bus.subscribe(ScheduleChanged, self._on_schedule_changed)
        self._bus.subscribe(SessionRevoked, self._on_session_revoked)

    # ==========================================================
    # Регистрация/удаление
    # ==========================================================

    def try_register(
        self,
        *,
        session_id: int,
        user_id: int,
    ) -> Optional[SSEConnection]:
        """
        Регистрирует конкретный SSE stream.

        None означает:
        - web server уже остановлен; либо
        - пользователь превысил лимит connections.

        Лимит считается по реальным connection_id, а не по session_id:
        две вкладки одного browser учитываются как две SSE connections.
        """
        if self._closed:
            logger.warning(
                "SSE registration rejected during shutdown: user_id=%s",
                user_id,
            )
            return None

        active_connection_ids = self._connection_ids_by_user.get(
            user_id,
            set(),
        )

        if len(active_connection_ids) >= self.MAX_CONNECTIONS_PER_USER:
            logger.warning(
                "SSE connection limit reached: user_id=%s",
                user_id,
            )
            return None

        self._next_connection_id += 1

        connection = SSEConnection(
            connection_id=self._next_connection_id,
            session_id=session_id,
            user_id=user_id,
        )

        self._by_connection[connection.connection_id] = connection

        self._connection_ids_by_session.setdefault(
            session_id,
            set(),
        ).add(connection.connection_id)

        self._connection_ids_by_user.setdefault(
            user_id,
            set(),
        ).add(connection.connection_id)

        logger.debug(
            "SSE registered: connection_id=%s session_id=%s "
            "user_id=%s active_for_user=%s total_active=%s",
            connection.connection_id,
            connection.session_id,
            connection.user_id,
            len(self._connection_ids_by_user.get(user_id, set())),
            self.active_count(),
        )
        
        return connection

    def unregister(self, connection: SSEConnection) -> None:
        """
        Удаляет connection из всех indexes.

        Метод идемпотентен: его безопасно вызвать после _close() и затем
        повторно из finally SSE generator.
        """
        stored = self._by_connection.pop(
            connection.connection_id,
            None,
        )

        if stored is None:
            return

        session_connections = self._connection_ids_by_session.get(
            stored.session_id,
        )
        if session_connections is not None:
            session_connections.discard(stored.connection_id)

            if not session_connections:
                self._connection_ids_by_session.pop(
                    stored.session_id,
                    None,
                )

        user_connections = self._connection_ids_by_user.get(
            stored.user_id,
        )
        if user_connections is not None:
            user_connections.discard(stored.connection_id)

            if not user_connections:
                self._connection_ids_by_user.pop(
                    stored.user_id,
                    None,
                )

    def active_count(self) -> int:
        """Количество реально отслеживаемых SSE streams."""
        return len(self._by_connection)

    # ==========================================================
    # Реакция на события шины
    # ==========================================================

    async def _on_schedule_changed(
        self,
        event: ScheduleChanged,
    ) -> None:
        """
        Отправляет всем открытым экранам минимальный invalidation signal.

        Payload намеренно содержит только revision. Расписание, family data,
        user ID, class/group и permissions в SSE не передаются.
        """
        payload = json.dumps(
            {"revision": event.revision},
            separators=(",", ":"),
        )
        message = (
            "event: schedule_changed\n"
            f"data: {payload}\n\n"
        )
        self._broadcast(message)

    async def _on_session_revoked(
        self,
        event: SessionRevoked,
    ) -> None:
        """
        Завершает streams после server-side revoke.

        session_id задан:
        - закрываются все browser tabs конкретной web session.

        session_id is None:
        - закрываются все SSE connections пользователя.
        """
        if event.session_id is not None:
            connection_ids = list(
                self._connection_ids_by_session.get(
                    event.session_id,
                    set(),
                )
            )

            for connection_id in connection_ids:
                connection = self._by_connection.get(connection_id)

                if connection is None:
                    continue

                # Защита от некорректного internal event payload.
                if connection.user_id != event.user_id:
                    logger.warning(
                        "SSE session revoke user mismatch: "
                        "connection_id=%s session_id=%s "
                        "event_user_id=%s connection_user_id=%s",
                        connection.connection_id,
                        event.session_id,
                        event.user_id,
                        connection.user_id,
                    )
                    continue
                self._close(
                    connection,
                    notify_session_revoked=True,
                )

            return

        connection_ids = list(
            self._connection_ids_by_user.get(
                event.user_id,
                set(),
            )
        )

        for connection_id in connection_ids:
            connection = self._by_connection.get(connection_id)

            if connection is not None:
                self._close(
                    connection,
                    notify_session_revoked=True,
                )

    # ==========================================================
    # Внутреннее
    # ==========================================================

    def _broadcast(self, message: str) -> None:
        """
        Доставляет invalidation всем active streams.

        QueueFull означает slow/dead consumer. Старые invalidation events
        бесполезны: connection принудительно закрывается и browser после
        reconnect получает fresh authenticated state.
        """
        for connection in list(self._by_connection.values()):
            if connection.closed:
                continue

            try:
                connection.queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE queue overflow; closing slow connection: "
                    "connection_id=%s session_id=%s user_id=%s",
                    connection.connection_id,
                    connection.session_id,
                    connection.user_id,
                )
                self._close(connection)

    def _close(
        self,
        connection: SSEConnection,
        *,
        notify_session_revoked: bool = False,
    ) -> None:
        """
        Гарантированно завершает SSE generator sentinel-ом.

        Метод синхронный и не содержит await, поэтому между очисткой queue
        и постановкой None не возникает interleaving других coroutine
        текущего event loop.
        """
        if connection.closed:
            return

        connection.closed = True

        # При overflow старые ScheduleChanged больше не важны. Очищаем
        # очередь, чтобы None дошёл до stream generator немедленно.
        while True:
            try:
                connection.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        try:
            if notify_session_revoked:
                # Никаких user ID, session ID, tokens, roles, family data
                # или расписания в SSE payload.
                connection.queue.put_nowait(
                    "event: session_revoked\n"
                    "data: {}\n\n"
                )

            # Sentinel завершает server-side stream generator.
            connection.queue.put_nowait(None)

        except asyncio.QueueFull:
            logger.exception(
                "Unable to enqueue SSE close sequence: "
                "connection_id=%s",
                connection.connection_id,
            )

        self.unregister(connection)

    def close_all(self) -> None:
        """
        Вызывается при shutdown web-сервера.

        Streams получают sentinel, а все in-memory indexes очищаются.
        """
        self._closed = True

        for connection in list(self._by_connection.values()):
            self._close(connection)