import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

from bot import callbacks
from bot.keyboards.keyboard import Keyboards
from bot.utils.ui_renderer import UIRenderer
from services.help_service import HelpService
from services.profiles_service import ProfileService

router = Router()
logger = logging.getLogger(__name__)


async def _safe_edit_help_message(
    *,
    message: Message,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> bool:
    """
    Безопасно обновляет сообщение справки.

    Пользователь может повторно нажать активный раздел,
    например «К оглавлению», когда оглавление уже открыто.
    Telegram в таком случае отвечает message is not modified.
    Это нормальная ситуация, а не ошибка приложения.
    """
    try:
        await message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return True
    except TelegramBadRequest as exc:
        error_text = str(exc).lower()

        if "message is not modified" in error_text:
            logger.debug(
                "Help message already has requested content."
            )
            return False

        logger.warning(
            "Unable to edit help message: %s",
            exc,
        )
        return False


async def _resolve_help_role(
    *,
    user_id: int,
    profile_service: ProfileService,
) -> str | None:
    user_dto = await profile_service.get_user_profile_dto(
        user_id,
    )

    # Этап 4: роутинный путь — debug, не warning (шум в логах убран).
    logger.debug(
        "Help role resolve: user_id=%s role=%r "
        "registered=%r family_id=%r class_id=%r teacher_id=%r",
        user_id,
        user_dto.role,
        user_dto.is_fully_registered,
        user_dto.family_id,
        user_dto.class_id,
        user_dto.teacher_id,
    )

    if not user_dto.is_fully_registered:
        return None

    return user_dto.role


async def show_help(
    *,
    message: Message,
    actor_user_id: int,
    section: str,
    profile_service: ProfileService,
    help_service: HelpService,
    edit_message: bool,
) -> None:
    role = await _resolve_help_role(
        user_id=actor_user_id,
        profile_service=profile_service,
    )

    dto = help_service.get_page(
        section=section,
        role=role,
    )

    text = UIRenderer.render_help_page(
        dto,
    )

    keyboard = Keyboards.get_help_kb(
        links=dto.links,
        role=dto.role,
        section=dto.section,
        show_back_to_settings=(
            dto.role is not None
        ),
    )

    if edit_message:
        await _safe_edit_help_message(
            message=message,
            text=text,
            keyboard=keyboard,
        )
        return

    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def command_help(
    message: Message,
    profile_service: ProfileService,
    help_service: HelpService,
) -> None:
    await show_help(
        message=message,
        actor_user_id=message.from_user.id,
        section="main",
        profile_service=profile_service,
        help_service=help_service,
        edit_message=False,
    )


@router.callback_query(F.data.startswith(callbacks.HELP_PREFIX))
async def callback_help(
    callback: CallbackQuery,
    profile_service: ProfileService,
    help_service: HelpService,
) -> None:
    # Этап 4: парсинг и whitelist разделов — в callbacks.parse_help.
    section = callbacks.parse_help(callback.data)
    if section is None:
        await callback.answer(
            "Раздел справки не найден.",
            show_alert=True,
        )
        return

    await show_help(
        message=callback.message,
        actor_user_id=callback.from_user.id,
        section=section,
        profile_service=profile_service,
        help_service=help_service,
        edit_message=True,
    )
    await callback.answer()
