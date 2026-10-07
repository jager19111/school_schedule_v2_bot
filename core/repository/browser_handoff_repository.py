# core/repository/browser_handoff_repository.py
#
# SQL-слой Telegram Mini App -> внешний браузер (browser_handoff_codes).
#
# Паттерн полностью повторяет web_login_tokens:
# - в БД только SHA-256 raw-кода;
# - одноразовый atomic consume в транзакции;
# - время строками проекта "YYYY-MM-DD HH:MM:SS";
# - только SQL, без бизнес-логики (она в services/browser_handoff_service.py).

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from core.repository.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class BrowserHandoffRepository(BaseRepository):
    """Таблица browser_handoff_codes (одноразовые handoff-коды)."""

    async def create_handoff_code(
        self,
        *,
        code_hash: str,
        user_id: int,
        target_path: str,
        expires_at_utc: str,
    ) -> None:
        await self._execute(
            """
            INSERT INTO browser_handoff_codes
                (code_hash, user_id, target_path, created_at,
                 expires_at, used)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                code_hash,
                user_id,
                target_path,
                self._now_utc_str(),
                expires_at_utc,
            ),
        )

    async def consume_handoff_code(
        self,
        *,
        code_hash: str,
        now_utc: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Атомарный одноразовый consume (образец consume_login_token).

        UPDATE ... WHERE used = 0 AND expires_at > now: replay и
        истёкшие коды не проходят; конкурирующие consume — побеждает
        ровно один. Возвращает {'user_id': int, 'target_path': str}
        или None.
        """
        async with self.transaction() as db:
            cursor = await db.execute(
                """
                UPDATE browser_handoff_codes
                SET used = 1, used_at = ?
                WHERE code_hash = ?
                  AND used = 0
                  AND expires_at > ?
                """,
                (now_utc, code_hash, now_utc),
            )
            if cursor.rowcount != 1:
                return None
            cursor = await db.execute(
                """
                SELECT user_id, target_path
                FROM browser_handoff_codes
                WHERE code_hash = ?
                """,
                (code_hash,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "user_id": int(row[0]),
                "target_path": str(row[1] or "/"),
            }

    async def cleanup_browser_handoff(
        self,
        *,
        now_utc: str,
    ) -> int:
        """Удаляет истёкшие/использованные коды (scheduled cleanup)."""
        removed = await self._execute(
            "DELETE FROM browser_handoff_codes WHERE expires_at <= ? OR used = 1",
            (now_utc,),
        )
        return removed