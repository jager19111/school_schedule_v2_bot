# main.py
## РЕШЁННЫЕ ПРОБЛЕМЫ:
#
# 1. I/O (Задача 1.1): создаётся ЕДИНОЕ постоянное подключение к БД
#    (db_connection = await database.connect()) и передаётся ВО ВСЕ
#    репозитории вместо строки db_path. Раньше каждый запрос каждого
#    репозитория открывал/закрывал собственное aiosqlite-соединение —
#    при сотнях клиентов и 4 фоновых джобах это основной источник
#    лишнего file I/O и SQLITE_BUSY. В finally — гарантированное
#    закрытие соединения при остановке бота.
#
# 2. Дополнительно (best practice): ночная задача PRAGMA wal_checkpoint(TRUNCATE),
#    чтобы -wal файл не рос бесконечно при постоянной записи.
#
# 3. Мелкий фикс: убран продублированный
#    "except asyncio.CancelledError: raise" в refresh_schedule_cache.
# ЭТАП 2. СЕТЕВОЙ СЛОЙ (Задача 2.1): персистентная aiohttp-сессия.
#
# ИЗМЕНЕНИЯ:
# - В main() создаётся ЕДИНАЯ http_session на весь жизненный цикл:
#     tcp-коннектор с keep-alive, лимитом пула (хост один, 5 слотов
#     с запасом), кешем DNS на 5 минут (иначе резолвинг при каждом
#     соединении) и очисткой закрытых SSL-сокетов (против
#     ResourceWarning). Session-таймаут 15 сек — безопасный дефолт;
#     probe() и fetch_js_content() переопределяют его per-request
#     своими бюджетами (15с и 30с соответственно).
# - http_session передаётся в ScheduleRepository -> ScheduleFetcher.
#   Раньше каждый probe() (раз в NIKA_REFRESH_INTERVAL_MINUTES)
#   поднимал новый TCP+TLS-сокет и закрывал его.
# - В finally — гарантированное закрытие сессии (с проверкой closed),
#   в порядке: scheduler -> БД -> HTTP-сессия -> bot.session.
#
# ПРОШЛЫЕ ЭТАПЫ (без изменений):
# - Задача 1.1: единое shared-подключение SQLite на весь жизненный цикл.
# - Дополнительно: ночная задача PRAGMA wal_checkpoint(TRUNCATE).
# - Фиксы Этапа 2 сервисного слоя: notification_service в workflow_data
#   (для админ-команды /stress).

import asyncio
import datetime
import logging
import aiohttp
import aiosqlite

from aiogram.types import BotCommand
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
from services.help_service import HelpService

from bot.middlewares.error_middleware import GlobalErrorMiddleware
from bot.handlers import (
    registration,
    schedule_child,
    settings,
    extra_classes,
    admin,
    search,
    schedule_teacher,
    help
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
    # Админ-алерт: парсер NIKA работает в обход TLS-проверки.
    # Флаг обновляется фетчером при каждой попытке; проверка в начале
    # тика читает состояние последней попытки (задержка <= 5 мин).
    # Обновления расписания при этом НЕ останавливаются.
    try:
        if schedule_repo.is_ssl_degraded():
            await notification_service.send_admin_alert(
                alert_key="ssl_degraded",
                text=(
                    "⚠️ <b>Внимание: ошибка SSL-сертификата!</b>\n\n"
                    "Сайт лицея не прошёл проверку подлинности.\n"
                    "Парсер автоматически переключился в режим без "
                    "проверки сертификата.\n"
                    "Возможен перехват трафика (MITM).\n\n"
                    "Скорее всего школа сменила сертификат — обновите "
                    "NIKA_TLS_FINGERPRINT_SHA256 в "
                    "core/nika/fetcher.py.\n\n"
                    "Новый отпечаток снять командой:\n"
                    "<code>echo | openssl s_client -connect "
                    "lyceum.nstu.ru:443 -servername lyceum.nstu.ru "
                    "| openssl x509 -noout -fingerprint -sha256"
                    "</code>\n\n"
                    "Обновления расписания продолжают поступать — "
                    "это предупреждение только о снижении защиты."
                ),
            )
    except Exception:
        # Сбой алерта не должен ломать refresh расписания.
        logger.exception("SSL degradation admin alert failed")

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
                "Failed to persist NIKA source error."
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


async def run_wal_checkpoint(db_connection: aiosqlite.Connection) -> None:
    """
    Ночной WAL-checkpoint (best practice).

    При WAL и постоянной записи -wal файл может расти долго; усечение
    ночью держит его компактным и ускоряет чтение. Безопасно: checkpoint
    не блокирует читателей надолго и не теряет данные.
    """
    try:
        result = await Database.checkpoint_wal(db_connection)
        logger.info("Nightly WAL checkpoint completed: %s", result)
    except Exception:
        logger.exception("Nightly WAL checkpoint failed")


async def main():
    if not config.BOT_TOKEN:
        logger.error("Критическая ошибка: BOT_TOKEN не задан в .env файле!")
        return

    # 1. Инициализация бота и диспетчера
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    await bot.set_my_commands([
        BotCommand(
            command="start",
            description="Начать работу с ботом",
        ),
        BotCommand(
            command="help",
            description="Справка и возможности бота",
        ),
#        BotCommand(
#            command="support",
#            description="Связь с автором и поддержка проекта",
#        )
    ])

    dp = Dispatcher()
    tz = ZoneInfo(config.TIMEZONE)

    # Этап 3: глобальный перехват ошибок хендлеров.
    # Один вызов оборачивает весь пайплайн (message, callback_query,
    # edited_message, my_chat_member): непредвиденное исключение
    # больше не оставляет пользователя без ответа и не роняет
    # обработку апдейта. Ожидаемые TelegramBadRequest остаются
    # на локальных _safe_edit_* как раньше.
    dp.update.outer_middleware(GlobalErrorMiddleware())
    
    # 2. Инициализация базы данных
    database = Database(config.DB_PATH)
    await database.init_db()

    # ==============================================================
    # Задача 1.1: единое shared-подключение на весь жизненный цикл.
    # Все PRAGMA (foreign_keys, busy_timeout, WAL, synchronous)
    # настраиваются внутри Database.connect() один раз.
    # ==============================================================
    db_connection = await database.connect()

    # ==============================================================
    # Задача 2.1: персистентная HTTP-сессия на весь жизненный цикл.
    #
    # - keep-alive: соединение к lyceum.nstu.ru переиспользуется
    #   между тиками probe() вместо нового TCP+TLS-сокета каждые
    #   NIKA_REFRESH_INTERVAL_MINUTES (при прокси — ещё и CONNECT);
    # - ttl_dns_cache=300: DNS не резолвится заново на каждое
    #   соединение;
    # - limit=5: хост один, пяти слотов пула достаточно с запасом
    #   (probe и JS-загрузка не параллелятся);
    # - enable_cleanup_closed=True: чистит закрытые SSL-сокеты,
    #   иначе копятся ResourceWarning;
    # - timeout 15 сек — session-дефолт; probe()/fetch_js_content()
    #   переопределяют его per-request (15с / 30с).
    # ==============================================================
    http_session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=15),
        connector=aiohttp.TCPConnector(
            limit=5,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        ),
    )

    scheduler: AsyncIOScheduler | None = None

    try:
        # 3. Сервисы времени
        time_service = TimeService(TimeServiceConfig(timezone=config.TIMEZONE))

        # 4. Репозитории.
        # ВНИМАНИЕ: db_path= принимает ОБЪЕКТ СОЕДИНЕНИЯ, а не строку.
        # Это обеспечивает один пул (одно соединение) для всего приложения.
        schedule_repo = ScheduleRepository(
            db_path=db_connection,
            http_session=http_session,
            proxy=config.PROXY_URL,
            time_service=time_service,
            nika_base_url=config.NIKA_BASE_URL,
            history_days=config.NIKA_HISTORY_DAYS,
            tls_fingerprint_sha256=config.NIKA_TLS_FINGERPRINT_SHA256,
        )

        logger.info(
            "NIKA source configured: base_url=%s, proxy=%s",
            config.NIKA_BASE_URL,
            "enabled" if config.PROXY_URL else "disabled",
        )

        user_repo = UserRepository(db_path=db_connection, time_service=time_service)
        admin_repo = AdminRepository(db_path=db_connection, time_service=time_service)
        profile_repo = ProfileRepository(db_path=db_connection, time_service=time_service)
        notification_repo = NotificationRepository(db_path=db_connection, time_service=time_service)
        extra_classes_repo = ExtraClassesRepository(db_path=db_connection, time_service=time_service)
        watch_target_repo = WatchTargetRepository(db_path=db_connection, time_service=time_service)
        student_repo = StudentRepository(db_path=db_connection, time_service=time_service)

        # 5. Сервисы
        schedule_service = ScheduleService(schedule_repo=schedule_repo, extra_classes_repo=extra_classes_repo, time_service=time_service)
        profile_service = ProfileService(profile_repo)
        notification_service = NotificationService(bot, notification_repo, time_service=time_service, schedule_repo=schedule_repo, extra_classes_repo=extra_classes_repo, admin_ids=config.ADMIN_IDS,)
        cleanup_job = UserCleanupJob(user_repo, time_service=time_service, dormant_days=60)
        students_service = StudentsService(student_repo, profile_service=profile_service)
        admin_service = AdminService(admin_repo=admin_repo, schedule_repo=schedule_repo, admin_ids=config.ADMIN_IDS)
        extra_classes_service = ExtraClassesService(extra_classes_repo=extra_classes_repo, profile_service=profile_service, students_service=students_service, time_service=time_service)
        watch_targets_service = WatchTargetsService(repository=watch_target_repo)
        help_service = HelpService(public_help_url=config.HELP_PUBLIC_URL, author_contact_url=config.AUTHOR_CONTACT_URL, donation_url=config.DONATION_URL)
        notification_delivery_cleanup_job = NotificationDeliveryCleanupJob(notification_repo=notification_repo, time_service=time_service, retention_days=35)

        # 6. Регистрация роутеров команд
        dp.include_router(registration.router)
        dp.include_router(help.router)
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
            help_service=help_service,
            schedule_repo=schedule_repo,
            user_repository=user_repo,
            profile_repo=profile_repo,
            notification_repo=notification_repo,
            extra_classes_repo=extra_classes_repo,
            admin_repo=admin_repo,
            student_repo=student_repo,
            db_path=config.DB_PATH,
            notification_service=notification_service, # Для теста из админ хендлера
            config=config
        )

        # 7. Первоначальная синхронизация кэша при старте
        logger.info("Синхронизация первичного кэша расписания...")
        await refresh_schedule_cache(
            schedule_repo=schedule_repo,
            notification_service=notification_service,
            tz=tz,
            config=config,
        )

        # 8. Настройка планировщика задач (APScheduler)
        scheduler = AsyncIOScheduler(timezone=tz)

        # Предурочные напоминания
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

        # Оповещения об изменениях в N-дневном окне
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

        # Фоновое обновление кэша из NIKA
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

        # Деактивация неактивных пользователей раз в сутки в 03:00
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

        # Ночной WAL-checkpoint: усечение -wal файла (best practice).
        scheduler.add_job(
            run_wal_checkpoint,
            trigger="cron",
            hour=3,
            minute=20,
            kwargs={"db_connection": db_connection},
            id="wal_checkpoint",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )

        # Утренняя сводка: проверяется каждую минуту, отправка при
        # совпадении current_time_str с users.morning_summary_time.
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

        # 9. Запуск поллинга
        logger.info("🚀 Бот (v2) готов к работе!")
        await dp.start_polling(bot)
    finally:
        # Гарантированное освобождение ресурсов.
        # Порядок: scheduler (без ожидания задач) -> БД -> HTTP-сессия
        # -> aiogram session. HTTP-сессия закрывается с проверкой,
        # чтобы двойное закрытие не падало.
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await database.close()
        if not http_session.closed:
            await http_session.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
