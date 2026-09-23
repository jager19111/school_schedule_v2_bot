"""Замеры латентности рендера для калибровки констант (этап 5 ТЗ v2.2).

Зачем: значения IMAGE_RENDER_TIMEOUT_SEC / IMAGE_MAX_CONCURRENT_RENDERS /
IMAGE_QUEUE_CAPACITY должны опираться на фактические перцентили, а не на
интуицию. LatencyTracker пишет последние N замеров и отдаёт p50/p95/p99/max
для /img_stats.
"""

from __future__ import annotations

from collections import deque


class LatencyTracker:
    """Кольцевой буфер последних N замеров + перцентили.

    Не потокобезопасен — вызывается только из event loop бота.
    Хранит секунды, отдаёт миллисекунды (удобнее читать в /img_stats).
    """

    def __init__(self, maxlen: int = 200) -> None:
        self._samples: deque[float] = deque(maxlen=maxlen)

    def record(self, seconds: float) -> None:
        """Добавляет замер; отрицательные значения игнорируются."""
        if seconds >= 0:
            self._samples.append(seconds)

    def percentiles(self) -> dict[str, float] | None:
        """p50/p95/p99/max в мс; None — замеров ещё не было."""
        if not self._samples:
            return None
        ordered = sorted(self._samples)

        def percentile(fraction: float) -> float:
            index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
            return ordered[index]

        return {
            "count": len(ordered),
            "p50_ms": percentile(0.50) * 1000,
            "p95_ms": percentile(0.95) * 1000,
            "p99_ms": percentile(0.99) * 1000,
            "max_ms": ordered[-1] * 1000,
        }
