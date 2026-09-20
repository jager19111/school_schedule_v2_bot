"""Fallback-движок без браузера: чистый Pillow, для слабых серверов.

Стадия 1 — каркас: карточки с базовой типографикой и цветовым
кодированием статусов (левая полоса). Финальная доводка дизайна — этап 5.

Назначение на этом этапе — доказать, что RendererPort действительно
абстрагирует обе реализации, а не подогнан постфактум под Playwright:
подушка принимает те же PosterRequest и возвращает те же RenderedPoster.
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageDraw, ImageFont

from services.image_render.models import (
    LessonStatus,
    PosterLessonCard,
    PosterRequest,
    RenderedPoster,
)
from services.image_render.port import RendererPort

logger = logging.getLogger(__name__)

# Цвета левой границы карточки — синхронизированы с авторским дизайном
# из services/image_render/templates/schedule_poster.html.j2 (раздел 6 ТЗ).
STATUS_COLORS: dict[LessonStatus, tuple[int, int, int]] = {
    LessonStatus.NORMAL: (49, 130, 206),       # #3182ce — синий
    LessonStatus.EXCHANGE: (229, 62, 62),      # #e53e3e — красный
    LessonStatus.CANCELLED: (203, 213, 224),    # #cbd5e0 — серый
    LessonStatus.EXTRA: (128, 90, 213),         # #805ad5 — фиолетовый
    LessonStatus.METHODICAL: (221, 107, 32),    # #dd6b20 — оранжевый
}

# Красная линия зачёркивания отменённого урока — как в CSS-шаблоне.
_STRIKE_COLOR = (229, 62, 62)  # #e53e3e

_BG = (244, 246, 249)
_CARD_BG = (255, 255, 255)
_HEADER_BG = (26, 54, 93)      # #1a365d
_TEXT = (45, 55, 72)
_MUTED = (113, 128, 150)

_HEADER_HEIGHT = 240
_CARD_HEIGHT = 130
_CARD_MARGIN = 9
_BOTTOM_PADDING = 48


def _load_font(size: int):
    """Локальный шрифт без сетевых загрузок; fallback — встроенный PIL."""
    for candidate in ("Inter.ttf", "DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


class PillowRenderer(RendererPort):
    """Рендер постера средствами Pillow. Браузер и Playwright не нужны."""

    def __init__(self) -> None:
        self._font_title = _load_font(52)
        self._font_date = _load_font(32)
        self._font_subject = _load_font(40)
        self._font_meta = _load_font(28)

    async def startup(self) -> None:
        return None  # ресурсов с ленивой инициализацией нет

    async def shutdown(self) -> None:
        return None  # нечего освобождать

    async def is_healthy(self) -> bool:
        return True  # браузера нет — падать нечему

    async def render(self, request: PosterRequest) -> RenderedPoster:
        width = request.width
        card_rows = max(1, len(request.lessons))
        height = _HEADER_HEIGHT + card_rows * _CARD_HEIGHT + _BOTTOM_PADDING
        image = Image.new("RGB", (width, height), _BG)
        draw = ImageDraw.Draw(image)

        # Шапка в стиле авторского дизайна: тёмно-синий блок
        draw.rounded_rectangle((40, 40, width - 40, 190), radius=26, fill=_HEADER_BG)
        title = f"\U0001F4C5 {request.title}"
        if request.changes_count:
            title = f"{title}   \u26A0\uFE0F {request.changes_count}"
        draw.text((76, 66), title, font=self._font_title, fill=(255, 255, 255))
        if request.subtitle:
            draw.text((76, 134), f"\U0001F464 {request.subtitle}", font=self._font_date, fill=(160, 174, 192))

        # Карточки уроков
        y = _HEADER_HEIGHT
        for lesson in request.lessons:
            self._draw_card(draw, width, y, lesson)
            y += _CARD_HEIGHT

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        logger.debug(
            "Постер %s отрендерен (pillow): %dx%d",
            request.request_id,
            width,
            image.height,
        )
        return RenderedPoster(
            request_id=request.request_id,
            png_bytes=buffer.getvalue(),
            width=width,
            height=image.height,
        )

    def _draw_card(
        self,
        draw: ImageDraw.ImageDraw,
        width: int,
        y: int,
        lesson: PosterLessonCard,
    ) -> None:
        """Одна карточка: полоса статуса, время столбиком, предмет, метаданные."""
        top = y + _CARD_MARGIN
        bottom = y + _CARD_HEIGHT - _CARD_MARGIN
        draw.rounded_rectangle((40, top, width - 40, bottom), radius=20, fill=_CARD_BG)
        draw.rectangle((40, top, 52, bottom), fill=STATUS_COLORS[lesson.status])

        # Время вертикально в левой колонке (раздел 6 ТЗ)
        draw.text((84, top + 20), lesson.time_start, font=self._font_meta, fill=_TEXT)
        draw.text((84, top + 52), lesson.time_end, font=self._font_meta, fill=_MUTED)
        num_label = "Доп." if lesson.status is LessonStatus.EXTRA else f"урок {lesson.num}"
        draw.text((84, top + 84), num_label, font=self._font_meta, fill=(203, 213, 224))

        subject_x = 320
        subject_y = top + 22
        subject = lesson.subject or lesson.original_subject or "Урок"
        if lesson.status is LessonStatus.CANCELLED:
            # Серый предмет с КРАСНЫМ зачёркиванием — как в CSS-шаблоне
            draw.text((subject_x, subject_y), subject, font=self._font_subject, fill=_MUTED)
            bbox = draw.textbbox((subject_x, subject_y), subject, font=self._font_subject)
            draw.line(
                (bbox[0], subject_y + 34, bbox[2], subject_y + 34),
                fill=_STRIKE_COLOR,
                width=4,
            )
            draw.text(
                (subject_x, subject_y + 56),
                "Отменено",
                font=self._font_meta,
                fill=_STRIKE_COLOR,
            )
        else:
            draw.text((subject_x, subject_y), subject, font=self._font_subject, fill=_TEXT)

            # Учитель курсивом под предметом (имитация курсива — этап 5)
            meta_parts = [
                part
                for part in (
                    lesson.teacher,
                    lesson.group,
                )
                if part
            ]
            if meta_parts:
                draw.text(
                    (subject_x, subject_y + 58),
                    " · ".join(meta_parts),
                    font=self._font_meta,
                    fill=_MUTED,
                )
