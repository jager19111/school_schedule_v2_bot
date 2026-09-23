# bot/handlers/admin.py
#
# ИЗМЕНЕНИЯ:
# 1. Команда /stress [count] — стресс-тест боевого пайплайна уведомлений
#    через NotificationService.debug_send_burst (paced send, батчевый dedup
#    и delivery log). Тестирует лимиты Telegram (429), дросселирование,
#    идемпотентность на рестарте.
# 2. Команда /stress_render [count] — долгосрочный стресс-тест рендера:
#    непрерывный поток уникальных постеров для проверки утечек RAM.
# /stats — статистика пользователей + anti-flood
# /img_stats — статистика ImageGenerationService (этап 4/5 ТЗ v2.2):
#    рендеры, кэши L1/L2, rate limit, circuit breaker, здоровье движка
#    и перцентили латентности (p50/p95/p99).
# /source_status — статус актуальности кеша NIKA
# DEBUG-команды для быстрой проверки UI уведомлений:
# /debug_ui morning|change|lesson
import asyncio
import logging


from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from datetime import datetime


from bot.utils.ui_renderer import UIRenderer
from services.admin_service import AdminService
from services.notifications_service import NotificationService
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import config
from services.image_render.poster_factory import build_poster_request
from services.image_render.service import ImageGenerationService
from services.schedule_service import ScheduleService
from services.time_service import TimeService


from bot.middlewares.antiflood import AntiFloodMiddleware, AntiFloodStatsDTO


logger = logging.getLogger(__name__)
router = Router()


# Максимальное число сообщений за один запуск /stress.
MAX_STRESS_COUNT = 500


# Приблизительный пер-чат интервал отправки (для оценки времени).
PER_CHAT_SEND_INTERVAL_SEC = 1.1



async def _require_admin(
    *,
    message: Message,
    admin_service: AdminService,
) -> bool:
    """
    Проверяет доступ к admin commands через service.
    """
    if admin_service.is_admin(
        user_id=message.from_user.id,
    ):
        return True


    logger.warning(
        "Admin command denied: user_id=%s command=%r",
        message.from_user.id,
        message.text,
    )


    await message.answer(
        "⛔ Команда доступна только администратору."
    )


    return False



@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    admin_service: AdminService,
    antiflood: AntiFloodMiddleware,
) -> None:
    if not await _require_admin(message=message, admin_service=admin_service):
        return
    dto = await admin_service.get_statistics()
    text = UIRenderer.render_admin_stats(dto)
    text += "\n\n" + _render_antiflood_section(antiflood.stats_snapshot())
    await message.answer(text, parse_mode="HTML")


@router.message(Command("source_status"))
async def cmd_source_status(
    message: Message,
    admin_service: AdminService,
) -> None:
    """
    Показывает сохранённое состояние NIKA source и schedule cache.


    Не запускает refresh и не делает HTTP request.
    """
    if not await _require_admin(
        message=message,
        admin_service=admin_service,
    ):
        return


    dto = await admin_service.get_nika_source_health()


    text = UIRenderer.render_nika_source_health(
        dto,
    )


    await message.answer(
        text,
        parse_mode="HTML",
    )


@router.message(Command("img_stats"))
async def cmd_img_stats(
    message: Message,
    admin_service: AdminService,
    image_service: ImageGenerationService,
) -> None:
    """
    Статистика генерации постеров (этапы 4/5 ТЗ v2.2):
    рендеры, кэши L1/L2, rate limit, circuit breaker, здоровье движка
    и перцентили латентности для калибровки констант.
    """
    if not await _require_admin(message=message, admin_service=admin_service):
        return

    stats = image_service.stats().snapshot()
    state = image_service.snapshot()
    healthy = await image_service.is_healthy()

    text = _render_image_stats_section(
        stats=stats,
        state=state,
        healthy=healthy,
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("stress"))
async def cmd_stress(
    message: Message,
    admin_service: AdminService,
    notification_service: NotificationService,
) -> None:
    """
    Стресс-тест боевого пайплайна уведомлений (только админ).


    /stress             — 50 сообщений себе по умолчанию;
    /stress 100          — указанное количество (1..500) себе;
    /stress 50 1234567  — указанное количество указанному chat_id.
    Что проверяет:
    - дросселирование (глобальный темп + 1 сообщение/сек на чат);
    - обработку 429 Too Many Requests;
    - идемпотентность на рестарте: прерви тест Ctrl+C, перезапусти
      бота и запусти снова — рассылка продолжится с места остановки,
      а не начнётся сначала (дедупликация через delivery log).


    Время выполнения ~ count * 1.1 сек из-за пер-чат лимита Telegram.    """
    if not await _require_admin(
        message=message,
        admin_service=admin_service,
    ):
        return


    parts = (message.text or "").split()


    # Значения по умолчанию
    count = 50
    target_chat_id = message.from_user.id


    # Парсим количество (первый аргумент)
    if len(parts) > 1 and parts[1].isdigit():
        count = int(parts[1])


    # Парсим кастомный ID получателя (второй аргумент)
    # lstrip('-') позволяет передавать ID групп (они отрицательные)
    if len(parts) > 2 and parts[2].lstrip('-').isdigit():
        target_chat_id = int(parts[2])


    count = max(1, min(count, MAX_STRESS_COUNT))
    estimated_seconds = int(count * PER_CHAT_SEND_INTERVAL_SEC)


    logger.info(
        "Stress test started: admin_id=%s, target_id=%s, count=%d",
        message.from_user.id,
        target_chat_id,
        count,
    )


    # Используем извлеченный target_chat_id вместо message.from_user.id
    result = await notification_service.debug_send_burst(
        chat_id=target_chat_id,
        count=count,
    )


    await message.answer(
        "🧪 <b>Стресс-тест завершён</b>\n\n"
        f"Получатель: <code>{target_chat_id}</code>\n"
        f"Запрошено: {result.requested}\n"
        f"К отправке после дедупликации: {result.pending}\n"
        f"Отправлено: {result.sent}\n"
        f"Ошибок: {result.failed}\n\n"
        "Если 'к отправке' меньше 'запрошено' — дедупликация "
        "отработала (это уже отправленные сегодня сообщения)."
    )
    logger.info(
        "Stress test finished: admin_id=%s, target_id=%s, result=%s",
        message.from_user.id,
        target_chat_id,
        result,
    )


@router.message(Command("stress_render"))
async def cmd_stress_render_long(
    message: Message,
    admin_service: AdminService,
    schedule_service: ScheduleService,
    image_service: ImageGenerationService,
    time_service: TimeService,
) -> None:
    """Долгосрочный стресс-тест: непрерывный поток рендеров для проверки утечек RAM."""
    if not await _require_admin(message=message, admin_service=admin_service):
        return

    parts = (message.text or "").split()
    count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 100
    count = max(1, min(count, 2000))  # Защита от бесконечного цикла

    status_msg = await message.answer(
        f"🔥 Запускаю долгосрочный стресс-тест на {count} постеров...\n"
        "Откройте htop на сервере. Рендер займет время."
    )

    today_iso = time_service.get_now_base().date().isoformat()

    # 1. Получаем DTO один раз, чтобы тестировать именно графику,
    # а не нагружать SQLite одинаковыми SELECT-запросами.
    base_dto = await schedule_service.get_daily_schedule_for_student(
        class_id="016",
        group_id="ALL",
        date_iso=today_iso,
        student_id=None
    )

    # 2. Шлюз-дозатор.
    # Пропускает в сервис не более 15 задач одновременно.
    # Это значение должно быть МЕНЬШЕ вашего IMAGE_QUEUE_CAPACITY,
    # чтобы очередь никогда не переполнялась.
    feeder_semaphore = asyncio.Semaphore(15)

    async def render_with_throttle(i: int):
        async with feeder_semaphore:
            # Уникальный request_id пробивает in-memory кэш
            # и заставляет браузер рисовать каждый постер с нуля
            request = build_poster_request(
                request_id=f"stress_long_{today_iso}_{i}",
                dto=base_dto,
                title=f"Стресс-тест #{i}",
                date_text=today_iso,
                width=1080
            )
            return await image_service.get_poster(request, user_id=None)

    # 3. Запускаем конвейер
    tasks = [render_with_throttle(i) for i in range(count)]

    start_time = time_service.get_now_base()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    duration = (time_service.get_now_base() - start_time).total_seconds()

    success = sum(1 for r in results if not isinstance(r, Exception))
    failed = count - success

    error_msg = ""
    if failed > 0:
        first_err = next(r for r in results if isinstance(r, Exception))
        error_msg = f"\n\n🛑 <b>Первая ошибка:</b>\n<code>{repr(first_err)}</code>"

    await status_msg.edit_text(
        f"🏁 <b>Марафон завершен за {duration:.2f} сек</b>\n\n"
        f"Успешно: {success}\n"
        f"Ошибок: {failed}{error_msg}\n"
        f"Средняя скорость: {(duration/max(1, success)):.3f} сек/постер",
        parse_mode="HTML",
    )


def _render_antiflood_section(dto: AntiFloodStatsDTO) -> str:
    lines = ["🛡 <b>Anti-flood</b>"]
    lines.append(f"Пропущено событий: {dto.allowed_total}")
    lines.append(f"Отсеяно троттлингом: {dto.throttled_total}")
    if dto.throttled_total:
        total = dto.throttled_total + dto.allowed_total
        ratio = dto.throttled_total / max(1, total) * 100
        lines.append(f"Доля отсева: {ratio:.1f}%")
        if dto.last_throttled_at:
            stamp = datetime.fromtimestamp(dto.last_throttled_at).strftime(
                "%d.%m %H:%M:%S",
            )
            lines.append(f"Последний отсев: {stamp}")
        if dto.throttled_by_user:
            lines.append("Топ нарушителей:")
            for user_id, count in dto.throttled_by_user.items():
                lines.append(f"  • <code>{user_id}</code>: {count}")
    else:
        lines.append("Ни одного срабатывания — спама не было.")
    lines.append(f"Активных бакетов: {dto.tracked_users}")
    return "\n".join(lines)


def _render_image_stats_section(
    *,
    stats: dict,
    state: dict,
    healthy: bool,
) -> str:
    """HTML-блок статистики ImageGenerationService для /img_stats."""
    attempts = stats["renders"] + stats["cache_hits"]
    hit_ratio = stats["cache_hits"] / max(1, attempts) * 100
    lines = ["🖼 <b>ImageGenerationService</b>"]
    lines.append(
        f"Движок: <code>{config.IMAGE_RENDER_ENGINE}</code> · "
        f"Рубильник: {'вкл' if config.ENABLE_IMAGE_GENERATION else 'выкл'} · "
        f"Здоровье движка: {'✅' if healthy else '❌'}"
    )
    lines.append(
        f"Рендеров: <b>{stats['renders']}</b> · "
        f"Кэш-хитов: <b>{stats['cache_hits']}</b> ({hit_ratio:.1f}%) · "
        f"Single-flight: {stats['inflight_joins']}"
    )
    lines.append(
        f"Rate limited: {stats['rate_limited']} · "
        f"Очередь отклонена: {stats['queue_rejections']}"
    )
    lines.append(
        f"Таймаутов: {stats['timeouts']} · "
        f"Ошибок рендера: {stats['render_errors']} · "
        f"Breaker-отказов: {stats['breaker_rejections']}"
    )
    lines.append(
        f"Circuit breaker: <code>{state['breaker_state']}</code> · "
        f"В полёте: {state['inflight']} · В очереди: {state['waiting']}"
    )
    lines.append(
        f"Кэш L1 (PNG): {state['cached_posters']} записей · "
        f"L2 (file_id): {state['cached_file_ids']} записей"
    )

    # Перцентили латентности (этап 5) — база для калибровки констант
    render_time = state.get("render_time")
    if render_time:
        lines.append(
            f"Рендер: p50 {render_time['p50_ms']:.0f} мс · "
            f"p95 {render_time['p95_ms']:.0f} мс · "
            f"p99 {render_time['p99_ms']:.0f} мс · "
            f"max {render_time['max_ms']:.0f} мс "
            f"({render_time['count']} замеров)"
        )
    queue_wait = state.get("queue_wait")
    if queue_wait:
        lines.append(
            f"Ожидание очереди: p50 {queue_wait['p50_ms']:.0f} мс · "
            f"p95 {queue_wait['p95_ms']:.0f} мс · "
            f"p99 {queue_wait['p99_ms']:.0f} мс"
        )
    return "\n".join(lines)
