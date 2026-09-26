# web/idempotency.py
#
# In-process защита от повторного применения POST (ТЗ 60).
#
# Решение Phase 0/5: Idempotency-Key для mutation, где повторный запрос
# создаёт нежелательный дубль (в первую очередь POST extra class).
# Один процесс = in-memory корректен; при переходе к multi-worker
# заменяется на shared-хранилище (как rate limiter).
#
# Ключ генерируется при рендере формы (hidden input) и «сгорает»
# при первом успешном применении: повторная отправка (double tap,
# повторная отправка формы браузером) становится no-op.

from __future__ import annotations

import secrets
import time
from typing import Dict


class IdempotencyStore:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self._ttl = ttl_seconds
        self._seen: Dict[str, float] = {}

    def new_key(self) -> str:
        """Свежий ключ для hidden-поля формы."""
        return secrets.token_urlsafe(24)

    def _cleanup(self, now: float) -> None:
        expired = [k for k, ts in self._seen.items() if now - ts > self._ttl]
        for key in expired:
            self._seen.pop(key, None)

    def consume(self, key: str) -> bool:
        """
        True — ключ новый (выполняем операцию).
        False — ключ уже использован (повторный запрос: no-op).
        """
        if not key or len(key) > 128:
            return True  # отсутствие ключа не блокирует, но и не защищает
        now = time.monotonic()
        self._cleanup(now)
        if key in self._seen:
            return False
        self._seen[key] = now
        return True
