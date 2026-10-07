# services/browser_handoff_service.py
#
# Одноразовые коды перехода Mini App -> внешний браузер.
#
# Паттерн повторяет magic-link login (WebSessionsService), но
# назначение другое: код живёт 120 секунд и обменивается в /tg/browser
# consume-route на обычную browser-сессию. Raw-код существует только
# в URL consume; в БД — SHA-256.
#
# target_path — закрытый allowlist, никаких произвольных redirect URL.

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from core.repository.browser_handoff_repository import BrowserHandoffRepository
from services.time_service import TimeService

logger = logging.getLogger(__name__)

_HANDOFF_CODE_BYTES = 32
_HANDOFF_TTL = timedelta(seconds=120)

ALLOWED_TARGET_PATHS = frozenset(
    {
        "/",
        "/school",
        "/school/free-rooms",
        "/extra-classes",
    }
)


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class HandoffPayload:
    user_id: int
    target_path: str


class BrowserHandoffService:
    def __init__(
        self,
        repo: BrowserHandoffRepository,
        time_service: TimeService,
    ) -> None:
        self.repo = repo
        self.time_service = time_service

    def _now_utc(self):
        return TimeService.to_utc(self.time_service.get_now_base())

    def _fmt(self, dt) -> str:
        result = self.time_service.utc_str_from(dt)
        assert result is not None
        return result

    async def issue_handoff(
        self,
        *,
        user_id: int,
        target_path: str = "/",
    ) -> str:
        """
        Создаёт одноразовый handoff-код, возвращает RAW.

        Raw уходит только в external_url для Telegram.WebApp.openLink()
        и больше нигде не хранится.
        """
        safe_target = (
            target_path
            if target_path in ALLOWED_TARGET_PATHS
            else "/"
        )
        raw = secrets.token_urlsafe(_HANDOFF_CODE_BYTES)
        expires_at = self._now_utc() + _HANDOFF_TTL
        await self.repo.create_handoff_code(
            code_hash=_sha256(raw),
            user_id=user_id,
            target_path=safe_target,
            expires_at_utc=self._fmt(expires_at),
        )
        # Лог — только fingerprint, не raw.
        logger.info(
            "Browser handoff issued: user_id=%s target=%s",
            user_id,
            safe_target,
        )
        return raw

    async def consume_handoff(
        self,
        raw_code: str,
    ) -> Optional[HandoffPayload]:
        """
        Одноразовое потребление кода.

        Replay / истёкший / неизвестный код -> None (route вернёт
        нейтральную страницу с предложением вернуться в Telegram).
        """
        if not raw_code or len(raw_code) > 256:
            return None
        row = await self.repo.consume_handoff_code(
            code_hash=_sha256(raw_code.strip()),
            now_utc=self.time_service.now_utc_str(),
        )
        if row is None:
            return None
        return HandoffPayload(
            user_id=int(row["user_id"]),
            target_path=str(row.get("target_path") or "/"),
        )
        
    async def cleanup(self) -> int:
        """Scheduled-очистка истёкших/использованных кодов."""
        return await self.repo.cleanup_browser_handoff(
            now_utc=self.time_service.now_utc_str(),
        )