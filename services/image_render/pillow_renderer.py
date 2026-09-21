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
from services.image_render.models import LessonStatus, PosterLessonCard, PosterRequest, RenderedPoster
from services.image_render.port import RendererPort

logger = logging.getLogger(__name__)

STATUS_COLORS = {
    LessonStatus.NORMAL: (49, 130, 206),
    LessonStatus.EXCHANGE: (217, 119, 6),
    LessonStatus.CANCELLED: (229, 62, 62),
    LessonStatus.EXTRA: (128, 90, 213),
    LessonStatus.METHODICAL: (113, 128, 150),
}
_STRIKE_COLOR = (229, 62, 62)
_BG = (244, 246, 249)
_CARD_BG = (255, 255, 255)
_HEADER_BG = (26, 54, 93)
_TEXT = (45, 55, 72)
_MUTED = (113, 128, 150)

def _load_font(size: int):
    for candidate in ("Inter.ttf", "DejaVuSans.ttf", "Arial.ttf"):
        try: return ImageFont.truetype(candidate, size)
        except OSError: continue
    return ImageFont.load_default()

class PillowRenderer(RendererPort):
    def __init__(self) -> None:
        self._font_title = _load_font(52)
        self._font_date = _load_font(32)
        self._font_subject = _load_font(40)
        self._font_meta = _load_font(28)

    async def startup(self) -> None: pass
    async def shutdown(self) -> None: pass
    async def is_healthy(self) -> bool: return True

    async def render(self, request: PosterRequest) -> RenderedPoster:
        width = request.width
        card_rows = max(1, sum(max(1, len(l.items)) for l in request.lessons))
        height = 240 + card_rows * 130 + 48
        image = Image.new("RGB", (width, height), _BG)
        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle((40, 40, width - 40, 190), radius=26, fill=_HEADER_BG)
        title = f"\U0001F4C5 {request.title}"
        if request.changes_count: title = f"{title}   \u26A0\uFE0F {request.changes_count}"
        draw.text((76, 66), title, font=self._font_title, fill=(255, 255, 255))
        if request.subtitle: draw.text((76, 134), f"\U0001F464 {request.subtitle}", font=self._font_date, fill=(160, 174, 192))

        y = 240
        for lesson in request.lessons:
            card_h = max(130, 20 + len(lesson.items) * 100)
            self._draw_card(draw, width, y, lesson, card_h)
            y += card_h + 20

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return RenderedPoster(request_id=request.request_id, png_bytes=buffer.getvalue(), width=width, height=image.height)

    def _draw_card(self, draw: ImageDraw.ImageDraw, width: int, y: int, lesson: PosterLessonCard, height: int) -> None:
        draw.rounded_rectangle((40, y, width - 40, y + height), radius=20, fill=_CARD_BG)
        draw.rectangle((40, y, 52, y + height), fill=STATUS_COLORS[lesson.status])

        draw.text((84, y + 20), lesson.time_start, font=self._font_meta, fill=_TEXT)
        draw.text((84, y + 52), lesson.time_end, font=self._font_meta, fill=_MUTED)
        
        subj_y = y + 22
        for item in lesson.items:
            subj = item.original_primary if item.is_cancelled else (item.primary_text or "")
            if item.is_cancelled:
                draw.text((320, subj_y), subj, font=self._font_subject, fill=_MUTED)
                bbox = draw.textbbox((320, subj_y), subj, font=self._font_subject)
                draw.line((bbox[0], subj_y + 34, bbox[2], subj_y + 34), fill=_STRIKE_COLOR, width=4)
            else:
                draw.text((320, subj_y), subj, font=self._font_subject, fill=_TEXT)
                if item.secondary_text:
                    draw.text((320, subj_y + 46), item.secondary_text, font=self._font_meta, fill=_MUTED)
            subj_y += 100