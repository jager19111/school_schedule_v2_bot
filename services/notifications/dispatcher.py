# services/notification/dispatcher.py

import asyncio
import logging
import time
from typing import Optional
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from core.repository.notification_repository import NotificationRepository

logger = logging.getLogger(__name__)

class NotificationDispatcher:
    """
    Диспетчер отправки. Отвечает только за взаимодействие с Telegram API:
    лимиты (Smart Throttling), блокировки (Lock), сетевые ошибки и алерты админам.
    """
    
    GLOBAL_SEND_INTERVAL_SEC = 0.045
    PER_CHAT_SEND_INTERVAL_SEC = 1.1
    MAX_SEND_ATTEMPTS = 3
    _CHAT_CACHE_MAX = 1000
    _CHAT_CACHE_TTL_SEC = 600.0
    ADMIN_ALERT_COOLDOWN_SEC = 3600.0

    def __init__(
        self,
        bot: Bot,
        notification_repo: NotificationRepository,
        admin_ids: Optional[list[int]] = None,
    ) -> None:
        self.bot = bot
        self.repo = notification_repo
        self._admin_ids = list(admin_ids or [])
        
        self._send_lock = asyncio.Lock()
        self._global_last_send_at = 0.0
        self._chat_last_send_at: dict[int, float] = {}
        self._last_admin_alert_at: dict[str, float] = {}

    def _prune_chat_send_times(self) -> None:
        """Микроочистка кеша per-chat таймстемпов."""
        if len(self._chat_last_send_at) < self._CHAT_CACHE_MAX:
            return
        cutoff = time.monotonic() - self._CHAT_CACHE_TTL_SEC
        self._chat_last_send_at = {
            chat_id: ts
            for chat_id, ts in self._chat_last_send_at.items()
            if ts > cutoff
        }

    def _build_keyboard(self, action_type: str | None, payload: dict | None) -> Optional[InlineKeyboardMarkup]:
        """Превращает абстрактное намерение (action_type) в физическую клавиатуру Telegram."""
        if not action_type or not payload:
            return None
            
        if action_type == "day_changes":
            from bot import callbacks
            from bot.keyboards.keyboard import Keyboards
            
            try:
                cb_data = callbacks.DayChangesCD(
                    target_kind=payload["target_kind"],
                    target_id=payload["target_id"],
                    class_id=payload["class_id"],
                    group_id=payload["group_id"],
                    date_iso=payload["date_iso"],
                    origin=payload["origin"],
                    return_to=payload.get("return_to", "morning"),
                )
                return Keyboards.get_day_changes_kb(cb_data)
            except Exception as e:
                logger.error("Render error: Failed to build keyboard for action %s: %s", action_type, e)
                return None
            
        return None

    async def send(
        self, 
        chat_id: int, 
        text: str, 
        action_type: str | None = None,
        action_payload: dict | None = None
    ) -> bool:
        """Paced-отправка с соблюдением лимитов Telegram."""
        keyboard = self._build_keyboard(action_type, action_payload)
        
        async with self._send_lock:
            for attempt in range(1, self.MAX_SEND_ATTEMPTS + 1):
                now_mono = time.monotonic()

                wait_global = (self._global_last_send_at + self.GLOBAL_SEND_INTERVAL_SEC) - now_mono
                wait_chat = (self._chat_last_send_at.get(chat_id, 0.0) + self.PER_CHAT_SEND_INTERVAL_SEC) - now_mono
                wait = max(wait_global, wait_chat, 0.0)
                
                if wait > 0:
                    await asyncio.sleep(wait)

                try:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                    finished_at = time.monotonic()
                    self._global_last_send_at = finished_at
                    self._chat_last_send_at[chat_id] = finished_at
                    self._prune_chat_send_times()
                    return True

                except TelegramRetryAfter as exc:
                    logger.warning(
                        "Send error: Telegram 429 flood control (chat_id=%s, retry_after=%ss, attempt=%d/%d)",
                        chat_id, exc.retry_after, attempt, self.MAX_SEND_ATTEMPTS,
                    )
                    if attempt < self.MAX_SEND_ATTEMPTS:
                        await asyncio.sleep(float(exc.retry_after) + 0.5)

                except TelegramForbiddenError:
                    logger.warning("Access error: Chat %s blocked the bot. Marking user as blocked.", chat_id)
                    try:
                        await self.repo.mark_user_notifications_blocked(user_id=chat_id)
                    except Exception as e:
                        logger.error("Infrastructure error: Failed to mark blocked chat %s: %s", chat_id, e)
                    return False

                except TelegramBadRequest as exc:
                    logger.warning("Send error: Telegram rejected message (chat_id=%s, error=%s)", chat_id, exc)
                    return False

                except (TelegramNetworkError, asyncio.TimeoutError, OSError) as exc:
                    logger.warning(
                        "Infrastructure error: Network error sending to chat %s (attempt %d/%d): %s",
                        chat_id, attempt, self.MAX_SEND_ATTEMPTS, exc,
                    )
                    await asyncio.sleep(0.5 * attempt)

            logger.error("Send error: Giving up sending to chat %s after %d attempts", chat_id, self.MAX_SEND_ATTEMPTS)
            return False

    async def send_admin_alert(self, alert_key: str, text: str) -> None:
        """Дедуплицированный алерт всем админам."""
        if not self._admin_ids:
            return

        now_mono = time.monotonic()
        last_sent_at = self._last_admin_alert_at.get(alert_key)
        if last_sent_at is not None and (now_mono - last_sent_at) < self.ADMIN_ALERT_COOLDOWN_SEC:
            return
        self._last_admin_alert_at[alert_key] = now_mono

        for admin_id in self._admin_ids:
            sent = await self.send(chat_id=admin_id, text=text)
            if not sent:
                logger.warning("Send error: Admin alert not delivered (admin_id=%s, key=%s)", admin_id, alert_key)