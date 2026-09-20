import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

# Загрузка переменных окружения из .env
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)


@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    DB_PATH: str = os.getenv("DB_PATH", "schedule_bot.db")
    # Если закомментировано или пусто — будет строго None
    PROXY_URL: Optional[str] = os.getenv("PROXY_URL", "").strip() or None
    NIKA_BASE_URL: str = (
        os.getenv("NIKA_BASE_URL", "https://lyceum.nstu.ru/rasp").strip().rstrip("/")
    )
    
    # Отпечаток сертификата для Certificate Pinning
    NIKA_TLS_FINGERPRINT_SHA256: Optional[str] = (
        os.getenv("NIKA_TLS_FINGERPRINT_SHA256", "").strip().lower().replace(":", "")
        or None
    )
    NIKA_REFRESH_INTERVAL_MINUTES: int = int(
        os.getenv("NIKA_REFRESH_INTERVAL_MINUTES", "5")
    )
    NIKA_COVERAGE_DAYS: int = int(os.getenv("NIKA_COVERAGE_DAYS", "21"))
    NIKA_HISTORY_DAYS: int = int(os.getenv("NIKA_HISTORY_DAYS", "7"))
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Novosibirsk")
    ADMIN_IDS: List[int] = field(
        default_factory=lambda: [
            int(x)
            for x in os.getenv("ADMIN_IDS", "").split(",")
            if x.strip()
        ]
    )

    # === Генерация постеров (ТЗ v2.2, ImageGenerationService) ===
    # Глобальный рубильник: False = весь бот бесшовно в текстовом режиме.
    ENABLE_IMAGE_GENERATION: bool = os.getenv(
        "ENABLE_IMAGE_GENERATION", "True"
    ).strip().lower() in ("1", "true", "yes", "on")
    # playwright | pillow (pillow — fallback для слабых серверов без Chromium).
    IMAGE_RENDER_ENGINE: str = os.getenv("IMAGE_RENDER_ENGINE", "playwright").strip().lower()
    # Semaphore: 2 = пик RAM ~900 МБ при 3.5 ГБ свободных.
    IMAGE_MAX_CONCURRENT_RENDERS: int = int(os.getenv("IMAGE_MAX_CONCURRENT_RENDERS", "2"))
    # Максимум ждущих в очереди; сверх — мгновенный текстовый fallback.
    IMAGE_QUEUE_CAPACITY: int = int(os.getenv("IMAGE_QUEUE_CAPACITY", "3"))
    # Общий бюджет запроса: ожидание слота + рендер, секунды.
    IMAGE_RENDER_TIMEOUT_SEC: float = float(os.getenv("IMAGE_RENDER_TIMEOUT_SEC", "4.0"))
    # Рецикл браузера: не более N рендеров на процесс...
    IMAGE_BROWSER_RECYCLE_RENDERS: int = int(os.getenv("IMAGE_BROWSER_RECYCLE_RENDERS", "200"))
    # ...и не старше N минут (что наступит раньше).
    IMAGE_BROWSER_RECYCLE_INTERVAL_MIN: int = int(os.getenv("IMAGE_BROWSER_RECYCLE_INTERVAL_MIN", "720"))
    # Ширина постера, px: 1080 переживает JPEG-компрессию Telegram.
    POSTER_WIDTH: int = int(os.getenv("POSTER_WIDTH", "1080"))

    HELP_PUBLIC_URL = os.getenv("HELP_PUBLIC_URL", "").strip() or None
    AUTHOR_CONTACT_URL = os.getenv("AUTHOR_CONTACT_URL", "").strip() or None
    DONATION_URL = os.getenv("DONATION_URL", "").strip() or None


config = Config()


def validate_config(config: Config) -> None:
    if not config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env")

    if config.IMAGE_RENDER_ENGINE not in ("playwright", "pillow"):
        raise ValueError(
            "IMAGE_RENDER_ENGINE должен быть 'playwright' или 'pillow', "
            f"получено: {config.IMAGE_RENDER_ENGINE!r}"
        )
    if config.ENABLE_IMAGE_GENERATION and config.IMAGE_MAX_CONCURRENT_RENDERS < 1:
        raise ValueError("IMAGE_MAX_CONCURRENT_RENDERS должен быть >= 1")
    if config.IMAGE_RENDER_TIMEOUT_SEC <= 0:
        raise ValueError("IMAGE_RENDER_TIMEOUT_SEC должен быть > 0")


def build_image_render_settings():
    """Собирает настройки слоя рендера из Config (DI-точка для main.py, этап 3)."""
    from services.image_render.settings import ImageRenderSettings

    return ImageRenderSettings(
        engine=config.IMAGE_RENDER_ENGINE,
        poster_width=config.POSTER_WIDTH,
        concurrency=config.IMAGE_MAX_CONCURRENT_RENDERS,
        queue_capacity=config.IMAGE_QUEUE_CAPACITY,
        render_timeout_sec=config.IMAGE_RENDER_TIMEOUT_SEC,
        browser_recycle_renders=config.IMAGE_BROWSER_RECYCLE_RENDERS,
        browser_recycle_interval_min=config.IMAGE_BROWSER_RECYCLE_INTERVAL_MIN,
    )
