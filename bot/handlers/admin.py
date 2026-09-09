# bot/handlers/admin.py
#
# ИЗМЕНЕНИЯ:
# 1. НОВАЯ команда /stress [count] — стресс-тест боевого пайплайна
#    уведомлений. Отправка идёт через NotificationService.debug_send_burst,
#    то есть через paced send, батчевый dedup и delivery log —
#    в отличие от message.answer(), который эти слои обходит.
#    Тестирует: лимиты Telegram (429), дросселирование, идемпотентность
#    на рестарте (ключи стабильны в течение дня).
#

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.utils.ui_renderer import UIRenderer
from services.admin_service import AdminService
from services.notifications_service import NotificationService
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


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
) -> None:
    """
    Общая статистика пользователей.
    """
    if not await _require_admin(
        message=message,
        admin_service=admin_service,
    ):
        return

    dto = await admin_service.get_statistics()

    text = UIRenderer.render_admin_stats(
        dto,
    )

    await message.answer(
        text,
        parse_mode="HTML",
    )


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

    /stress      — 50 сообщений по умолчанию;
    /stress 100  — указанное количество (1..500).

    Что проверяет:
    - дросселирование (глобальный темп + 1 сообщение/сек на чат);
    - обработку 429 Too Many Requests;
    - идемпотентность на рестарте: прерви тест Ctrl+C, перезапусти
      бота и запусти снова — рассылка продолжится с места остановки,
      а не начнётся сначала (дедупликация через delivery log).

    Время выполнения ~ count * 1.1 сек из-за пер-чат лимита Telegram.
    """
    if not await _require_admin(
        message=message,
        admin_service=admin_service,
    ):
        return

    parts = (message.text or "").split()

    count = 100
    if len(parts) > 1 and parts[1].isdigit():
        count = int(parts[1])

    count = max(1, min(count, MAX_STRESS_COUNT))
    estimated_seconds = int(count * PER_CHAT_SEND_INTERVAL_SEC)

    logger.info(
        "Stress test started: user_id=%s, count=%d",
        message.from_user.id,
        count,
    )

    await message.answer(
        "🧪 <b>Стресс-тест пайплайна уведомлений</b>\n\n"
        f"Сообщений: {count}\n"
        f"Оценка времени: ~{estimated_seconds} сек "
        "(лимит Telegram: 1 сообщение/сек на чат).\n\n"
        "Отправка идёт через боевой конвейер: дросселирование, "
        "батчевая дедупликация, delivery log.\n\n"
        "Для теста рестарта: прервите бота на середине (Ctrl+C), "
        "запустите снова и выполните команду ещё раз — "
        "рассылка продолжится с места остановки."
    )

    result = await notification_service.debug_send_burst(
        chat_id=message.from_user.id,
        count=count,
    )

    await message.answer(
        "🧪 <b>Стресс-тест завершён</b>\n\n"
        f"Запрошено: {result['requested']}\n"
        f"К отправке после дедупликации: {result['pending']}\n"
        f"Отправлено: {result['sent']}\n"
        f"Ошибок: {result['failed']}\n\n"
        "Если 'к отправке' меньше 'запрошено' — дедупликация "
        "отработала (это уже отправленные сегодня сообщения)."
    )

    logger.info(
        "Stress test finished: user_id=%s, result=%s",
        message.from_user.id,
        result,
    )


@router.message(Command("test_btn"))
async def send_test_button(message: Message):
    """Временная команда для быстрого вызова любого коллбэка."""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Тест смены класса",
                callback_data="settings:main" # Меняйте это значение на нужное
            )
        ]]
    )
    await message.answer("Жми:", reply_markup=kb)
