"""Иерархия ошибок слоя рендера постеров.

Все наследники ImageRenderError перехватываются хендлерами для
graceful degradation к текстовому рендеру (раздел 5 ТЗ v2.2).
Исключение — RateLimitExceededError: это не сбой, а осознанный
отказ с alert'ом «подождите пару минут» (раздел 4 ТЗ).
"""


class ImageRenderError(Exception):
    """Базовая ошибка генерации постеров."""


class RendererUnavailableError(ImageRenderError):
    """Браузер не запущен, упал или circuit breaker разомкнут."""


class RenderTimeoutError(ImageRenderError):
    """Рендер не уложился в общий бюджет (очередь + скриншот)."""


class QueueOverflowError(ImageRenderError):
    """Очередь рендера переполнена — запрос отклонён без ожидания."""


class RateLimitExceededError(ImageRenderError):
    """Пользователь исчерпал лимит генераций (10 за 3 минуты).

    Показывать alert, а не текстовый fallback: постер ещё может
    прийти из кэша, лимит касается только фактических рендеров.
    """
