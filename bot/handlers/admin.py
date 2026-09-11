# bot/handlers/admin.py
#
# ИЗМЕНЕНИЯ:
# 1. НОВАЯ команда /stress [count] — стресс-тест боевого пайплайна
#    уведомлений. Отправка идёт через NotificationService.debug_send_burst,
#    то есть через paced send, батчевый dedup и delivery log —
#    в отличие от message.answer(), который эти слои обходит.
#    Тестирует: лимиты Telegram (429), дросселирование, идемпотентность
#    на рестарте (ключи стабильны в течение дня).
# /stats показывает статистику
# DEBUG-команды для быстрой проверки UI уведомлений.
#/debug_ui            — всё сразу
#/debug_ui morning    — утренние сводки: вид родителя, вид ребёнка,
#/debug_ui change     — замена (родитель), отмена (ребёнок),
#                        два ребёнка в одном сообщении, день без уроков
#                        замена по watch-target, замена у учителя
#/debug_ui lesson     — начало урока (ребёнок/родитель), доп. занятие
# /source_status - показывает статус актуальности кеша в  
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from datetime import datetime

from bot.utils.ui_renderer import UIRenderer
from services.admin_service import AdminService
from services.notifications_service import NotificationService
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


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

    await message.answer(
        "🧪 <b>Стресс-тест пайплайна уведомлений</b>\n\n"
        f"Получатель (chat_id): <code>{target_chat_id}</code>\n"
        f"Сообщений: {count}\n"
        f"Оценка времени: ~{estimated_seconds} сек.\n\n"
        "Для теста рестарта: прервите бота на середине (Ctrl+C), "
        "запустите снова и выполните команду ещё раз."
    )

    # Используем извлеченный target_chat_id вместо message.from_user.id
    result = await notification_service.debug_send_burst(
        chat_id=target_chat_id,
        count=count,
    )

    await message.answer(
        "🧪 <b>Стресс-тест завершён</b>\n\n"
        f"Получатель: <code>{target_chat_id}</code>\n"
        f"Запрошено: {result['requested']}\n"
        f"К отправке после дедупликации: {result['pending']}\n"
        f"Отправлено: {result['sent']}\n"
        f"Ошибок: {result['failed']}"
    )

    logger.info(
        "Stress test finished: admin_id=%s, target_id=%s, result=%s",
        message.from_user.id,
        target_chat_id,
        result,
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

@router.message(Command("test_btn"))
async def send_test_button(message: Message):
    """Временная команда для быстрого вызова любого коллбэка."""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Тест смены класса",
                callback_data="" # Меняйте это значение на нужное
            )
        ]]
    )
    await message.answer("Жми:", reply_markup=kb)


@router.message(Command("test_fallback"))
async def cmd_test_fallback(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Кнопка-призрак", callback_data="non_existent_callback_123")]
    ])
    await message.answer("Жми:", reply_markup=kb)