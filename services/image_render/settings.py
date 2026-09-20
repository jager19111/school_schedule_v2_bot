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
