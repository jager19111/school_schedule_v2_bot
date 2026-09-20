"""Слой генерации PNG-постеров расписания (ТЗ v2.2 — ImageGenerationService).

Изоляция зависимостей: модуль не знает про NIKA, БД и Telegram.
На входе доменная PosterRequest, на выходе RenderedPoster (PNG bytes).
Две реализации RendererPort: PlaywrightRenderer (singleton-Chromium)
и PillowRenderer (fallback без браузера для слабых серверов).
"""

from services.image_render.exceptions import (
    ImageRenderError,
    QueueOverflowError,
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
from services.image_render.settings import ImageRenderSettings

__all__ = [
    "ImageRenderError",
    "ImageRenderSettings",
    "LessonStatus",
    "PosterLessonCard",
    "PosterRequest",
    "QueueOverflowError",
    "RenderedPoster",
    "RenderTimeoutError",
    "RendererPort",
    "RendererUnavailableError",
]
