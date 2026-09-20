"""Рендер постера через singleton-Chromium: один контекст на запрос.

Гарантии (раздел 3 ТЗ v2.2):
- контекст и вкладка закрываются в finally — утечка вкладок невозможна;
- внешние сетевые запросы блокируются (_route_guard): шаблон
  и шрифты строго локальные, рендер не ходит в интернет;
- перед скриншотом ожидается document.fonts.ready — текст не должен
  перехватиться системным fallback-шрифтом;
- скриншот обрезается по контейнеру #poster (динамическая высота).

ВНИМАНИЕ: только async API Playwright — sync-варианты из документации
блокируют event loop бота и несовместимы с aiogram.
"""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from services.image_render.browser_lifecycle import BrowserLifecycleManager
from services.image_render.exceptions import ImageRenderError
from services.image_render.models import PosterRequest, RenderedPoster
from services.image_render.port import RendererPort

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class PlaywrightRenderer(RendererPort):
    """Движок рендера через Chromium (Chrome for Testing с playwright 1.57+)."""

    def __init__(self, lifecycle: BrowserLifecycleManager) -> None:
        self._lifecycle = lifecycle
        self._jinja = Environment(
            loader=FileSystemLoader(_TEMPLATE_DIR),
            autoescape=select_autoescape(["html", "j2"]),
        )

    async def startup(self) -> None:
        # Браузер стартует лениво при первом рендере (BrowserLifecycleManager.acquire).
        return None

    async def shutdown(self) -> None:
        await self._lifecycle.shutdown()

    async def is_healthy(self) -> bool:
        return await self._lifecycle.is_healthy()

    async def render(self, request: PosterRequest) -> RenderedPoster:
        html = self._jinja.get_template("schedule_poster.html.j2").render(
            date_text=request.date_text,
            title=request.title,
            subtitle=request.subtitle,
            lessons=request.lessons,
            changes_count=request.changes_count,
            width=request.width,
        )
        browser = await self._lifecycle.acquire()
        # Один легковесный контекст на запрос; закрытие гарантировано в finally.
        context = await browser.new_context(
            viewport={"width": request.width, "height": 800},
            device_scale_factor=1,
        )
        try:
            page = await context.new_page()
            # Расписание не должно тянуть ничего из сети.
            await page.route("**/*", _route_guard)
            await page.set_content(html, wait_until="load")
            # Шрифты обязаны успеть примениться до скриншота.
            await page.evaluate("document.fonts.ready")
            element = await page.query_selector("#poster")
            if element is None:
                raise ImageRenderError("В шаблоне нет контейнера #poster")
            box = await element.bounding_box()
            png_bytes = await element.screenshot(type="png")
        finally:
            await context.close()

        self._lifecycle.on_render_finished()
        height = int((box or {}).get("height") or 0)
        logger.debug(
            "Постер %s отрендерен: %dx%d, %d байт",
            request.request_id,
            request.width,
            height,
            len(png_bytes),
        )
        return RenderedPoster(
            request_id=request.request_id,
            png_bytes=png_bytes,
            width=request.width,
            height=height,
        )


async def _route_guard(route) -> None:  # noqa: ANN001 — тип Route из playwright
    """Пропускает только локальный контент; все сетевые запросы — abort."""
    if route.request.url.startswith(("file://", "data:", "about:")):
        await route.continue_()
    else:
        await route.abort()
