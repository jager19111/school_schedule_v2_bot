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
    # === Backup ===
    # Если строка пустая или закомментирована — будет None (отправка отключена)
    BACKUP_CHAT_ID: Optional[int] = field(
        default_factory=lambda: int(os.getenv("BACKUP_CHAT_ID").strip()) 
        if os.getenv("BACKUP_CHAT_ID", "").strip().lstrip('-').isdigit() else None
    )
    ADMIN_IDS: List[int] = field(
        default_factory=lambda: [
            int(x)
            for x in os.getenv("ADMIN_IDS", "").split(",")
            if x.strip()
        ]
    )
    
    # === Логирование ===
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")
    
    # === Генерация постеров (ТЗ v2.2, ImageGenerationService) ===
    # Глобальный рубильник: False = весь бот бесшовно в текстовом режиме.
    ENABLE_IMAGE_GENERATION: bool = os.getenv(
        "ENABLE_IMAGE_GENERATION", "True"
    ).strip().lower() in ("1", "true", "yes", "on")
    # playwright | pillow (pillow — fallback для слабых серверов без Chromium).
    IMAGE_RENDER_ENGINE: str = os.getenv("IMAGE_RENDER_ENGINE", "playwright").strip().lower()
    # Semaphore: одновременных рендеров (RAM = N контекстов Chromium).
    IMAGE_MAX_CONCURRENT_RENDERS: int = int(os.getenv("IMAGE_MAX_CONCURRENT_RENDERS", "2"))
    # Максимум ждущих в очереди; сверх — мгновенный текстовый fallback.
    IMAGE_QUEUE_CAPACITY: int = int(os.getenv("IMAGE_QUEUE_CAPACITY", "3"))
    # Общий бюджет запроса: ожидание слота + рендер, секунды.
    # Калибровка (этап 5): p99 рендера + queue_capacity / пропускная способность.
    IMAGE_RENDER_TIMEOUT_SEC: float = float(os.getenv("IMAGE_RENDER_TIMEOUT_SEC", "4.0"))
    # Рецикл браузера: не более N рендеров на процесс...
    IMAGE_BROWSER_RECYCLE_RENDERS: int = int(os.getenv("IMAGE_BROWSER_RECYCLE_RENDERS", "200"))
    # ...и не старше N минут (что наступит раньше).
    IMAGE_BROWSER_RECYCLE_INTERVAL_MIN: int = int(os.getenv("IMAGE_BROWSER_RECYCLE_INTERVAL_MIN", "720"))
    # Ширина постера, px: 1080 переживает JPEG-компрессию Telegram.
    POSTER_WIDTH: int = int(os.getenv("POSTER_WIDTH", "1080"))
    # Rate limit: N генераций на пользователя за окно (только фактические рендеры).
    IMAGE_RATE_LIMIT_MAX: int = int(os.getenv("IMAGE_RATE_LIMIT_MAX", "10"))
    IMAGE_RATE_LIMIT_WINDOW_SEC: float = float(os.getenv("IMAGE_RATE_LIMIT_WINDOW_SEC", "180"))
    # L1 (PNG-байты, RAM ~0.1 МБ/запись) и L2 (file_id, строки) —
    # раздельные лимиты: file_id-записи почти бесплатны, байты — нет.
    IMAGE_CACHE_TTL_HOURS: float = float(os.getenv("IMAGE_CACHE_TTL_HOURS", "24"))
    IMAGE_CACHE_MAXSIZE: int = int(os.getenv("IMAGE_CACHE_MAXSIZE", "200"))
    IMAGE_FILE_ID_CACHE_MAXSIZE: int = int(os.getenv("IMAGE_FILE_ID_CACHE_MAXSIZE", "2000"))
    # Circuit breaker: серия ошибок до размыкания и пауза перед пробой.
    IMAGE_BREAKER_FAILURE_THRESHOLD: int = int(os.getenv("IMAGE_BREAKER_FAILURE_THRESHOLD", "5"))
    IMAGE_BREAKER_COOLDOWN_SEC: float = float(os.getenv("IMAGE_BREAKER_COOLDOWN_SEC", "120"))

    # --- ДОБАВЛЕНО (Phase 1: Web) ---
    WEB_ENABLED: bool = os.getenv("WEB_ENABLED", "0") == "1"
    WEB_PUBLIC_URL: str = os.getenv("WEB_PUBLIC_URL", "http://localhost:8000")
    WEB_HOST: str = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT: int = int(os.getenv("WEB_PORT", "8000"))
    WEB_TRUSTED_PROXY_IPS: str = os.getenv("WEB_TRUSTED_PROXY_IPS", "127.0.0.1")
    WEB_GATEWAY_KEY: str = os.getenv("WEB_GATEWAY_KEY", "")
    WEB_CSRF_SECRET: str = os.getenv("WEB_CSRF_SECRET", "")
    WEB_ACCESS_MODE: str = os.getenv("WEB_ACCESS_MODE", "family_allowlist")
    WEB_ALLOWED_FAMILY_IDS: str = os.getenv("WEB_ALLOWED_FAMILY_IDS", "")
    WEB_COOKIE_SECURE: bool = os.getenv("WEB_COOKIE_SECURE", "1") == "1"
    # --------------------------------

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
    """Собирает настройки слоя рендера из Config (DI-точка для main.py)."""
    from services.image_render.settings import ImageRenderSettings

    return ImageRenderSettings(
        engine=config.IMAGE_RENDER_ENGINE,
        poster_width=config.POSTER_WIDTH,
        concurrency=config.IMAGE_MAX_CONCURRENT_RENDERS,
        queue_capacity=config.IMAGE_QUEUE_CAPACITY,
        render_timeout_sec=config.IMAGE_RENDER_TIMEOUT_SEC,
        browser_recycle_renders=config.IMAGE_BROWSER_RECYCLE_RENDERS,
        browser_recycle_interval_min=config.IMAGE_BROWSER_RECYCLE_INTERVAL_MIN,
        rate_limit_max=config.IMAGE_RATE_LIMIT_MAX,
        rate_limit_window_sec=config.IMAGE_RATE_LIMIT_WINDOW_SEC,
        cache_ttl_sec=config.IMAGE_CACHE_TTL_HOURS * 3600,
        cache_maxsize=config.IMAGE_CACHE_MAXSIZE,
        file_id_cache_maxsize=config.IMAGE_FILE_ID_CACHE_MAXSIZE,
        breaker_failure_threshold=config.IMAGE_BREAKER_FAILURE_THRESHOLD,
        breaker_cooldown_sec=config.IMAGE_BREAKER_COOLDOWN_SEC,
    )