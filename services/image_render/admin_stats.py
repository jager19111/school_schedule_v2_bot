"""Админское представление статистики ImageGenerationService."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ImageStatsView:
    """Снимок runtime-счётчиков без доступа хендлера к сервису рендера."""

    renders: int
    cache_hits: int
    inflight_joins: int
    rate_limited: int
    queue_rejections: int
    timeouts: int
    breaker_rejections: int
    render_errors: int
    cache_bytes_entries: int
    cache_file_id_entries: int

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, int], *, cache_bytes_entries: int = 0, cache_file_id_entries: int = 0) -> "ImageStatsView":
        return cls(
            renders=int(snapshot.get("renders", 0)), cache_hits=int(snapshot.get("cache_hits", 0)),
            inflight_joins=int(snapshot.get("inflight_joins", 0)), rate_limited=int(snapshot.get("rate_limited", 0)),
            queue_rejections=int(snapshot.get("queue_rejections", 0)), timeouts=int(snapshot.get("timeouts", 0)),
            breaker_rejections=int(snapshot.get("breaker_rejections", 0)), render_errors=int(snapshot.get("render_errors", 0)),
            cache_bytes_entries=cache_bytes_entries, cache_file_id_entries=cache_file_id_entries,
        )


def render_image_stats(stats: ImageStatsView) -> str:
    """HTML-блок для /stats и отдельной команды /img_stats."""
    attempts = stats.renders + stats.cache_hits
    hit_ratio = stats.cache_hits / max(1, attempts) * 100
    lines = [
        "🖼 <b>ImageGenerationService</b>",
        f"Реальные рендеры: <b>{stats.renders}</b>",
        f"Попадания в L1-кэш: <b>{stats.cache_hits}</b> ({hit_ratio:.1f}%)",
        f"Single-flight присоединений: <b>{stats.inflight_joins}</b>",
        f"Rate limit отказов: <b>{stats.rate_limited}</b>",
        f"Отказов очереди: <b>{stats.queue_rejections}</b>",
        f"Таймаутов: <b>{stats.timeouts}</b>",
        f"Circuit breaker отказов: <b>{stats.breaker_rejections}</b>",
        f"Ошибок рендера: <b>{stats.render_errors}</b>",
        f"Записей PNG-кэша: <b>{stats.cache_bytes_entries}</b>",
        f"Записей file_id-кэша: <b>{stats.cache_file_id_entries}</b>",
    ]
    return "\n".join(lines)
