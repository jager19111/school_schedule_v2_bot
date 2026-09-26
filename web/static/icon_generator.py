"""Генерирует PWA PNG icons без сетевых зависимостей.

Запуск из корня проекта:
    python scripts/generate_pwa_icons.py

Создаёт:
  web/static/icons/icon-192.png
  web/static/icons/icon-512.png
  web/static/icons/icon-maskable-512.png
  web/static/icons/apple-touch-icon.png

Pillow уже есть в большинстве окружений; иначе:
    pip install Pillow
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "web" / "static" / "icons"
BLUE = "#1a56db"
WHITE = "#ffffff"
LIGHT = "#dbeafe"


def font(size: int):
    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def draw_icon(size: int, *, maskable: bool = False) -> Image.Image:
    image = Image.new("RGB", (size, size), BLUE)
    draw = ImageDraw.Draw(image)
    margin = int(size * (0.20 if maskable else 0.13))
    card = (margin, margin, size - margin, size - margin)
    radius = int(size * 0.08)
    draw.rounded_rectangle(card, radius=radius, fill=WHITE)

    # Верхняя синяя полоса календаря.
    header_h = int(size * 0.19)
    draw.rounded_rectangle(
        (margin, margin, size - margin, margin + header_h),
        radius=radius, fill=BLUE,
    )
    # Внутренняя белая линия делает header визуально ровным.
    draw.rectangle((margin, margin + header_h - radius, size - margin, margin + header_h), fill=BLUE)

    # Две крепёжные точки календаря.
    ring_r = max(2, int(size * 0.025))
    for x in (int(size * .35), int(size * .65)):
        draw.ellipse((x-ring_r, margin-ring_r, x+ring_r, margin+ring_r), fill=LIGHT)

    # Число 24 — нейтральная ассоциация с расписанием, без персональных данных.
    label = "24"
    f = font(int(size * .36))
    box = draw.textbbox((0, 0), label, font=f)
    x = (size - (box[2] - box[0])) // 2
    y = int(size * .42)
    draw.text((x, y), label, font=f, fill=BLUE)
    return image


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw_icon(192).save(OUT / "icon-192.png", optimize=True)
    draw_icon(512).save(OUT / "icon-512.png", optimize=True)
    draw_icon(512, maskable=True).save(OUT / "icon-maskable-512.png", optimize=True)
    draw_icon(180).save(OUT / "apple-touch-icon.png", optimize=True)
    print("PWA icons generated:", OUT)


if __name__ == "__main__":
    main()
