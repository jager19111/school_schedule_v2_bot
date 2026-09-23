"""CI-тесты метрик этапа 5: перцентили латентности и раздельный лимит L2."""

import asyncio

from services.image_render.metrics import LatencyTracker
from services.image_render.models import PosterRequest, RenderedPoster
from services.image_render.port import RendererPort
from services.image_render.service import ImageGenerationService
from services.image_render.settings import ImageRenderSettings


def _request(request_id: str) -> PosterRequest:
    return PosterRequest(
        request_id=request_id,
        date_text="Понедельник, 21.09",
        title="Расписание · 5А",
        lessons=(),
    )


class _TimedRenderer(RendererPort):
    """Рендерер с фиксированной задержкой — детерминированные замеры."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.calls = 0

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def is_healthy(self) -> bool:
        return True

    async def render(self, request: PosterRequest) -> RenderedPoster:
        self.calls += 1
        await asyncio.sleep(self.delay)
        return RenderedPoster(
            request_id=request.request_id,
            png_bytes=b"\x89PNG-metrics",
            width=request.width,
            height=100,
        )


def test_latency_tracker_percentiles() -> None:
    tracker = LatencyTracker()
    assert tracker.percentiles() is None

    for value in range(1, 101):  # 0.001..0.100 сек
        tracker.record(value / 1000)

    percentiles = tracker.percentiles()
    assert percentiles is not None
    assert percentiles["count"] == 100
    assert percentiles["p50_ms"] == 50.0
    assert percentiles["max_ms"] == 100.0
    assert percentiles["p50_ms"] <= percentiles["p95_ms"] <= percentiles["p99_ms"] <= percentiles["max_ms"]

    tracker.record(-0.5)  # отрицательные замеры игнорируются
    assert tracker.percentiles()["count"] == 100


def test_latency_tracker_keeps_last_n_samples() -> None:
    tracker = LatencyTracker(maxlen=10)
    for value in range(1, 21):  # 20 замеров, буфер на 10
        tracker.record(value / 1000)
    percentiles = tracker.percentiles()
    assert percentiles is not None
    assert percentiles["count"] == 10
    assert percentiles["max_ms"] == 20.0  # выжили только последние


def test_service_records_queue_and_render_latency() -> None:
    async def scenario() -> None:
        settings = ImageRenderSettings(concurrency=1, render_timeout_sec=5.0)
        service = ImageGenerationService(_TimedRenderer(delay=0.05), settings)

        await service.get_poster(_request("m1"), user_id=1)
        await service.get_poster(_request("m2"), user_id=1)

        state = service.snapshot()
        render_time = state["render_time"]
        queue_wait = state["queue_wait"]

        assert render_time is not None
        assert render_time["count"] == 2
        # Рендер со sleep(0.05): p50 не может быть заметно меньше 50 мс
        assert render_time["p50_ms"] >= 45.0

        assert queue_wait is not None
        assert queue_wait["count"] == 2

    asyncio.run(scenario())


def test_file_id_cache_has_separate_limit() -> None:
    async def scenario() -> None:
        settings = ImageRenderSettings(cache_maxsize=100, file_id_cache_maxsize=1)
        service = ImageGenerationService(_TimedRenderer(delay=0.0), settings)

        service.store_file_id("img_a", "FID_A")
        service.store_file_id("img_b", "FID_B")

        # Лимит L2 = 1: вторая запись вытеснила первую
        assert service.get_file_id("img_a") is None
        assert service.get_file_id("img_b") == "FID_B"

    asyncio.run(scenario())
