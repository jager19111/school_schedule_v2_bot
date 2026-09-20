"""Circuit breaker против «мучения» пользователей полным таймаутом.

При серии ошибок рендера цепь размыкается: все запросы мгновенно
получают RendererUnavailableError (graceful degradation в текст)
без ожидания semaphore и таймаута. Через cooldown разрешается одна
проба (half-open): успех — замыкаем, провал — снова размыкаем.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Callable


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


class CircuitBreaker:
    """Замкнут -> разомкнут (серия ошибок) -> half-open (проба)."""

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_sec: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_sec = cooldown_sec
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> CircuitState:
        return self._state

    def allow(self) -> bool:
        """Разрешён ли запуск рендера (учитывая half-open пробу)."""
        if self._state is CircuitState.CLOSED:
            return True
        if self._state is CircuitState.OPEN:
            if self._clock() - self._opened_at >= self._cooldown_sec:
                self._state = CircuitState.HALF_OPEN
                return True  # разрешаем одну пробу
            return False
        return False  # HALF_OPEN: проба уже выполняется

    def record_success(self) -> None:
        self._state = CircuitState.CLOSED
        self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._state is CircuitState.HALF_OPEN or self._failures >= self._failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()
