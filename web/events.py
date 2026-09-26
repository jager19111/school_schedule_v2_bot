# web/events.py
#
# ApplicationEventBus (Phase 7, ТЗ 51.3, 59).
#
# In-process event bus: события публикуются ТОЛЬКО после успешного
# commit соответствующего изменения. SSE ConnectionManager подписан на
# эти события; NotificationService с ним НЕ связан (решение Phase 0).
#
# События:
# - ScheduleChanged(revision) — инвалидирующий сигнал (без персональных
#   данных, ТЗ 51.4);
# - SessionRevoked(user_id) — logout/revoke: закрыть SSE этого пользователя.

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Type

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScheduleChanged:
    revision: int


@dataclass(frozen=True, slots=True)
class SessionRevoked:
    user_id: int


class ApplicationEventBus:
    """Простейший in-process pub/sub (один процесс = один loop)."""

    def __init__(self) -> None:
        self._subscribers: Dict[Type, List[Callable[[Any], Any]]] = {}
        self._revision = 0

    def subscribe(
        self, event_type: Type, handler: Callable[[Any], Any]
    ) -> Callable[[], None]:
        """Возвращает unsubscribe-функцию."""
        self._subscribers.setdefault(event_type, []).append(handler)

        def _unsubscribe() -> None:
            try:
                self._subscribers[event_type].remove(handler)
            except (KeyError, ValueError):
                pass

        return _unsubscribe

    def next_revision(self) -> int:
        """Монотонный счётчик изменений расписания (для invalidation signal)."""
        self._revision += 1
        return self._revision

    async def publish(self, event: Any) -> None:
        """
        Доставляет событие всем подписчикам.

        Ошибка одного обработчика не ломает остальных (ТЗ 59:
        одновременные SSE events). Sync-обработчики вызываются как задачи.
        """
        for handler in list(self._subscribers.get(type(event), [])):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "EventBus handler failed for %s", type(event).__name__
                )
