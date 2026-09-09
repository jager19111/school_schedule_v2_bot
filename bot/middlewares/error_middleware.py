# bot/middlewares/error_middleware.py
#
# ЭТАП 3: Глобальный перехват ошибок (Global Error Handling).
#
# ПРОБЛЕМА: непредвиденное исключение в любом хендлере (ValueError
# при парсинге, ошибка БД, опечатка) сейчас роняет хендлер молча:
# у пользователя висит спиннер на коллбэке, бот "не реагирует",
# в логе — traceback без контекста, пользователь не получает ответа.
#
# РЕШЕНИЕ: middleware на dp.update.outer_middleware оборачивает
# ВЕСЬ пайплайн обработки апдейта (message, callback_query,
# edited_message, my_chat_member) в try/except Exception.
#
# ГАРАНТИИ И ГРАНИЦЫ:
# - except Exception, НЕ BaseException: asyncio.CancelledError
#   (корректный shutdown) пролетает мимо и не глотается;
# - пользователю уходит render_system_error() БЕЗ деталей ошибки
#   (traceback в чат = утечка путей/SQL/данных — недопустимо);
# - полный traceback пишется в лог с контекстом
#   (update_id, user_id, callback_data/text);
# - отправка уведомления сама обёрнута в try: заблокировавший бот
#   пользователь не должен порождать ошибку в обработчике ошибки;
# - для CallbackQuery спиннер закрывается через answer(show_alert):
#   иначе у пользователя вечно висят "часики";
# - handler НЕ ретраится (идемпотентность неизвестна — повтор
#   рассылки означал бы дубль) и FSM НЕ сбрасывается (данные
#   пользователя дороже застрявшего флоу);
# - ошибки проглатываются (return None = обработано) — бот жив.
#
# РЕГИСТРАЦИЯ (main.py, сразу после dp = Dispatcher()):
#     from bot.middlewares.error_middleware import GlobalErrorMiddleware
#     dp.update.outer_middleware(GlobalErrorMiddleware())
#
# НЕ ЗАМЕНА локальным _safe_edit_text / _safe_callback_answer:
# ожидаемые TelegramBadRequest (message is not modified) обрабатываются
# локально как раньше — сюда долетает только неожиданное.

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, Update

from bot.utils.ui_renderer import UIRenderer

logger = logging.getLogger(__name__)


class GlobalErrorMiddleware(BaseMiddleware):
    """
    Оборачивает выполнение всего пайплайна обработки апдейта.

    Регистрируется один раз на dp.update.outer_middleware и ловит
    исключения из любого хендлера любого роутера.
    """

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception:
            # Полный traceback + контекст для воспроизведения.
            logger.exception(
                "Unhandled error in handler: %s",
                self._describe_update(event),
            )
            # Пользователь не должен остаться без обратной связи.
            # Ошибка уведомления НЕ должна порождать новую ошибку.
            try:
                await self._notify_user(event, data)
            except Exception:
                logger.debug(
                    "Failed to deliver error message to user",
                    exc_info=True,
                )
            # Ошибка обработана: апдейт не роняет поллинг.
            return None

    # --------------------------------------------------------------

    @staticmethod
    def _describe_update(update: Update) -> str:
        """Компактный контекст апдейта для строки лога."""
        try:
            if update.callback_query is not None:
                callback: CallbackQuery = update.callback_query
                callback_data = (callback.data or "")[:64]
                return (
                    f"update_id={update.update_id}, "
                    f"user_id={callback.from_user.id}, "
                    f"callback_data={callback_data!r}"
                )

            if update.message is not None:
                message: Message = update.message
                user_id = (
                    message.from_user.id
                    if message.from_user is not None
                    else None
                )
                text = (message.text or "")[:64]
                return (
                    f"update_id={update.update_id}, "
                    f"user_id={user_id}, "
                    f"text={text!r}"
                )
        except Exception:
            pass

        return f"update_id={update.update_id}"

    async def _notify_user(
        self,
        update: Update,
        data: dict[str, Any],
    ) -> None:
        """
        Отправляет пользователю сообщение об ошибке.

        Message -> новое сообщение в тот же чат.
        CallbackQuery -> сначала alert (закрывает спиннер);
        если alert не прошёл (коллбэк старый) и есть исходное
        сообщение -> сообщением в чат.
        my_chat_member и прочие "безликие" апдейты -> без уведомления.
        """
        bot = data.get("bot")
        if bot is None:
            return

        # 1. Обычное сообщение.
        if update.message is not None:
            await bot.send_message(
                chat_id=update.message.chat.id,
                text=UIRenderer.render_system_error(),
                parse_mode="HTML",
            )
            return

        # 2. Коллбэк: закрываем спиннер алертом.
        callback = update.callback_query
        if callback is None:
            return

        try:
            await callback.answer(
                text=UIRenderer.render_system_error_plain(),
                show_alert=True,
            )
            return
        except Exception:
            # Коллбэк мог протухнуть (answer работает ограниченное время)
            # или уже был отвечен — пробуем сообщением в чат.
            logger.debug(
                "Error callback.answer failed, falling back to message",
                exc_info=True,
            )

        if callback.message is not None:
            await bot.send_message(
                chat_id=callback.message.chat.id,
                text=UIRenderer.render_system_error(),
                parse_mode="HTML",
            )
