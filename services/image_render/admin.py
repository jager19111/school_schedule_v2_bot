"""Статистика ImageGenerationService для админских хендлеров."""

from __future__ import annotations

from services.image_render.admin_stats import ImageStatsView
from services.image_render.service import ImageGenerationService


def get_image_stats_view(service: ImageGenerationService) -> ImageStatsView:
    """Строит DTO, не раскрывая внутренние структуры сервиса хендлеру."""
    stats = service.stats()
    return ImageStatsView.from_snapshot(
        stats.snapshot(),
        cache_bytes_entries=service.bytes_cache_size,
        cache_file_id_entries=service.file_id_cache_size,
    )
