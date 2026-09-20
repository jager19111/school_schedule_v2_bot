"""Владелец singleton-браузера Playwright. Строго async API!

Правила жизненного цикла (защита от OOM и утечек памяти):
- chromium.launch() выполняется один раз, ЛЕНИВО — при первом рендере,
  а не при старте бота (бот не платит RAM за неиспользуемую графику);
- плановый рецикл: по счётчику рендеров ИЛИ по возрасту процесса —
  что наступит раньше (профилактика деградации Chromium);
- аварийный рецикл: is_connected() == False -> перезапуск в acquire();
- перезапуски сериализованы asyncio.Lock — конкурентные рестарты
  и дублирование процессов запрещены;
- shutdown() вызывается из main() по SIGTERM/SIGINT, чтобы не оставлять
  осиротевших chrome-процессов после каждого деплоя.

С версии playwright 1.57 используется бандл Chrome for Testing
(на ARM64 Linux остаётся classic Chromium) — см. чейнджлог Playwright.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from services.image_render.exceptions import RendererUnavailableError
from services.image_render.settings import ImageRenderSettings

logger = logging.getLogger(__name__)

# Стабильные флаги запуска: /dev/shm в контейнерах мал, GPU не нужен,
# фоновые сервисы не нужны — страница локальная и статическая.
_LAUNCH_ARGS = (
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-first-run",
    "--disable-extensions",
    "--disable-background-networking",
    "--no-default-browser-check",
)


class BrowserLifecycleManager:
    """Единственный владелец процесса Chromium на весь бот."""

    def __init__(self, settings: ImageRenderSettings) -> None:
        self._settings = settings
        self._playwright: Any = None   # Playwright driver (ленивый импорт)
        self._browser: Any = None      # Browser
        self._render_count = 0
        self._born_at = 0.0
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def render_count(self) -> int:
        """Сколько рендеров пережил текущий процесс браузера."""
        return self._render_count

    async def acquire(self) -> Any:
        """Возвращает живой браузер; при необходимости (пере)запускает его.

        Лок держит только проверку/перезапуск — сами рендеры идут
        параллельно (browser.new_context() потокобезопасен).
        """
        if self._closed:
            raise RendererUnavailableError("BrowserLifecycleManager остановлен")
        async with self._lock:
            if self._needs_restart_locked():
                await self._restart_locked()
        return self._browser

    def on_render_finished(self) -> None:
        """Вызывается рендерером после успешного скриншота."""
        self._render_count += 1

    def _needs_restart_locked(self) -> bool:
        if self._browser is None:
            return True
        if not self._browser.is_connected():
            logger.warning("Chromium потерял соединение — перезапускаю")
            return True
        if self._render_count >= self._settings.browser_recycle_renders:
            logger.info("Рецикл браузера по счётчику: %d рендеров", self._render_count)
            return True
        age_sec = time.monotonic() - self._born_at
        if age_sec >= self._settings.browser_recycle_interval_min * 60:
            logger.info("Рецикл браузера по возрасту: %.1f ч", age_sec / 3600)
            return True
        return False

    async def _restart_locked(self) -> None:
        # Ленивый импорт: слой рендера должен импортироваться без Playwright
        # (weak-серверы с IMAGE_RENDER_ENGINE=pillow не тянут драйвер).
        from playwright.async_api import async_playwright

        await self._close_browser_locked()
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=list(_LAUNCH_ARGS),
            )
        except Exception as exc:  # noqa: BLE001 — пробрасываем как доменную ошибку
            raise RendererUnavailableError(f"Не удалось запустить Chromium: {exc}") from exc
        self._render_count = 0
        self._born_at = time.monotonic()
        logger.info("Chromium запущен (счётчики рецикла сброшены)")

    async def _close_browser_locked(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:  # noqa: BLE001 — не блокируем рецикл
                logger.warning("Ошибка закрытия браузера", exc_info=True)
            self._browser = None

    async def is_healthy(self) -> bool:
        """Жив ли текущий процесс браузера (без перезапуска)."""
        return self._browser is not None and self._browser.is_connected()

    async def shutdown(self) -> None:
        """Полная остановка: браузер + драйвер Playwright. Идемпотентен."""
        self._closed = True
        async with self._lock:
            await self._close_browser_locked()
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:  # noqa: BLE001
                    logger.warning("Ошибка остановки Playwright", exc_info=True)
                self._playwright = None
        logger.info("BrowserLifecycleManager остановлен")
