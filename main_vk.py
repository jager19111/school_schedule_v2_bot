import asyncio
import logging
from vkbottle.bot import Bot

from config import config
from database.db import Database
from core.logger_config import setup_logging

# Импорт репозиториев
from core.repository.profile_repository import ProfileRepository
from core.repository.audit_repository import AuditRepository

# Импорт сервисов
from services.time_service import TimeService, TimeServiceConfig
from services.audit_service import AuditService
from services.profiles_service import ProfileService

# Импорт VK слоев
from bot_vk.handlers.registration import labeler as registration_labeler
from bot_vk.middlewares import create_di_middleware
from vkbottle.dispatch.dispenser.builtin import BuiltinStateDispenser

# Инициализируем систему логов ПЕРЕД созданием любых логгеров
setup_logging(log_level=config.LOG_LEVEL, log_dir=config.LOG_DIR)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Инициализация слоев для VK-бота...")
    
    # 1. Инициализация единого подключения к БД (Задача 1.1)
    database = Database(config.DB_PATH)
    await database.init_db()
    db_connection = await database.connect()
    
    try:
        # 2. Сервисы времени
        time_service = TimeService(TimeServiceConfig(timezone=config.TIMEZONE))
        
        # 3. Репозитории (Строго передаем db_connection и time_service)
        audit_repo = AuditRepository(db_path=db_connection, time_service=time_service)
        profile_repo = ProfileRepository(db_path=db_connection, time_service=time_service)
        
        # 4. Бизнес-сервисы
        audit_service = AuditService(
            audit_repo=audit_repo, 
            profile_repo=profile_repo, 
            time_service=time_service, 
            log_dir=config.LOG_DIR
        )
        profile_service = ProfileService(
            profile_repo, 
            audit_service=audit_service
        )
        
        # 5. Инициализация VK-бота (добавьте VK_TOKEN в .env или вставьте сюда)
        # Пример: bot = Bot(token=config.VK_TOKEN)
        bot = Bot(token="vk1.a.M5IFkPW9Y3AZlTLd0-AlgsT3OPNFmrPpbuX-EvCTEfru5mUxquit-0m_c8VTz_iKvdVzH2ZU4awgMHG0GWE7r9jxz24vAKHtDJshV6qklMzYGfVhNrxOp8uPja6oH72dYpd11hZ3X_OE2sCwN2xlGV9jog2z0_2O0ry7t5MOwK2r3F9xHnePGGJSBrSUjySvC9DwqkRbI8V8WZRwqtBbXA")
        state_dispenser = BuiltinStateDispenser() # <-- СОЗДАЕМ ДИСПЕТЧЕР FSM
        bot.state_dispenser = state_dispenser
       # 6. Dependency Injection: внедряем сервисы и диспетчер
        bot.labeler.message_view.register_middleware(
            create_di_middleware(
                state_dispenser=state_dispenser, # <-- ПЕРЕДАЕМ В MIDDLEWARE
                profile_service=profile_service
            )
        )
        
        # 7. Регистрация нового роутера (Labeler)
        bot.labeler.load(registration_labeler)
            
        logger.info("🚀 VK-бот успешно запущен и подключен к БД!")
        await bot.run_polling()
        
    finally:
        await database.close()
        logger.info("VK-бот остановлен.")

if __name__ == "__main__":
    asyncio.run(main())