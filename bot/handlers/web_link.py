# bot/handlers/web_link.py
import asyncio
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from bot import callbacks
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from config import Config
from services.profiles_service import ProfileService
from services.web_sessions_service import WebSessionsService

logger = logging.getLogger(__name__)
router = Router()

LOGIN_MESSAGE_TTL = 6 * 60  # сек; чуть больше TTL токена (5 мин)


@router.callback_query(F.data == callbacks.WEB_OPEN)
async def open_web_version(
    callback: CallbackQuery,
    bot: Bot,
    profile_service: ProfileService,
    config: Config,
    web_sessions_service: Optional[WebSessionsService] = None,
) -> None:
    # Защита: если WEB_ENABLED=0 в .env, сервис не инициализируется
    if web_sessions_service is None:
        await callback.answer("Веб-версия сейчас отключена на сервере 🛠", show_alert=True)
        return

    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    if not user_dto or not getattr(user_dto, "is_fully_registered", False):
        await callback.answer("Сначала завершите регистрацию.", show_alert=True)
        return

    # Phase MA: Открытие через Telegram Mini App (Web App)
    if getattr(config, "WEB_TG_APP_ENABLED", True):
        web_app_url = f"{config.WEB_PUBLIC_URL.rstrip('/')}/tg/app"
        
        text = UIRenderer.render_web_app_instructions()
        kb = Keyboards.get_web_app_kb(web_app_url)
        
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        return

    # Legacy fallback (WEB_TG_APP_ENABLED=0): прежний одноразовый magic link
    link = await web_sessions_service.create_login_link(
        user_id=callback.from_user.id,
        base_url=config.WEB_PUBLIC_URL,
    )
    message = await callback.message.answer(
        UIRenderer.render_web_login_instructions(
            login_link=link,
        ),
        parse_mode="HTML",
        protect_content=True,
    )
    await callback.answer()
    
    # Best-effort удаление bearer-сообщения после TTL токена
    asyncio.create_task(_delete_later(bot, message.chat.id, message.message_id))


# =====================================================================
# ФОЛБЭК ДЛЯ ТЕКСТОВОЙ КНОПКИ ГЛАВНОГО МЕНЮ
# Отрабатывает, если клиент Telegram не поддерживает прямой запуск WebApp
# из Reply-клавиатуры или произошел системный сбой запуска.
# =====================================================================
@router.message(F.text == '🌐 Веб-расписание')
async def handle_web_schedule_text(
    message: Message,
    bot: Bot,
    profile_service: ProfileService,
    config: Config,
    web_sessions_service: Optional[WebSessionsService] = None,
) -> None:
    # --- ВРЕМЕННЫЙ ПАТЧ ОБНОВЛЕНИЯ МЕНЮ ---
    from bot.handlers.registration import _show_main_menu
    await _show_main_menu(message, text="<i>🔄 Синхронизация меню...</i>")
    # --------------------------------------
    
    # Защита: если WEB_ENABLED=0 в .env, сервис не инициализируется
    if web_sessions_service is None:
        await message.answer("Веб-версия сейчас отключена на сервере 🛠")
        return

    user_dto = await profile_service.get_user_profile_dto(message.from_user.id)
    if not user_dto or not getattr(user_dto, "is_fully_registered", False):
        await message.answer("Сначала завершите регистрацию.")
        return

    # Phase MA: Предлагаем инлайн-кнопку запуска Mini App
    if getattr(config, "WEB_TG_APP_ENABLED", True):
        web_app_url = f"{config.WEB_PUBLIC_URL.rstrip('/')}/tg/app"
        
        text = UIRenderer.render_web_app_instructions()
        kb = Keyboards.get_web_app_kb(web_app_url)
        
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        return

    # Legacy fallback (WEB_TG_APP_ENABLED=0): одноразовый magic link
    link = await web_sessions_service.create_login_link(
        user_id=message.from_user.id,
        base_url=config.WEB_PUBLIC_URL,
    )
    sent_message = await message.answer(
        UIRenderer.render_web_login_instructions(
            login_link=link,
        ),
        parse_mode="HTML",
        protect_content=True,
    )
    
    # Best-effort удаление bearer-сообщения после TTL токена
    asyncio.create_task(_delete_later(bot, sent_message.chat.id, sent_message.message_id))


async def _delete_later(bot: Bot, chat_id: int, message_id: int) -> None:
    await asyncio.sleep(LOGIN_MESSAGE_TTL)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass  # best-effort; токен мёртв независимо от удаления