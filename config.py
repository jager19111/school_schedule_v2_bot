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
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Novosibirsk")
    ADMIN_IDS: List[int] = field(
        default_factory=lambda: [
            int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
        ]
    )

config = Config()