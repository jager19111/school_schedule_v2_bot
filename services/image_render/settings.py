"""Настройки слоя рендера. Строится из config.py (значения из .env)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImageRenderSettings:
    engine: str = "playwright"                # "playwright" | "pillow"
    poster_width: int = 1080                  # переживает JPEG-компрессию Telegram
    concurrency: int = 2                       # semaphore: пик RAM ~900 МБ при 2 контекстах
    queue_capacity: int = 3                   # сверх — отказ вместо бесконечного ожидания
    render_timeout_sec: float = 4.0           # общий бюджет: ожидание слота + рендер
    browser_recycle_renders: int = 200        # плановый рецикл по счётчику рендеров
    browser_recycle_interval_min: int = 720   # ...и по возрасту процесса (12 ч)
    rate_limit_max: int = 10                  # генераций на пользователя...
    rate_limit_window_sec: float = 180.0      # ...за 3 минуты (только фактические рендеры)
    cache_ttl_sec: float = 86400.0            # L1/L2: TTL записей (24 ч)
    cache_maxsize: int = 200                  # L1/L2: предел числа записей
    breaker_failure_threshold: int = 5       # серия ошибок до размыкания цепи
    breaker_cooldown_sec: float = 120.0       # пауза перед пробной попыткой (half-open)

    def validate(self) -> None:
        if self.engine not in ("playwright", "pillow"):
            raise ValueError(f"Неизвестный движок рендера: {self.engine!r}")
        if self.concurrency < 1:
            raise ValueError("concurrency должен быть >= 1")
        if self.queue_capacity < 0:
            raise ValueError("queue_capacity не может быть отрицательной")
        if self.render_timeout_sec <= 0:
            raise ValueError("render_timeout_sec должен быть > 0")
        if self.poster_width < 320:
            raise ValueError("poster_width слишком мал")
        if self.rate_limit_max < 1:
            raise ValueError("rate_limit_max должен быть >= 1")
        if self.rate_limit_window_sec <= 0:
            raise ValueError("rate_limit_window_sec должен быть > 0")
        if self.cache_ttl_sec <= 0:
            raise ValueError("cache_ttl_sec должен быть > 0")
        if self.cache_maxsize < 1:
            raise ValueError("cache_maxsize должен быть >= 1")
        if self.breaker_failure_threshold < 1:
            raise ValueError("breaker_failure_threshold должен быть >= 1")
        if self.breaker_cooldown_sec <= 0:
            raise ValueError("breaker_cooldown_sec должен быть > 0")
