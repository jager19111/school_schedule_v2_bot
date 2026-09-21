"""Тесты представления статистики рендера."""

from services.image_render.admin_stats import ImageStatsView, render_image_stats


def test_render_image_stats_contains_all_counters() -> None:
    view = ImageStatsView.from_snapshot({"renders": 4, "cache_hits": 16, "inflight_joins": 3, "rate_limited": 2, "queue_rejections": 1, "timeouts": 5, "breaker_rejections": 6, "render_errors": 7}, cache_bytes_entries=8, cache_file_id_entries=9)
    text = render_image_stats(view)
    assert "ImageGenerationService" in text
    assert "Реальные рендеры: <b>4</b>" in text
    assert "Попадания в L1-кэш: <b>16</b>" in text
    assert "Записей file_id-кэша: <b>9</b>" in text


def test_render_image_stats_handles_zero_activity() -> None:
    text = render_image_stats(ImageStatsView.from_snapshot({}))
    assert "0.0%" in text
