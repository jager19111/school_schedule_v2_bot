"""DI-сборка слоя постеров (этап 3). Вызывается из main.py — см. wiring в PR."""

from __future__ import annotations

import logging

import aiosqlite

from config import build_image_render_settings
from services.image_preferences import ImagePreferencesService
from services.image_render.browser_lifecycle import BrowserLifecycleManager
from services.image_render.playwright_renderer import PlaywrightRenderer
from services.image_render.pillow_renderer import PillowRenderer
from services.image_render.port import RendererPort
from services.image_render.service import ImageGenerationService

logger = logging.getLogger(__name__)


async def setup_image_generation(
    db_connection: aiosqlite.Connection,
) -> tuple[ImageGenerationService, ImagePreferencesService]:
    """Собирает ImageGenerationService + ImagePreferencesService.

    Возвращает кортеж для dp.workflow_data.update(
        image_service=..., image_prefs=...
    ).
    Движок выбирается настройкой IMAGE_RENDER_ENGINE:
    playwright — Chromium (ленивый запуск при первом рендере),
    pillow — fallback для слабых серверов без браузера.
    """
    settings = build_image_render_settings()
    settings.validate()

    renderer: RendererPort
    if settings.engine == "pillow":
        renderer = PillowRenderer()
    else:
        lifecycle = BrowserLifecycleManager(settings)
        # Нативный Playwright-таймаут = бюджет всего рендера (этап 5)
        renderer = PlaywrightRenderer(
            lifecycle,
            page_timeout_ms=int(settings.render_timeout_sec * 1000),
        )

    image_service = ImageGenerationService(renderer, settings)
    await image_service.startup()

    image_prefs = ImagePreferencesService(db_connection)
    await image_prefs.ensure_schema()

    logger.info("ImageGenerationService инициализирован (движок=%s)", settings.engine)
    return image_service, image_prefs
