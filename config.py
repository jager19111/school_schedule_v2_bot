import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# Загрузка переменных окружения из файла .env
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    DB_PATH: str = os.getenv("DB_PATH", "schedule_bot.db")
    PROXY_URL: str = os.getenv("PROXY_URL", "")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Novosibirsk")
    # Преобразование строки ID администраторов в список чисел
    ADMIN_IDS: list[int] = field(
        default_factory=lambda: [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
    )

config = Config()