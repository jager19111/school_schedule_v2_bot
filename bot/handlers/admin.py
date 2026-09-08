# bot/handlers/admin.py
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.utils.ui_renderer import UIRenderer
from services.admin_service import AdminService
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


logger = logging.getLogger(__name__)
router = Router()


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
        # Убираем reply_markup=keyboard, так как клавиатуры здесь нет
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