import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List
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
        os.getenv(
            "NIKA_BASE_URL",
            "https://lyceum.nstu.ru/rasp",
        )
        .strip()
        .rstrip("/")
    )
    NIKA_REFRESH_INTERVAL_MINUTES: int = int(
        os.getenv(
            "NIKA_REFRESH_INTERVAL_MINUTES",
            "5",
        )
    )

    NIKA_COVERAGE_DAYS: int = int(
        os.getenv(
            "NIKA_COVERAGE_DAYS",
            "21",
        )
    )

    NIKA_HISTORY_DAYS: int = int(
        os.getenv(
            "NIKA_HISTORY_DAYS",
            "7",
        )
    )
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Novosibirsk")
    ADMIN_IDS: List[int] = field(
        default_factory=lambda: [
            int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
        ]
    )


    HELP_PUBLIC_URL = os.getenv(
        "HELP_PUBLIC_URL",
        "",
    ).strip()

    AUTHOR_CONTACT_URL = os.getenv(
        "AUTHOR_CONTACT_URL",
        "",
    ).strip()

    DONATION_URL = os.getenv(
        "DONATION_URL",
        "",
    ).strip()

config = Config()

def validate_config(config: Config) -> None:
    if config.NIKA_REFRESH_INTERVAL_MINUTES < 1:
        raise ValueError(
            "NIKA_REFRESH_INTERVAL_MINUTES must be >= 1"
        )

    if not 1 <= config.NIKA_COVERAGE_DAYS <= 90:
        raise ValueError(
            "NIKA_COVERAGE_DAYS must be in range 1..90"
        )

    if not 0 <= config.NIKA_HISTORY_DAYS <= 90:
        raise ValueError(
            "NIKA_HISTORY_DAYS must be in range 0..90"
        )
        
validate_config(config)