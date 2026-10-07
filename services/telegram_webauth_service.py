# services/telegram_webauth_service.py
#
# Валидация Telegram Mini App initData -> user_id проекта.
#
# Алгоритм: официальная схема Telegram Web Apps:
#   secret_key   = HMAC-SHA256(key="WebAppData", msg=<bot_token>)
#   valid_hash   = HMAC-SHA256(key=secret_key, msg=data_check_string)
#   data_check_string = все параметры initData, кроме hash,
#                       отсортированные по алфавиту, "key=value" через \n
#
# user.id из initData == user_id проекта (Telegram user id).
#
# ПРАВИЛА ПРОЕКТА: время только через TimeService; никаких секретов
# в логах; обобщённые ошибки наружу.

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
from urllib.parse import parse_qsl

from services.time_service import TimeService

logger = logging.getLogger(__name__)

_INIT_DATA_MAX_LENGTH = 16_384
_AUTH_DATE_TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class TelegramWebIdentity:
    """Результат успешной валидации initData."""

    user_id: int
    auth_date: int


class TelegramWebAuthService:
    """Без state: чистая валидация подписи Telegram initData."""

    def __init__(
        self,
        time_service: TimeService,
        *,
        bot_token: str,
    ) -> None:
        if not bot_token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN обязателен для Mini App авторизации."
            )
        self.time_service = time_service
        self._bot_token = bot_token

    def validate_init_data(
        self,
        raw_init_data: str,
    ) -> Optional[TelegramWebIdentity]:
        """
        Возвращает identity или None (подпись невалидна / устарела).

        Никаких различий в тексте ошибок между причинами — наружу
        только обобщённый отказ.
        """
        if not raw_init_data or len(raw_init_data) > _INIT_DATA_MAX_LENGTH:
            return None

        try:
            params = dict(parse_qsl(raw_init_data, keep_blank_values=True))
        except Exception:
            return None

        received_hash = params.pop("hash", None)
        if not received_hash:
            return None

        user_raw = params.get("user")
        auth_date_raw = params.get("auth_date")
        if not user_raw or not auth_date_raw:
            return None

        # 1. Подпись.
        data_check_string = "\n".join(
            f"{key}={value}"
            for key, value in sorted(params.items())
        )
        secret_key = hmac.new(
            b"WebAppData",
            self._bot_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        # 2. Свежесть auth_date (защита от replay старых initData).
        try:
            auth_date = int(auth_date_raw)
        except ValueError:
            return None
        now_ts = TimeService.to_utc(
            self.time_service.get_now_base()
        ).timestamp()
        if abs(now_ts - auth_date) > _AUTH_DATE_TTL.total_seconds():
            return None

        # 3. Telegram user -> user_id проекта (совпадают по построению).
        import json
        try:
            user_payload = json.loads(user_raw)
            user_id = int(user_payload["id"])
        except Exception:
            return None

        return TelegramWebIdentity(user_id=user_id, auth_date=auth_date)