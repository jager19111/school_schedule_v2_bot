"""CI-контракт слоя рендера постеров — без браузера.

Проверяется PillowRenderer и общий контракт RendererPort;
Playwright-тесты требуют установленного Chromium и выполняются
локально (браузер в CI не ставится).
"""

import asyncio
import io

from PIL import Image

from services.image_render.models import (
    LessonStatus,
    PosterLessonCard,
    PosterRequest,
    RenderedPoster,
)
from services.image_render.pillow_renderer import PillowRenderer
from services.image_render.port import RendererPort


def _sample_request() -> PosterRequest:
    lessons = (
        PosterLessonCard(
            num="1", time_start="08:15", time_end="09:00",
            subject="Математика", teacher="Иванова А.П.", room="205",
            status=LessonStatus.NORMAL,
        ),
        PosterLessonCard(
            num="2", time_start="09:10", time_end="09:55",
            subject="Физкультура", original_subject="Математика",
            status=LessonStatus.EXCHANGE,
        ),
        PosterLessonCard(
            num="3", time_start="10:05", time_end="10:50",
            subject="Музыка", status=LessonStatus.CANCELLED,
        ),
        PosterLessonCard(
            num="Доп.", time_start="15:00", time_end="16:00",
            subject="Робототехника", room="112", status=LessonStatus.EXTRA,
        ),
    )
    return PosterRequest(
        request_id="img_test_1",
        date_text="Понедельник, 21.09",
        title="Расписание · 5А",
        subtitle="Иван · Группа 1",
        lessons=lessons,
        changes_count=2,
    )


def test_both_renderers_implement_port() -> None:
    """Абстракция порта обязана покрывать обе реализации (правило этапа 1)."""
    from services.image_render.playwright_renderer import PlaywrightRenderer

    assert issubclass(PillowRenderer, RendererPort)
    assert issubclass(PlaywrightRenderer, RendererPort)


def test_pillow_renderer_produces_valid_png() -> None:
    async def scenario() -> RenderedPoster:
        renderer = PillowRenderer()
        await renderer.startup()
        try:
            return await renderer.render(_sample_request())
        finally:
            await renderer.shutdown()

    poster = asyncio.run(scenario())
    image = Image.open(io.BytesIO(poster.png_bytes))
    assert image.format == "PNG"
    assert image.width == poster.width == 1080
    assert poster.height > 0
    assert poster.request_id == "img_test_1"


def test_pillow_renderer_is_deterministic() -> None:
    """Одинаковый запрос -> одинаковые габариты (основа кэширования)."""

    async def render_once() -> RenderedPoster:
        return await PillowRenderer().render(_sample_request())

    first = asyncio.run(render_once())
    second = asyncio.run(render_once())
    assert (first.width, first.height) == (second.width, second.height)


def test_settings_validation_rejects_bad_engine() -> None:
    from services.image_render.settings import ImageRenderSettings

    try:
        ImageRenderSettings(engine="skia").validate()
    except ValueError:
        return
    raise AssertionError("validate() должен отклонять неизвестный движок")
