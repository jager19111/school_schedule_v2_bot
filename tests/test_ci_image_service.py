"""CI-тесты ImageGenerationService — без браузера (FakeRenderer).

Проверяются: кэш L1, single-flight, rate limit (только на фактические
рендеры; системные вызовы мимо), кап очереди, общий таймаут,
circuit breaker, L2 file_id, фабрика PosterRequest и версионированные
ключи. Playwright не нужен.
"""

import asyncio

from core.models.dto import DayScheduleDTO, LessonDTO
from services.image_render.exceptions import (
    ImageRenderError,
    QueueOverflowError,
    RateLimitExceededError,
    RenderTimeoutError,
    RendererUnavailableError,
)
from services.image_render.models import LessonStatus, PosterRequest, RenderedPoster
from services.image_render.port import RendererPort
from services.image_render.poster_factory import (
    build_global_request_id,
    build_personal_request_id,
    build_poster_request,
    extra_classes_hash,
)
from services.image_render.service import ImageGenerationService
from services.image_render.settings import ImageRenderSettings


class FakeRenderer(RendererPort):
    """Детерминированная заглушка движка: задержка и/или гарантированный сбой."""

    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.calls = 0

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def is_healthy(self) -> bool:
        return True

    async def render(self, request: PosterRequest) -> RenderedPoster:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ImageRenderError("движок сломан (тест)")
        return RenderedPoster(
            request_id=request.request_id,
            png_bytes=b"\x89PNG-test",
            width=request.width,
            height=100 + self.calls,
        )


def _request(request_id: str) -> PosterRequest:
    return PosterRequest(
        request_id=request_id,
        date_text="Понедельник, 21.09",
        title="Расписание · 5А",
        lessons=(),
    )


def test_cache_hit_skips_render() -> None:
    async def scenario() -> None:
        renderer = FakeRenderer()
        svc = ImageGenerationService(renderer, ImageRenderSettings())
        first = await svc.get_poster(_request("a"), user_id=1)
        second = await svc.get_poster(_request("a"), user_id=2)
        assert renderer.calls == 1
        assert first.png_bytes == second.png_bytes
        assert svc.stats().cache_hits == 1

    asyncio.run(scenario())


def test_single_flight_deduplicates_concurrent_requests() -> None:
    async def scenario() -> None:
        renderer = FakeRenderer(delay=0.1)
        svc = ImageGenerationService(renderer, ImageRenderSettings())
        request = _request("shared")
        results = await asyncio.gather(
            *(svc.get_poster(request, user_id=uid) for uid in range(5))
        )
        assert renderer.calls == 1
        assert len({result.png_bytes for result in results}) == 1
        assert svc.stats().inflight_joins == 4

    asyncio.run(scenario())


def test_rate_limit_only_consumed_on_real_render() -> None:
    async def scenario() -> None:
        renderer = FakeRenderer()
        settings = ImageRenderSettings(rate_limit_max=3, rate_limit_window_sec=60.0)
        svc = ImageGenerationService(renderer, settings)

        for i in range(3):
            await svc.get_poster(_request(f"r{i}"), user_id=42)

        # Кэш-хит лимит не расходует
        await svc.get_poster(_request("r0"), user_id=42)

        # 4-й уникальный рендер — отказ
        try:
            await svc.get_poster(_request("r_new"), user_id=42)
        except RateLimitExceededError:
            pass
        else:
            raise AssertionError("ожидали RateLimitExceededError")

        # Системный вызов (warm-up) идёт мимо per-user лимита
        poster = await svc.get_poster(_request("r_system"), user_id=None)
        assert poster.request_id == "r_system"
        assert svc.stats().rate_limited == 1

    asyncio.run(scenario())


def test_queue_overflow_rejects_without_waiting() -> None:
    async def scenario() -> None:
        renderer = FakeRenderer(delay=0.2)
        settings = ImageRenderSettings(
            concurrency=1, queue_capacity=1, render_timeout_sec=5.0
        )
        svc = ImageGenerationService(renderer, settings)

        first = asyncio.create_task(svc.get_poster(_request("a"), user_id=1))
        await asyncio.sleep(0.05)  # первый рендер стартовал и занял semaphore

        try:
            await svc.get_poster(_request("b"), user_id=2)
        except QueueOverflowError:
            pass
        else:
            raise AssertionError("ожидали QueueOverflowError")

        poster = await first
        assert poster.request_id == "a"
        assert svc.stats().queue_rejections == 1

    asyncio.run(scenario())


def test_total_timeout_covers_queue_and_render() -> None:
    async def scenario() -> None:
        renderer = FakeRenderer(delay=0.5)
        settings = ImageRenderSettings(render_timeout_sec=0.05)
        svc = ImageGenerationService(renderer, settings)
        try:
            await svc.get_poster(_request("slow"), user_id=1)
        except RenderTimeoutError:
            pass
        else:
            raise AssertionError("ожидали RenderTimeoutError")
        assert svc.stats().timeouts == 1

    asyncio.run(scenario())


def test_circuit_breaker_opens_after_failure_series() -> None:
    async def scenario() -> None:
        renderer = FakeRenderer(fail=True)
        settings = ImageRenderSettings(breaker_failure_threshold=3, breaker_cooldown_sec=60.0)
        svc = ImageGenerationService(renderer, settings)

        for i in range(3):
            try:
                await svc.get_poster(_request(f"f{i}"), user_id=1)
            except ImageRenderError:
                pass

        # Цепь разомкнута: отказ мгновенный, без новой попытки рендера
        assert renderer.calls == 3
        try:
            await svc.get_poster(_request("f_after"), user_id=1)
        except RendererUnavailableError:
            pass
        else:
            raise AssertionError("ожидали RendererUnavailableError (breaker open)")
        assert renderer.calls == 3  # рендер не вызывался
        assert svc.stats().breaker_rejections == 1

    asyncio.run(scenario())


def test_file_id_cache_store_get_invalidate() -> None:
    async def scenario() -> None:
        svc = ImageGenerationService(FakeRenderer(), ImageRenderSettings())
        assert svc.get_file_id("img_x") is None
        svc.store_file_id("img_x", "AgAC-file-id")
        assert svc.get_file_id("img_x") == "AgAC-file-id"
        svc.invalidate_file_id("img_x")
        assert svc.get_file_id("img_x") is None

    asyncio.run(scenario())


def test_poster_factory_maps_dto_statuses() -> None:
    dto = DayScheduleDTO(
        date_iso="2026-09-21",
        lessons=[
            LessonDTO(
                lesson_num=1, start_time="08:15", end_time="09:00",
                subject_name="Математика", room_name="205", teacher_name="Иванова А.П.",
            ),
            LessonDTO(
                lesson_num=2, start_time="09:10", end_time="09:55",
                subject_name="Физкультура", is_exchange=True,
                original_subject_name="Математика",
            ),
            LessonDTO(
                lesson_num=3, start_time="10:05", end_time="10:50",
                subject_name="Музыка", is_cancelled=True,
                original_subject_name="Музыка",
            ),
            LessonDTO(
                start_time="15:00", end_time="16:00",
                subject_name="Робототехника", is_extra=True,
            ),
        ],
    )
    request = build_poster_request(
        request_id="img_test",
        dto=dto,
        title="Расписание · 5А",
        date_text="Понедельник, 21.09",
        subtitle="Иван",
    )
    statuses = [card.status for card in request.lessons]
    assert statuses == [
        LessonStatus.NORMAL,
        LessonStatus.EXCHANGE,
        LessonStatus.CANCELLED,
        LessonStatus.EXTRA,
    ]
    assert request.lessons[3].num == "Доп."
    
    # ИСПРАВЛЕНИЕ: У замены (EXCHANGE) нет зачеркивания в PosterItem, поэтому None
    assert request.lessons[1].items[0].primary_text == "Физкультура"
    assert request.lessons[1].items[0].original_primary is None
    
    # ИСПРАВЛЕНИЕ: А вот у отмены (CANCELLED) зачеркивание есть
    assert request.lessons[2].items[0].original_primary == "Музыка"
    
    assert request.changes_count == 2


def test_request_ids_are_versioned() -> None:
    version_1 = build_global_request_id(1, "016", "ALL", "2026-09-21")
    version_2 = build_global_request_id(2, "016", "ALL", "2026-09-21")
    personal = build_personal_request_id(1, 42, "2026-09-21", "abc123")
    assert version_1 != version_2
    assert personal not in (version_1, version_2)


def test_extra_classes_hash_stable_and_distinct() -> None:
    class _Extra:
        def __init__(self, day: int, start: str, end: str, title: str) -> None:
            self.day_of_week = day
            self.time_start = start
            self.time_end = end
            self.title = title

    first = extra_classes_hash([_Extra(1, "15:00", "16:00", "Робототехника")])
    same = extra_classes_hash([_Extra(1, "15:00", "16:00", "Робототехника")])
    other = extra_classes_hash([_Extra(2, "15:00", "16:00", "Робототехника")])
    assert first == same
    assert first != other
    assert extra_classes_hash([]) == "noextra"
