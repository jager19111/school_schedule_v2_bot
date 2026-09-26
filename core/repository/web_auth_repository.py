# core/repository/web_auth_repository.py
#
# SQL-слой web-аутентификации: web_login_tokens + web_sessions.
#
# ПРАВИЛА ПРОЕКТА (сверено с baseline 588700f):
# - только SQL, без бизнес-логики (логика — в services/web_sessions_service.py);
# - ЕДИНОЕ shared aiosqlite-соединение: конструктор принимает объект
#   aiosqlite.Connection (основной режим, создаётся в main.py через
#   Database.connect()). Строка db_path — только legacy/тесты
#   (открывает соединение на каждый вызов — для прода запрещено);
# - ВРЕМЯ: "YYYY-MM-DD HH:MM:SS" (BaseRepository._now_utc_str ->
#   TimeService.now_utc_str). Строгий Time Governance: никаких
#   CURRENT_TIMESTAMP и никаких ISO-строк с 'T' (смешение форматов
#   ломает лексикографические сравнения в SQL);
# - схема web-таблиц живёт ТОЛЬКО в database/migrations.py
#   (migration = единственный источник schema evolution; apply_migrations
#   выполняется после init_db на каждом старте, поэтому свежие БД
#   тоже получают таблицы). В database/db.py дубликата нет.
#
# BaseRepository (baseline 588700f) предоставляет: _fetch_one/_fetch_all/
# _execute (с _write_lock), transaction() (BEGIN/COMMIT/ROLLBACK с lock),
# _now_utc_str(). ВАЖНО: не вызывать _execute внутри transaction() — дедлок.

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.repository.base_repository import BaseRepository

logger = logging.getLogger(__name__)


def _shift_days(now_utc: str, days: int) -> str:
    """Строка времени проекта -> строка со сдвигом в днях (для cleanup)."""
    dt = datetime.strptime(now_utc, "%Y-%m-%d %H:%M:%S")
    return (dt + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


class WebAuthRepository(BaseRepository):
    """Таблицы web_login_tokens (magic link) и web_sessions."""

    # ==========================================================
    # web_login_tokens (одноразовые magic-link токены, только SHA-256)
    # ==========================================================

    async def create_login_token(
        self,
        *,
        token_hash: str,
        user_id: int,
        expires_at_utc: str,
    ) -> None:
        await self._execute(
            """
            INSERT INTO web_login_tokens
                (token_hash, user_id, created_at, expires_at, used)
            VALUES (?, ?, ?, ?, 0)
            """,
            (token_hash, user_id, self._now_utc_str(), expires_at_utc),
        )

    async def consume_login_token(
        self,
        *,
        token_hash: str,
        now_utc: str,
    ) -> Optional[int]:
        """
        Атомарный одноразовый consume в одной транзакции.

        UPDATE ... WHERE used = 0 AND expires_at > now — replay и
        истёкшие токены не проходят; ровно один из конкурирующих
        exchange получает rowcount == 1, остальные — 0
        (проверено test_concurrent_exchange_same_token).
        Возвращает user_id или None.
        """
        async with self.transaction() as db:
            cursor = await db.execute(
                """
                UPDATE web_login_tokens
                SET used = 1, used_at = ?
                WHERE token_hash = ?
                  AND used = 0
                  AND expires_at > ?
                """,
                (now_utc, token_hash, now_utc),
            )
            if cursor.rowcount != 1:
                return None
            cursor = await db.execute(
                "SELECT user_id FROM web_login_tokens WHERE token_hash = ?",
                (token_hash,),
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else None

    # ==========================================================
    # web_sessions (opaque-сессии, session_hash = SHA-256(raw))
    # ==========================================================

    async def create_session(
        self,
        *,
        session_hash: str,
        user_id: int,
        idle_expires_at_utc: str,
        absolute_expires_at_utc: str,
        user_agent: Optional[str],
    ) -> int:
        now_utc = self._now_utc_str()
        await self._execute(
            """
            INSERT INTO web_sessions
                (session_hash, user_id, created_at, last_seen_at,
                 idle_expires_at, absolute_expires_at, revoked_at, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                session_hash,
                user_id,
                now_utc,
                now_utc,
                idle_expires_at_utc,
                absolute_expires_at_utc,
                (user_agent or "")[:300] or None,
            ),
        )
        row = await self._fetch_one(
            "SELECT id FROM web_sessions WHERE session_hash = ?",
            (session_hash,),
        )
        return int(row["id"])

    async def get_valid_session_by_hash(
        self,
        *,
        session_hash: str,
        now_utc: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Активная сессия: не отозвана, ОБА таймаута живы
        (idle_expires_at > now И absolute_expires_at > now).
        Роль/права НЕ хранятся в сессии — разрешаются на каждом запросе.
        """
        return await self._fetch_one(
            """
            SELECT id, user_id, created_at, last_seen_at, user_agent
            FROM web_sessions
            WHERE session_hash = ?
              AND revoked_at IS NULL
              AND idle_expires_at > ?
              AND absolute_expires_at > ?
            """,
            (session_hash, now_utc, now_utc),
        )

    async def touch_session(
        self,
        *,
        session_id: int,
        now_utc: str,
        idle_expires_at_utc: str,
        touch_threshold_utc: str,
    ) -> None:
        """
        Продление активности: ОБА поля, не только last_seen_at.

        - last_seen_at = now;
        - idle_expires_at = now + idle TTL (иначе idle timeout выродился
          бы в lifetime timeout — см. test_idle_timeout_extends_on_activity);
        - throttling: условие last_seen_at <= threshold не даёт писать
          в SQLite чаще ~1 раза в 5 минут.
        Атомарно одним UPDATE, без предварительного чтения.
        """
        await self._execute(
            """
            UPDATE web_sessions
            SET last_seen_at = ?, idle_expires_at = ?
            WHERE id = ? AND last_seen_at <= ?
            """,
            (now_utc, idle_expires_at_utc, session_id, touch_threshold_utc),
        )

    async def get_active_sessions_for_user(
        self,
        *,
        user_id: int,
        now_utc: str,
    ) -> List[Dict[str, Any]]:
        return await self._fetch_all(
            """
            SELECT id, session_hash, created_at, last_seen_at, user_agent
            FROM web_sessions
            WHERE user_id = ?
              AND revoked_at IS NULL
              AND idle_expires_at > ?
              AND absolute_expires_at > ?
            ORDER BY last_seen_at DESC
            """,
            (user_id, now_utc, now_utc),
        )

    async def revoke_session_by_hash(
        self,
        *,
        session_hash: str,
        user_id: int,
    ) -> bool:
        changed = await self._execute(
            """
            UPDATE web_sessions
            SET revoked_at = ?
            WHERE session_hash = ? AND user_id = ? AND revoked_at IS NULL
            """,
            (self._now_utc_str(), session_hash, user_id),
        )
        return changed == 1

    async def revoke_session_by_id(
        self,
        *,
        session_id: int,
        user_id: int,
    ) -> bool:
        """
        Отзыв конкретной сессии из device list.

        WHERE user_id = ? не даёт отозвать чужую сессию подстановкой id.
        """
        changed = await self._execute(
            """
            UPDATE web_sessions
            SET revoked_at = ?
            WHERE id = ? AND user_id = ? AND revoked_at IS NULL
            """,
            (self._now_utc_str(), session_id, user_id),
        )
        return changed == 1

    async def revoke_all_sessions_for_user(self, *, user_id: int) -> int:
        return await self._execute(
            """
            UPDATE web_sessions
            SET revoked_at = ?
            WHERE user_id = ? AND revoked_at IS NULL
            """,
            (self._now_utc_str(), user_id),
        )

    # ==========================================================
    # Cleanup (scheduled-задачей, не из HTTP request)
    # ==========================================================

    async def cleanup_web_auth(
        self,
        *,
        now_utc: str,
        keep_revoked_days: int = 7,
    ) -> Dict[str, int]:
        """
        Удаляет:
        - истёкшие/использованные login tokens;
        - сессии, истёкшие ПО ЛЮБОМУ из двух механизмов
          (idle_expires_at ИЛИ absolute_expires_at);
        - отозванные сессии старше keep_revoked_days.
        """
        removed_tokens = await self._execute(
            "DELETE FROM web_login_tokens WHERE expires_at <= ? OR used = 1",
            (now_utc,),
        )
        removed_expired = await self._execute(
            """
            DELETE FROM web_sessions
            WHERE absolute_expires_at <= ? OR idle_expires_at <= ?
            """,
            (now_utc, now_utc),
        )
        removed_revoked = await self._execute(
            """
            DELETE FROM web_sessions
            WHERE revoked_at IS NOT NULL AND revoked_at <= ?
            """,
            (_shift_days(now_utc, -keep_revoked_days),),
        )
        result = {
            "login_tokens": removed_tokens,
            "expired_sessions": removed_expired,
            "revoked_sessions": removed_revoked,
        }
        logger.info("WebAuth cleanup: %s", result)
        return result
