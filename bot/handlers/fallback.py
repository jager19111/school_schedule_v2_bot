# bot/handlers/fallback.py
#
# ЭТАП 7: последний router callback-пайплайна.
# Ловит устаревшие, поддельные или невалидные CallbackData,
# которые не совпали с XxxCD.filter().
#
# Обязательно зарегистрировать последним в main.py.

import logging

from aiogram import Router
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query()
async def unhandled_callback(callback: CallbackQuery) -> None:
    """
    Последний рубеж: коллбэк не распознан ни одним роутером.

    Тихий toast (не alert) — пользователь не пугается,
    спиннер гарантированно закрывается.
    """
    logger.info(
        "Unhandled callback_query: user_id=%s data=%r",
        callback.from_user.id,
        (callback.data or "")[:64],
    )
    try:
        await callback.answer(
            "Кнопка устарела или недоступна. Откройте меню заново.",
        )
    except Exception:
        logger.debug("Fallback callback answer skipped", exc_info=True)
