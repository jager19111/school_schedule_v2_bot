# services/web_sessions_service.py
#
# Бизнес-логика web-аутентификации:
# - генерация/потребление одноразовых magic-link токенов (SHA-256, TTL 5 мин);
# - создание/резолвция/отзыв opaque-сессий (multi-device, idle+absolute TTL);
# - CSRF-токены (stateless HMAC, session-bound, не пишутся в БД).
#
# ПРАВИЛА ПРОЕКТА (сверено с baseline 588700f):
# - сервис не содержит SQL (всё через WebAuthRepository);
# - ВРЕМЯ: только через TimeService. Формат БД — "YYYY-MM-DD HH:MM:SS"
#   (TimeService.now_utc_str / utc_str_from). Никаких ISO-строк с 'T':
#   смешение форматов ломает лексикографические сравнения в SQL
#   (проверено тестом test_mixed_timestamp_format_breaks_comparisons);
# - все репозитории работают через ЕДИНОЕ shared aiosqlite-соединение,
#   созданное в main.py (WebAuthRepository получает объект Connection,
#   а не db_path-строку);
# - роли/права НЕ хранятся в сессии, разрешаются на каждом запросе
#   через ProfileService (web/deps.py).

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from core.repository.web_auth_repository import WebAuthRepository
from services.time_service import TimeService

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "web_session"

# Токены генерируются криптографическим ГСЧ; в БД — только SHA-256.
_LOGIN_TOKEN_BYTES = 32  # >= 32 random bytes по ТЗ
_SESSION_TOKEN_BYTES = 32

_LOGIN_TOKEN_TTL = timedelta(minutes=5)
_SESSION_IDLE_TTL = timedelta(days=90)
_SESSION_ABSOLUTE_TTL = timedelta(days=365)
# last_seen_at обновляется не чаще одного раза в ~5 минут (решение Phase 0).
_TOUCH_THRESHOLD = timedelta(minutes=5)


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _to_str(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@dataclass(frozen=True, slots=True)
class WebSessionContext:
    """Результат резолвции сессии (actor-контекст запроса)."""

    session_id: int
    session_hash: str
    user_id: int
    csrf_token: str


@dataclass(frozen=True, slots=True)
class WebDeviceInfo:
    """Элемент списка активных устройств (без secrets)."""

    session_id: int
    user_agent: str
    created_at: Optional[str]
    last_seen_at: Optional[str]
    current: bool


class WebSessionsService:
    """
    Web-сессии поверх существующей users-модели.

    Один Telegram user -> N web sessions (multi-device).
    Login нового устройства никогда не отзывает существующие сессии.
    """

    def __init__(
        self,
        repo: WebAuthRepository,
        time_service: TimeService,
        *,
        csrf_secret: str,
    ) -> None:
        if not csrf_secret or len(csrf_secret) < 32:
            raise ValueError(
                "WEB_CSRF_SECRET обязателен и >= 32 символов "
                "(сгенерируйте: python -c \"import secrets; "
                "print(secrets.token_urlsafe(48))\")"
            )
        self.repo = repo
        self.time_service = time_service
        self._csrf_secret = csrf_secret

    # ==========================================================
    # Время (единый источник — TimeService, формат SQLite)
    # ==========================================================

    def _now_utc(self) -> datetime:
        """aware-UTC сейчас (арифметика TTL)."""
        return TimeService.to_utc(self.time_service.get_now_base())

    def _fmt(self, dt: datetime) -> str:
        """aware datetime -> "YYYY-MM-DD HH:MM:SS" (формат проекта)."""
        result = self.time_service.utc_str_from(dt)
        assert result is not None
        return result

    def _now_str(self) -> str:
        return self.time_service.now_utc_str()

    # ==========================================================
    # Magic link (кнопка «🌐 Открыть веб-версию» в боте)
    # ==========================================================

    async def create_login_link(self, *, user_id: int, base_url: str) -> str:
        """
        Генерирует одноразовую ссылку `{base_url}/auth#token=RAW`.

        Raw-токен существует только в ссылке; в БД — SHA-256.
        base_url берётся из WEB_PUBLIC_URL (никогда не хардкодится).
        """
        raw = secrets.token_urlsafe(_LOGIN_TOKEN_BYTES)
        expires_at = self._now_utc() + _LOGIN_TOKEN_TTL
        await self.repo.create_login_token(
            token_hash=_sha256(raw),
            user_id=user_id,
            expires_at_utc=self._fmt(expires_at),
        )
        return f"{base_url.rstrip('/')}/auth#token={raw}"

    async def exchange_login_token(self, raw_token: str) -> Optional[int]:
        """
        Одноразовый обмен magic-link токена на user_id.

        Атомарный consume внутри репозитория (UPDATE WHERE used=0 AND
        expires_at>now в транзакции): повторное использование, истёкший
        или неизвестный токен -> None (route вернёт 401 c обобщённым
        сообщением). Конкурентные exchange одного токена: побеждает
        ровно один (см. test_concurrent_exchange_same_token).
        """
        if not raw_token or len(raw_token) > 256:
            return None
        return await self.repo.consume_login_token(
            token_hash=_sha256(raw_token.strip()),
            now_utc=self._now_str(),
        )

    # ==========================================================
    # Сессии
    # ==========================================================

    async def create_session(
        self,
        *,
        user_id: int,
        user_agent: Optional[str] = None,
    ) -> tuple[str, WebSessionContext]:
        """
        Создаёт новую сессию.

        Возвращает (raw_cookie_token, context): raw уходит ТОЛЬКО в
        HttpOnly cookie и больше нигде не хранится; в БД — SHA-256.
        """
        now = self._now_utc()
        raw = secrets.token_urlsafe(_SESSION_TOKEN_BYTES)
        session_hash = _sha256(raw)
        session_id = await self.repo.create_session(
            session_hash=session_hash,
            user_id=user_id,
            idle_expires_at_utc=self._fmt(now + _SESSION_IDLE_TTL),
            absolute_expires_at_utc=self._fmt(now + _SESSION_ABSOLUTE_TTL),
            user_agent=user_agent,
        )
        return raw, WebSessionContext(
            session_id=session_id,
            session_hash=session_hash,
            user_id=user_id,
            csrf_token=self._csrf_token(session_hash),
        )

    async def resolve_session(self, raw_token: str) -> Optional[WebSessionContext]:
        """
        Валидация сессии на каждом authenticated request.

        Проверки (обе в SQL): not revoked, idle_expires_at > now,
        absolute_expires_at > now.
        Обновление активности: last_seen_at И idle_expires_at = now +
        idle TTL (только last_seen недостаточно — иначе idle timeout
        выродился бы в lifetime timeout). Throttling: не чаще 1 UPDATE
        в ~5 минут.
        """
        if not raw_token or len(raw_token) > 256:
            return None
        now = self._now_utc()
        now_str = self._now_str()
        raw = raw_token.strip()
        row = await self.repo.get_valid_session_by_hash(
            session_hash=_sha256(raw),
            now_utc=now_str,
        )
        if row is None:
            return None

        await self.repo.touch_session(
            session_id=int(row["id"]),
            now_utc=now_str,
            idle_expires_at_utc=self._fmt(now + _SESSION_IDLE_TTL),
            touch_threshold_utc=self._fmt(now - _TOUCH_THRESHOLD),
        )
        session_hash = _sha256(raw)
        return WebSessionContext(
            session_id=int(row["id"]),
            session_hash=session_hash,
            user_id=int(row["user_id"]),
            csrf_token=self._csrf_token(session_hash),
        )

    async def revoke_session(self, *, raw_token: str, user_id: int) -> bool:
        """Logout текущего устройства (отзывает только эту сессию)."""
        return await self.repo.revoke_session_by_hash(
            session_hash=_sha256(raw_token.strip()),
            user_id=user_id,
        )

    async def revoke_session_by_id(self, *, session_id: int, user_id: int) -> bool:
        """Отзыв конкретной сессии из device list (владелец — в SQL)."""
        return await self.repo.revoke_session_by_id(
            session_id=session_id, user_id=user_id
        )

    async def revoke_all_sessions(self, *, user_id: int) -> int:
        """Logout на всех устройствах."""
        return await self.repo.revoke_all_sessions_for_user(user_id=user_id)

    async def list_devices(
        self,
        *,
        user_id: int,
        current_session_hash: str,
    ) -> List[WebDeviceInfo]:
        """Список активных устройств для Settings; текущее помечено."""
        rows = await self.repo.get_active_sessions_for_user(
            user_id=user_id,
            now_utc=self._now_str(),
        )
        return [
            WebDeviceInfo(
                session_id=int(r["id"]),
                user_agent=str(r.get("user_agent") or "Неизвестное устройство"),
                created_at=_to_str(r.get("created_at")),
                last_seen_at=_to_str(r.get("last_seen_at")),
                current=str(r.get("session_hash")) == current_session_hash,
            )
            for r in rows
        ]

    # ==========================================================
    # CSRF (stateless HMAC; session-bound, не совпадает с session token)
    # ==========================================================

    def _csrf_token(self, session_hash: str) -> str:
        """
        CSRF-токен привязан К КОНКРЕТНОЙ сессии: HMAC(secret,
        session_hash). Session_hash уникален для каждой сессии,
        поэтому токен одной сессии не подходит другой (проверено
        test_csrf_token_is_session_bound). Не timestamp, не глобальный.
        """
        return hmac.new(
            self._csrf_secret.encode("utf-8"),
            session_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify_csrf(self, *, session_hash: str, provided_token: str) -> bool:
        expected = self._csrf_token(session_hash)
        return hmac.compare_digest(expected, provided_token or "")

    # ==========================================================
    # Cleanup (scheduled, не из HTTP request)
    # ==========================================================

    async def cleanup(self) -> dict:
        return await self.repo.cleanup_web_auth(now_utc=self._now_str())
