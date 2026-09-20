"""Абстракция движка рендера постеров.

Контракт одинаков для PlaywrightRenderer и PillowRenderer:
- render() детерминирован: одинаковый PosterRequest обязан давать
  визуально одинаковый PNG (основа кэширования по request_id);
- startup()/shutdown() безопасны при многократном вызове;
- реализация не блокирует event loop дольше таймаута рендера
  (общий таймаут «очередь + рендер» навешивается сервисом, этап 2).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.image_render.models import PosterRequest, RenderedPoster


class RendererPort(ABC):
    """Интерфейс движка отрисовки постера в PNG."""

    @abstractmethod
    async def render(self, request: PosterRequest) -> RenderedPoster:
        """Рендерит один постер; при сбое бросает ImageRenderError."""

    @abstractmethod
    async def startup(self) -> None:
        """Инициализация ресурсов. Chromium стартует лениво при первом рендере."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Полное освобождение ресурсов (SIGTERM/SIGINT в main). Идемпотентен."""

    @abstractmethod
    async def is_healthy(self) -> bool:
        """True, если движок готов принимать запросы без перезапуска."""
