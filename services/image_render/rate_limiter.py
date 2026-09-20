"""Per-user rate limiter фактических запусков рендера (ТЗ v2.2, раздел 4).

Правило: не более 10 генераций за 3 минуты на пользователя.
Кэш-хиты и присоединение к уже идущему рендеру лимит не расходуют.
Системные вызовы (warm-up, user_id=None) идут в обход лимита —
это осознанный трейд-офф: ранний утренний пользователь может встать
в общую очередь за системными задачами рендера.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable


class SlidingWindowRateLimiter:
    """Скользящее окно timestamp'ов; вызывается только из event loop."""

    def __init__(
        self,
        max_events: int,
        window_sec: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_events = max_events
        self._window_sec = window_sec
        self._clock = clock
        self._events: dict[int, deque[float]] = defaultdict(deque)
        self._last_prune = 0.0

    def allow(self, user_id: int) -> bool:
        """True — событие разрешено и записано; False — лимит исчерпан."""
        now = self._clock()
        self._maybe_prune(now)
        events = self._events[user_id]
        cutoff = now - self._window_sec
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= self._max_events:
            return False
        events.append(now)
        return True

    def retry_after(self, user_id: int) -> float:
        """Сколько секунд до освобождения слота (для текста alert'а)."""
        events = self._events.get(user_id)
        if not events:
            return 0.0
        return max(0.0, events[0] + self._window_sec - self._clock())

    def _maybe_prune(self, now: float) -> None:
        """Чистка неактивных пользователей — защита от роста памяти."""
        if now - self._last_prune < self._window_sec:
            return
        self._last_prune = now
        cutoff = now - self._window_sec
        stale = [
            user_id
            for user_id, events in self._events.items()
            if not events or events[-1] <= cutoff
        ]
        for user_id in stale:
            del self._events[user_id]
