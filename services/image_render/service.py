"""ImageGenerationService — публичный API слоя постеров (ТЗ v2.2).

Обязанности:
- L1: TTL-кэш PNG-байтов по request_id (версионированный ключ);
- single-flight: параллельные запросы одного постера = один рендер
  (защита от thundering herd утром и после смены версии расписания);
- semaphore + кап очереди + общий таймаут «ожидание слота + рендер»;
- rate limit (10/3 мин на пользователя) — расходуется только на
  фактический запуск рендера; кэш-хиты и системные вызовы
  (warm-up, user_id=None) лимит не расходуют;
- circuit breaker: серия ошибок -> мгновенный отказ вместо того,
  чтобы каждый пользователь платил полным таймаутом;
- L2: кэш Telegram file_id поверх байтов; протухший file_id
  инвалидируется (invalidate_file_id), хендлер перезаливает постер.

Слой не знает про Telegram/aiogram: отправка и file_id-фолбэк —
в хендлерах (этап 3).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from services.image_render.circuit_breaker import CircuitBreaker
from services.image_render.exceptions import (
    QueueOverflowError,
    RateLimitExceededError,
    RenderTimeoutError,
    RendererUnavailableError,
)
from services.image_render.models import PosterRequest, RenderedPoster
from services.image_render.port import RendererPort
from services.image_render.rate_limiter import SlidingWindowRateLimiter
from services.image_render.settings import ImageRenderSettings

logger = logging.getLogger(__name__)


@dataclass
class ImageServiceStats:
    """Счётчики для калибровки констант и /img_stats."""

    renders: int = 0
    cache_hits: int = 0
    inflight_joins: int = 0
    rate_limited: int = 0
    queue_rejections: int = 0
    timeouts: int = 0
    breaker_rejections: int = 0
    render_errors: int = 0

    def snapshot(self) -> dict[str, int]:
        return asdict(self)


class _TTLCache:
    """Минимальный TTL-кэш без внешних зависимостей (cachetools не тянем).

    Не потокобезопасен — используется только из event loop бота.
    """

    def __init__(
        self,
        maxsize: int,
        ttl: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._maxsize = maxsize
        self._ttl = ttl
        self._clock = clock
        self._data: dict[str, Any] = {}
        self._expires: dict[str, float] = {}

    def get(self, key: str) -> Any | None:
        if key not in self._data:
            return None
        if self._expires[key] <= self._clock():
            self._drop(key)
            return None
        return self._data[key]

    def set(self, key: str, value: Any) -> None:
        if key not in self._data and len(self._data) >= self._maxsize:
            self._evict_oldest()
        self._data[key] = value
        self._expires[key] = self._clock() + self._ttl

    def pop(self, key: str) -> Any | None:
        value = self._data.pop(key, None)
        self._expires.pop(key, None)
        return value

    def __len__(self) -> int:
        return len(self._data)

    def _drop(self, key: str) -> None:
        self._data.pop(key, None)
        self._expires.pop(key, None)

    def _evict_oldest(self) -> None:
        if not self._expires:
            return
        victim = min(self._expires, key=self._expires.get)
        self._drop(victim)


class ImageGenerationService:
    """Единая точка получения PNG-постеров для хендлеров."""

    def __init__(self, renderer: RendererPort, settings: ImageRenderSettings) -> None:
        settings.validate()
        self._renderer = renderer
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.concurrency)
        self._waiting = 0  # ждущих в очереди на semaphore
        self._inflight: dict[str, asyncio.Task[RenderedPoster]] = {}
        self._inflight_lock = asyncio.Lock()
        self._bytes_cache = _TTLCache(settings.cache_maxsize, settings.cache_ttl_sec)
        self._file_id_cache = _TTLCache(settings.cache_maxsize, settings.cache_ttl_sec)
        self._rate_limiter = SlidingWindowRateLimiter(
            settings.rate_limit_max, settings.rate_limit_window_sec
        )
        self._breaker = CircuitBreaker(
            settings.breaker_failure_threshold, settings.breaker_cooldown_sec
        )
        self._stats = ImageServiceStats()

    async def startup(self) -> None:
        await self._renderer.startup()

    async def shutdown(self) -> None:
        await self._renderer.shutdown()

    async def is_healthy(self) -> bool:
        return await self._renderer.is_healthy()

    def stats(self) -> ImageServiceStats:
        return self._stats

    def snapshot(self) -> dict[str, object]:
        """Сводное runtime-состояние для /img_stats (админ).

        Состояние breaker'а, число идущих рендеров, ждущих в очереди
        и размеры кэшей L1/L2.
        """
        return {
            "breaker_state": self._breaker.state.value,
            "inflight": len(self._inflight),
            "waiting": self._waiting,
            "cached_posters": len(self._bytes_cache),
            "cached_file_ids": len(self._file_id_cache),
        }

    # ---------------- L2: file_id ----------------

    def get_file_id(self, request_id: str) -> str | None:
        """file_id загруженного постера; None — отправлять байтами/рендерить."""
        return self._file_id_cache.get(request_id)

    def store_file_id(self, request_id: str, file_id: str) -> None:
        self._file_id_cache.set(request_id, file_id)

    def invalidate_file_id(self, request_id: str) -> None:
        """Протухший file_id (чистка Telegram / новый токен): удаляем запись.

        Хендлер после этого повторно отправит постер байтами из L1
        и сохранит новый file_id через store_file_id.
        """
        self._file_id_cache.pop(request_id)

    # ---------------- основной путь ----------------

    async def get_poster(
        self,
        request: PosterRequest,
        *,
        user_id: int | None = None,
    ) -> RenderedPoster:
        """Возвращает постер из кэша или рендерит его.

        user_id=None — системный вызов (warm-up, утренняя рассылка):
        rate limiter обходится, но semaphore/таймаут/circuit breaker
        действуют как для всех остальных.
        """
        cached = self._bytes_cache.get(request.request_id)
        if cached is not None:
            self._stats.cache_hits += 1
            return cached

        if not self._breaker.allow():
            self._stats.breaker_rejections += 1
            raise RendererUnavailableError(
                "Графический движок временно недоступен (circuit breaker)"
            )

        async with self._inflight_lock:
            inflight = self._inflight.get(request.request_id)
            if inflight is None:
                # Лимит расходуем только здесь: начинается реальный рендер.
                if user_id is not None and not self._rate_limiter.allow(user_id):
                    self._stats.rate_limited += 1
                    wait = self._rate_limiter.retry_after(user_id)
                    raise RateLimitExceededError(
                        f"Слишком много запросов к графическому движку, "
                        f"подождите ~{int(wait) + 1} с"
                    )
                inflight = asyncio.create_task(self._render_task(request))
                self._inflight[request.request_id] = inflight
            else:
                self._stats.inflight_joins += 1

        # shield: отмена одного ожидания не роняет общий рендер
        return await asyncio.shield(inflight)

    async def _render_task(self, request: PosterRequest) -> RenderedPoster:
        try:
            poster = await self._render_with_limits(request)
            self._bytes_cache.set(request.request_id, poster)
            self._breaker.record_success()
            return poster
        except Exception:  # noqa: BLE001 — любой сбой двигает breaker
            self._stats.render_errors += 1
            self._breaker.record_failure()
            raise
        finally:
            async with self._inflight_lock:
                self._inflight.pop(request.request_id, None)

    async def _render_with_limits(self, request: PosterRequest) -> RenderedPoster:
        """Очередь + semaphore + общий таймаут «ожидание слота + рендер»."""
        if self._waiting >= self._settings.queue_capacity:
            self._stats.queue_rejections += 1
            raise QueueOverflowError("Очередь рендера переполнена — попробуйте позже")

        self._waiting += 1
        try:

            async def _render() -> RenderedPoster:
                async with self._semaphore:
                    return await self._renderer.render(request)

            try:
                poster = await asyncio.wait_for(
                    _render(), timeout=self._settings.render_timeout_sec
                )
            except asyncio.TimeoutError as exc:
                self._stats.timeouts += 1
                raise RenderTimeoutError(
                    f"Рендер не уложился в {self._settings.render_timeout_sec:.1f} с"
                ) from exc
            self._stats.renders += 1
            return poster
        finally:
            self._waiting -= 1
