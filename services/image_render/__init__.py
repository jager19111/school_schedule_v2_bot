"""Слой генерации PNG-постеров расписания (ТЗ v2.2 — ImageGenerationService).

Изоляция зависимостей: модуль не знает про NIKA, БД и Telegram.
На входе доменная PosterRequest, на выходе RenderedPoster (PNG bytes).

Состав:
- RendererPort — абстракция движка; реализации: PlaywrightRenderer
  (singleton-Chromium) и PillowRenderer (fallback без браузера);
- ImageGenerationService — кэши L1/L2, single-flight, semaphore,
  rate limit, circuit breaker, общий таймаут;
- poster_factory — DayScheduleDTO -> PosterRequest + версионированные
  ключи кэша (schedule_version).
"""

from services.image_render.circuit_breaker import CircuitBreaker, CircuitState
from services.image_render.exceptions import (
    ImageRenderError,
    QueueOverflowError,
    RateLimitExceededError,
    RenderTimeoutError,
    RendererUnavailableError,
)
from services.image_render.models import (
    LessonStatus,
    PosterLessonCard,
    PosterRequest,
    RenderedPoster,
)
from services.image_render.port import RendererPort
from services.image_render.poster_factory import (
    build_global_request_id,
    build_personal_request_id,
    build_poster_request,
    extra_classes_hash,
)
from services.image_render.rate_limiter import SlidingWindowRateLimiter
from services.image_render.service import ImageGenerationService, ImageServiceStats
from services.image_render.settings import ImageRenderSettings

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "ImageGenerationService",
    "ImageRenderError",
    "ImageRenderSettings",
    "ImageServiceStats",
    "LessonStatus",
    "PosterLessonCard",
    "PosterRequest",
    "QueueOverflowError",
    "RateLimitExceededError",
    "RenderedPoster",
    "RenderTimeoutError",
    "RendererPort",
    "RendererUnavailableError",
    "SlidingWindowRateLimiter",
    "build_global_request_id",
    "build_personal_request_id",
    "build_poster_request",
    "extra_classes_hash",
]
