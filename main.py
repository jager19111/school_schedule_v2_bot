import asyncio
import datetime
import logging
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import config
from database.db import Database
from core.repository.schedule_repository import ScheduleRepository
from core.repository.user_repository import UserRepository
from core.repository.admin_repository import AdminRepository
from core.repository.profile_repository import ProfileRepository
from core.repository.notification_repository import NotificationRepository
from core.repository.extra_classes_repository import ExtraClassesRepository

from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.notifications_service import NotificationService
from services.extra_classes_service import ExtraClassesService
from services.cleanup_service import UserCleanupJob
from services.time_service import TimeService, TimeServiceConfig
from services.admin_service import AdminService
from bot.handlers import (
    registration,
    schedule_child,
    schedule_parent,
    settings,
    extra_classes,
    admin
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def scheduled_schedule_refresh(repo: ScheduleRepository, tz: ZoneInfo) -> None:
    """Фоновая выгрузка и обновление расписания на ближайшие 14 дней[cite: 3, 5]."""
    try:
        today = datetime.datetime.now(tz).date()
        target_dates = [today + datetime.timedelta(days=i) for i in range(14)]
        await repo.refresh_from_remote(target_dates)
    except Exception as e:
        logger.error(f"Ошибка периодического обновления расписания: {e}")

async def main():
    if not config.BOT_TOKEN:
        logger.error("Критическая ошибка: BOT_TOKEN не задан в .env файле!")
        return

    # 1. Инициализация бота и диспетчера
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    tz = ZoneInfo(config.TIMEZONE)

    # 2. Инициализация базы данных
    database = Database(config.DB_PATH)
    await database.init_db()

    
    # 3. Сервисы времени
    time_service = TimeService(TimeServiceConfig(timezone=config.TIMEZONE))
    
    # 4. Репозитории
    # PROXY_URL передается как None, если отключен в .env[cite: 2, 8]
    schedule_repo = ScheduleRepository(db_path=config.DB_PATH, proxy=config.PROXY_URL, time_service=time_service)
    user_repo = UserRepository(db_path=config.DB_PATH, time_service=time_service)
    admin_repo = AdminRepository(db_path=config.DB_PATH, time_service=time_service)
    profile_repo = ProfileRepository(db_path=config.DB_PATH, time_service=time_service)
    notification_repo = NotificationRepository(db_path=config.DB_PATH, time_service=time_service)
    extra_classes_repo = ExtraClassesRepository(db_path=config.DB_PATH)
    
    # 5. Сервисы
    schedule_service = ScheduleService(schedule_repo=schedule_repo, extra_classes_repo=extra_classes_repo, time_service=time_service)
    profile_service = ProfileService(profile_repo)
    notification_service = NotificationService(bot, notification_repo, time_service)
    cleanup_job = UserCleanupJob(user_repo, time_service=time_service, dormant_days=60)
    admin_service = AdminService(admin_repo)
    extra_classes_service = ExtraClassesService(extra_classes_repo=extra_classes_repo, time_service=time_service)
    
    # 4. Регистрация роутеров команд
    dp.include_router(registration.router)
    dp.include_router(schedule_child.router)
    dp.include_router(schedule_parent.router)
    dp.include_router(settings.router)
    dp.include_router(extra_classes.router)
    dp.include_router(admin.router)

    # Внедрение зависимостей в хендлеры (Dependency Injection)
    dp.workflow_data.update(
        profile_service=profile_service,
        schedule_service=schedule_service,
        admin_service=admin_service,
        time_service=time_service,
        extra_classes_service=extra_classes_service,
        schedule_repo=schedule_repo,
        user_repository=user_repo,
        profile_repo=profile_repo,
        notification_repo=notification_repo,
        extra_classes_repo=extra_classes_repo,
        admin_repo=admin_repo,
        db_path=config.DB_PATH,
        config=config
    )

    # 5. Первоначальная синхронизация кэша при старте
    logger.info("Синхронизация первичного кэша расписания...")
    await scheduled_schedule_refresh(schedule_repo, tz)

    # 6. Настройка планировщика задач (APScheduler)
    scheduler = AsyncIOScheduler(timezone=tz)

    # Предурочные напоминания: интервал 5 минут (0 < delta <= N)[cite: 5, 7]
    scheduler.add_job(
        notification_service.send_pre_lesson_reminders,
        trigger='interval',
        minutes=5,
        id='pre_lesson_reminders',
        replace_existing=True
    )

    # Оповещения об изменениях в N-дневном окне: интервал 45 минут[cite: 5, 7]
    scheduler.add_job(
        notification_service.send_upcoming_changes,
        trigger='interval',
        minutes=45,
        id='upcoming_changes',
        replace_existing=True
    )

    # Фоновое обновление кэша из NIKA и чистка raw_nika_cache (>7 дней)[cite: 7]
    scheduler.add_job(
        scheduled_schedule_refresh,
        trigger='interval',
        minutes=45,
        args=[schedule_repo, tz],
        id='nika_refresh',
        replace_existing=True
    )

    # Деактивация неактивных пользователей раз в сутки в 03:00[cite: 4]
    scheduler.add_job(
        cleanup_job.deactivate_dormant_users,
        trigger='cron',
        hour=3,
        minute=0,
        id='dormant_cleanup',
        replace_existing=True
    )

    scheduler.start()
    logger.info("Планировщик задач успешно запущен.")

    # 7. Запуск поллинга
    logger.info("🚀 Бот (v2) готов к работе!")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())