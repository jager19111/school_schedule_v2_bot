# bot/handlers/web_link.py
import asyncio
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from bot import callbacks
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

    link = await web_sessions_service.create_login_link(
        user_id=callback.from_user.id,
        base_url=config.WEB_PUBLIC_URL,
    )
    message = await callback.message.answer(
        "🌐 <b>Вход в веб-версию</b>\n\n"
        "Ссылка одноразовая и действует 5 минут. "
        "Никому её не пересылайте.\n\n"
        f"{link}",
        parse_mode="HTML",
        protect_content=True,
    )
    await callback.answer()
    
    # Best-effort удаление bearer-сообщения после TTL токена
    asyncio.create_task(_delete_later(bot, message.chat.id, message.message_id))


async def _delete_later(bot: Bot, chat_id: int, message_id: int) -> None:
    await asyncio.sleep(LOGIN_MESSAGE_TTL)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass  # best-effort; токен мёртв независимо от удаления