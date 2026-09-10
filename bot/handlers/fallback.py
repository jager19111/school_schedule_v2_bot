# bot/handlers/fallback.py
#
# ЭТАП 4.5: catch-all обработчик коллбэков (последний рубеж).
#
# ПРОБЛЕМА: коллбэк, не совпавший ни с одним хендлером
# (старая кнопка от прошлой версии бота, повреждённые данные,
# кнопка FSM-флоу при неправильном состоянии), оставляет
# пользователю ВЕЧНЫЙ СПИННЕР — aiogram не отвечает на
# callback query автоматически.
#
# РЕШЕНИЕ: роутер с безусловным фильтром, регистрируемый
# ПОСЛЕДНИМ в main.py. Любой неопознанный коллбэк получает
# тихий toast вместо спиннера.
#
# Это же — предусловие миграции на aiogram CallbackData
# (предложение 3): невалидные данные там тихо не совпадают
# с фильтром и падают сюда.
#
# РЕГИСТРАЦИЯ (main.py, ПОСЛЕДНЕЙ строкой после search):
#     from bot.handlers import fallback
#     dp.include_router(fallback.router)

import logging

from aiogram import F, Router
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
            "Кнопка устарела или недоступна. "
            "Откройте меню заново.",
        )
    except Exception:
        # Query мог протухнуть — спиннер в Telegram закрылся сам.
        logger.debug("Fallback callback answer skipped", exc_info=True)
