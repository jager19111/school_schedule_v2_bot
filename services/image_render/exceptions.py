"""Иерархия ошибок слоя рендера постеров.

Все наследники ImageRenderError перехватываются хендлерами для
graceful degradation к текстовому рендеру (раздел 5 ТЗ v2.2).
"""


class ImageRenderError(Exception):
    """Базовая ошибка генерации постеров."""


class RendererUnavailableError(ImageRenderError):
    """Браузер не запущен или упал и не смог перезапуститься."""


class RenderTimeoutError(ImageRenderError):
    """Рендер не уложился в бюджет времени (очередь + скриншот)."""


class QueueOverflowError(ImageRenderError):
    """Очередь рендера переполнена — запрос отклонён без ожидания."""
