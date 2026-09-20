"""Fallback-движок без браузера: чистый Pillow, для слабых серверов.

Стадия 1 — каркас: карточки с базовой типографикой и цветовым
кодированием статусов (левая полоса). Финальный дизайн — этап 5.

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

# Цвета левой границы карточки — строго синхронизированы с CSS-шаблоном
# Chromium-движка (раздел 6 ТЗ v2.2).
STATUS_COLORS: dict[LessonStatus, tuple[int, int, int]] = {
    LessonStatus.NORMAL: (59, 130, 246),       # синий
    LessonStatus.EXCHANGE: (239, 68, 68),      # красный
    LessonStatus.CANCELLED: (156, 163, 175),   # серый
    LessonStatus.EXTRA: (168, 85, 247),         # фиолетовый
    LessonStatus.METHODICAL: (245, 158, 11),   # оранжевый
}

_BG = (241, 245, 249)
_CARD_BG = (255, 255, 255)
_TEXT = (15, 23, 42)
_MUTED = (100, 116, 139)

_HEADER_HEIGHT = 220
_CARD_HEIGHT = 130
_CARD_MARGIN = 9
_BOTTOM_PADDING = 48


def _load_font(size: int):
    """Локальный шрифт без сетевых загрузок; fallback — встроенный PIL."""
    for candidate in ("DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


class PillowRenderer(RendererPort):
    """Рендер постера средствами Pillow. Браузер и Playwright не нужны."""

    def __init__(self) -> None:
        self._font_title = _load_font(56)
        self._font_date = _load_font(34)
        self._font_subject = _load_font(38)
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

        # Шапка
        draw.text((64, 56), request.date_text, font=self._font_date, fill=_MUTED)
        title = request.title
        if request.changes_count:
            title = f"{title}   ⚡ {request.changes_count}"
        draw.text((64, 104), title, font=self._font_title, fill=_TEXT)
        if request.subtitle:
            draw.text((64, 176), request.subtitle, font=self._font_date, fill=_MUTED)

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
        draw.rounded_rectangle((48, top, width - 48, bottom), radius=18, fill=_CARD_BG)
        draw.rectangle((48, top, 62, bottom), fill=STATUS_COLORS[lesson.status])

        # Время вертикально в левой колонке (раздел 6 ТЗ)
        draw.text((92, top + 22), lesson.num, font=self._font_meta, fill=_MUTED)
        draw.text((92, top + 54), lesson.time_start, font=self._font_meta, fill=_TEXT)
        draw.text((92, top + 86), lesson.time_end, font=self._font_meta, fill=_MUTED)

        subject_x = 330
        subject_y = top + 24
        subject = lesson.subject or lesson.original_subject or "Урок"
        if lesson.status is LessonStatus.CANCELLED:
            # Серый зачёркнутый предмет (раздел 6 ТЗ)
            draw.text((subject_x, subject_y), subject, font=self._font_subject, fill=_MUTED)
            bbox = draw.textbbox((subject_x, subject_y), subject, font=self._font_subject)
            draw.line(
                (bbox[0], subject_y + 32, bbox[2], subject_y + 32),
                fill=_MUTED,
                width=4,
            )
        else:
            draw.text((subject_x, subject_y), subject, font=self._font_subject, fill=_TEXT)

        # Учитель/кабинет/группа серым под предметом (имитация курсива — этап 5)
        meta_parts = [
            part
            for part in (
                lesson.teacher,
                f"каб. {lesson.room}" if lesson.room else None,
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
