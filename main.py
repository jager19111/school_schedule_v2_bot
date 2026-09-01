import asyncio
import logging
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import Config
from database.db import Database
from core.repository.schedule_repository import ScheduleRepository
from services.profiles import ProfileService
from services.schedule_v2 import ScheduleServiceV2
from services.notifications import NotificationService
from services.cleanup import UserCleanupJob
from bot.handlers import registration, schedule_child, settings, extra_classes, admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def main():
    config = Config()
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    # 1. Инициализация БД
    database = Database(config.DB_PATH)
    await database.init_db()

    # 2. Инициализация сервисов и репозитория
    repo = ScheduleRepository(db_path=config.DB_PATH, proxy=config.PROXY_URL)
    schedule_service = ScheduleServiceV2(repo)
    profile_service = ProfileService(config.DB_PATH)
    notification_service = NotificationService(bot, config.DB_PATH, timezone="Asia/Novosibirsk")

    # 3. Интеграция обработчиков
    dp.include_router(registration.router)
    dp.include_router(schedule_child.router)
    dp.include_router(settings.router)
    dp.include_router(extra_classes.router)
    dp.include_router(admin.router)

    # Проброс зависимостей в хендлеры (Dependency Injection)
    dp.workflow_data.update(
        profile_service=profile_service,
        schedule_service=schedule_service,
        schedule_repo=repo,
        db_path=config.DB_PATH
    )

    # 4. Настройка планировщика (APScheduler) со строгой таймзоной[cite: 4, 7]
    tz = ZoneInfo("Asia/Novosibirsk")
    scheduler = AsyncIOScheduler(timezone=tz)
    
    # Предурочные напоминания (запуск каждые 5 минут)[cite: 4, 7]
    scheduler.add_job(notification_service.send_pre_lesson_reminders, 'interval', minutes=5)
    
    # Напоминания об изменениях (запуск каждые 45 минут)[cite: 4, 7]
    scheduler.add_job(notification_service.send_upcoming_changes, 'interval', minutes=45)
    
    # Фоновое обновление кэша из NIKA и удаление дампов raw_nika_cache старше 7 дней[cite: 7]
    scheduler.add_job(repo.refresh_from_remote, 'interval', minutes=45, args=[])

    # Очистка неактивных пользователей (запуск раз в сутки)[cite: 4]
    cleanup_job = UserCleanupJob(config.DB_PATH, dormant_days=60)
    scheduler.add_job(cleanup_job.deactivate_dormant_users, 'cron', hour=3, minute=0)

    scheduler.start()

    logger.info("🚀 Бот (v2) успешно запущен!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())












def setup_scheduler(bot: Bot, db_path: str):
    """Настройка интервалов и триггеров планировщика[cite: 1, 4]."""
    tz = ZoneInfo("Asia/Novosibirsk")
    scheduler = AsyncIOScheduler(timezone=tz)
    
    notification_service = NotificationService(bot, db_path, timezone="Asia/Novosibirsk")

    # Предурочные напоминания: каждые 5 минут для плавающего расписания смен[cite: 4, 7]
    scheduler.add_job(
        notification_service.send_pre_lesson_reminders,
        'interval',
        minutes=5,
        id='pre_lesson_reminders',
        replace_existing=True
    )

    # Мониторинг отложенных замен в N-дневном окне: каждые 45 минут[cite: 5, 7]
    scheduler.add_job(
        notification_service.send_upcoming_changes,
        'interval',
        minutes=45,
        id='upcoming_changes',
        replace_existing=True
    )
    
    # Утренний брифинг (например, в 7:00 ежедневно)[cite: 1, 7]
    # scheduler.add_job(notification_service.send_morning_reminders, 'cron', hour=7, minute=0, ...)
    
    return scheduler