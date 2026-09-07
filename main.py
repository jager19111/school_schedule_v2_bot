import asyncio
import datetime
import logging
import aiohttp
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import Config
from config import config
from database.db import Database
from core.repository.schedule_repository import ScheduleRepository
from core.repository.user_repository import UserRepository
from core.repository.admin_repository import AdminRepository
from core.repository.profile_repository import ProfileRepository
from core.repository.notification_repository import NotificationRepository
from core.repository.extra_classes_repository import ExtraClassesRepository
from core.repository.watch_target_repository import WatchTargetRepository
from core.repository.student_repository import StudentRepository
    
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.notifications_service import NotificationService
from services.extra_classes_service import ExtraClassesService
from services.cleanup_service import UserCleanupJob, NotificationDeliveryCleanupJob
from services.time_service import TimeService, TimeServiceConfig
from services.admin_service import AdminService
from services.watch_targets_service import WatchTargetsService
from services.students_service import StudentsService

from bot.handlers import (
    registration,
    schedule_child,
    settings,
    extra_classes,
    admin,
    search,
    schedule_teacher
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def refresh_schedule_cache(
    *,
    schedule_repo: ScheduleRepository,
    notification_service: NotificationService,
    tz: ZoneInfo,
    config: Config,
) -> None:
    """
    Обновляет NIKA cache безопасно.

    Любая ошибка source/parsing/DB:
    - логируется;
    - сохраняется в nika_source_state.last_error;
    - не пробрасывается в APScheduler;
    - не очищает ранее существующий schedule_cache.
    """
    today = datetime.datetime.now(tz).date()

    monday = today - datetime.timedelta(
        days=today.isoweekday() - 1,
    )

    target_dates = [
        monday + datetime.timedelta(days=offset)
        for offset in range(config.NIKA_COVERAGE_DAYS)
    ]

    try:
        result = await schedule_repo.refresh_if_changed(
            target_dates=target_dates,
        )

    except asyncio.CancelledError:
        # Важно: не проглатывать штатное завершение приложения.
        raise

    except asyncio.CancelledError:
        raise

    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
    ) as exc:
        error_message = f"{type(exc).__name__}: {exc}"

        logger.warning(
            "NIKA source unavailable. Keeping existing schedule cache. "
            "error=%s",
            error_message,
        )

        try:
            await schedule_repo.record_nika_refresh_error(
                error_message=error_message,
            )
        except Exception:
            logger.exception(
                "Failed to persist NIKA source error."
            )

        return

    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"

        logger.exception(
            "Unexpected NIKA refresh failure. "
            "Keeping existing schedule cache. error=%s",
            error_message,
        )

        try:
            await schedule_repo.record_nika_refresh_error(
                error_message=error_message,
            )
        except Exception:
            logger.exception(
                "Failed to persist NIKA refresh error."
            )

        return

    try:
        await schedule_repo.clear_nika_refresh_error()
    except Exception:
        logger.exception(
            "NIKA refresh succeeded, but source error state "
            "could not be cleared."
        )

    logger.info(
        "NIKA refresh result: reason=%s, "
        "source_changed=%s, schedule_changed=%s, "
        "js_filename=%s, lesson_count=%s",
        result.reason,
        result.source_changed,
        result.schedule_changed,
        result.js_filename,
        result.lesson_count,
    )

    # Notifications — отдельная business operation.
    # Её ошибка не является ошибкой NIKA source.
    if not result.schedule_changed:
        return

    try:
        await notification_service.send_upcoming_changes()
    except asyncio.CancelledError:
        raise

    except Exception:
        logger.exception(
            "Schedule changed successfully, but immediate "
            "change notifications failed."
        )
        
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
    schedule_repo = ScheduleRepository(
    db_path=config.DB_PATH,
    proxy=config.PROXY_URL,
    time_service=time_service,
    nika_base_url=config.NIKA_BASE_URL,
    history_days=config.NIKA_HISTORY_DAYS,
    )
    
    logger.info(
    "NIKA source configured: base_url=%s, proxy=%s",
    config.NIKA_BASE_URL,
    "enabled" if config.PROXY_URL else "disabled",
    )
    user_repo = UserRepository(db_path=config.DB_PATH, time_service=time_service)
    admin_repo = AdminRepository(db_path=config.DB_PATH, time_service=time_service)
    profile_repo = ProfileRepository(db_path=config.DB_PATH, time_service=time_service)
    notification_repo = NotificationRepository(db_path=config.DB_PATH, time_service=time_service)
    extra_classes_repo = ExtraClassesRepository(db_path=config.DB_PATH, time_service=time_service)
    watch_target_repo = WatchTargetRepository(db_path=config.DB_PATH, time_service=time_service)
    student_repo = StudentRepository(db_path=config.DB_PATH, time_service=time_service)
        
    # 5. Сервисы
    schedule_service = ScheduleService(schedule_repo=schedule_repo, extra_classes_repo=extra_classes_repo, time_service=time_service)
    profile_service = ProfileService(profile_repo)
    notification_service = NotificationService(bot, notification_repo, time_service=time_service, schedule_repo=schedule_repo, extra_classes_repo=extra_classes_repo)
    cleanup_job = UserCleanupJob(user_repo, time_service=time_service, dormant_days=60)
    students_service = StudentsService(student_repo, profile_service = profile_service)
    admin_service = AdminService(admin_repo=admin_repo, schedule_repo=schedule_repo, admin_ids=config.ADMIN_IDS)
    extra_classes_service = ExtraClassesService(extra_classes_repo=extra_classes_repo, profile_service=profile_service, students_service=students_service, time_service=time_service)
    watch_targets_service = WatchTargetsService(repository=watch_target_repo)

        
    notification_delivery_cleanup_job = NotificationDeliveryCleanupJob(notification_repo=notification_repo, time_service=time_service, retention_days=35)
        
    # 4. Регистрация роутеров команд
    dp.include_router(registration.router)

    # Teacher router содержит только teacher_sched:* callbacks.
    dp.include_router(schedule_teacher.router)

    # Единственная message entry point:
    # «📅 Моё расписание» для child / parent / observer / teacher.
    dp.include_router(schedule_child.router)

    dp.include_router(settings.router)
    dp.include_router(extra_classes.router)
    dp.include_router(admin.router)
    dp.include_router(search.router)
        
    # Внедрение зависимостей в хендлеры (Dependency Injection)
    dp.workflow_data.update(
        profile_service=profile_service,
        schedule_service=schedule_service,
        admin_service=admin_service,
        time_service=time_service,
        extra_classes_service=extra_classes_service,
        watch_targets_service=watch_targets_service,
        students_service=students_service,
        schedule_repo=schedule_repo,
        user_repository=user_repo,
        profile_repo=profile_repo,
        notification_repo=notification_repo,
        extra_classes_repo=extra_classes_repo,
        admin_repo=admin_repo,
        student_repo=student_repo,
        db_path=config.DB_PATH,
        config=config
    )

    # 5. Первоначальная синхронизация кэша при старте
    logger.info("Синхронизация первичного кэша расписания...")
    await refresh_schedule_cache(
        schedule_repo=schedule_repo,
        notification_service=notification_service,
        tz=tz,
        config=config,
    )

    # ВРЕМЕННЫЙ smoke-test предурочного уведомления.
    # Удалить сразу после проверки.
    # await notification_service.send_morning_reminders()
    
    # 6. Настройка планировщика задач (APScheduler)
    scheduler = AsyncIOScheduler(timezone=tz)

    # Предурочные напоминания: интервал 5 минут (0 < delta <= N)[cite: 5, 7]
    scheduler.add_job(
        notification_service.send_pre_lesson_reminders,
        trigger="interval",
        minutes=1,
        id="pre_lesson_reminders",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=90,
    )
    
    # Напоминания о дополнительных занятиях.
    # Запуск раз в минуту: это уменьшает риск пропуска окна при старте,
    # задержке event loop или точном значении reminder_minutes.
    scheduler.add_job(
        notification_service.send_extra_class_reminders,
        trigger="interval",
        minutes=1,
        id="extra_class_reminders",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=90,
    )
    
    # Оповещения об изменениях в N-дневном окне: интервал 15 минут
    scheduler.add_job(
        notification_service.send_upcoming_changes,
        trigger="interval",
        minutes=15,
        id="upcoming_changes",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Фоновое обновление кэша из NIKA и чистка raw_nika_cache (>7 дней)[cite: 7]
    scheduler.add_job(
        refresh_schedule_cache,
        trigger="interval",
        minutes=config.NIKA_REFRESH_INTERVAL_MINUTES,
        kwargs={
            "schedule_repo": schedule_repo,
            "notification_service": notification_service,
            "tz": tz,
            "config": config,
        },
        id="nika_refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    # Деактивация неактивных пользователей раз в сутки в 03:00[cite: 4]
    scheduler.add_job(
        cleanup_job.deactivate_dormant_users,
        trigger="cron",
        hour=3,
        minute=0,
        id="dormant_cleanup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    
    scheduler.add_job(
        notification_delivery_cleanup_job.cleanup_old_deliveries,
        trigger="cron",
        hour=3,
        minute=10,
        id="notification_delivery_cleanup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    #  настройка задачи утренней сводки:
    # Проверяется каждую минуту: отправка происходит при совпадении
    # current_time_str с users.morning_summary_time.
    scheduler.add_job(
        notification_service.send_morning_reminders,
        trigger="interval",
        minutes=1,
        id="morning_reminders",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=90,
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