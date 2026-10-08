# core/repository/broadcast_repository.py
# SQL-слой admin-рассылок (broadcasts + broadcast_deliveries).
# ПРАВИЛА ПРОЕКТА:
# - только SQL, без бизнес-логики (она в services/broadcast_service.py);
# - ЕДИНОЕ shared aiosqlite-соединение (BaseRepository);
# - время: "YYYY-MM-DD HH:MM:SS" (_now_utc_str), никаких
#   CURRENT_TIMESTAMP;
# - переход draft -> sending атомарен: конкурирующие подтверждения
#   не отправляют рассылку дважды;
# - schema живёт ТОЛЬКО в database/migrations.py.

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.repository.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class BroadcastRepository(BaseRepository):
    """Таблицы broadcasts (черновики/отправки) и broadcast_deliveries."""

    async def create_broadcast(
        self,
        *,
        admin_user_id: int,
        audience: str,
        text: str,
        photo_file_id: Optional[str],
        button_text: Optional[str],
        button_url: Optional[str],
    ) -> int:
        """Создаёт черновик (status='draft'). id читается в той же
        транзакции — конкурирующие INSERT не подменят last_insert_rowid."""
        async with self.transaction() as db:
            await db.execute(
                """
                INSERT INTO broadcasts
                    (admin_user_id, audience, text, photo_file_id,
                     button_text, button_url, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'draft', ?)
                """,
                (
                    admin_user_id, audience, text, photo_file_id,
                    button_text, button_url, self._now_utc_str(),
                ),
            )
            cursor = await db.execute(
                "SELECT last_insert_rowid() AS id"
            )
            row = await cursor.fetchone()
            return int(row[0])

    async def get_broadcast(
        self,
        *,
        broadcast_id: int,
    ) -> Optional[Dict[str, Any]]:
        return await self._fetch_one(
            """
            SELECT id, admin_user_id, audience, text, photo_file_id,
                   button_text, button_url, recipient_count, status
            FROM broadcasts
            WHERE id = ?
            """,
            (broadcast_id,),
        )

        async def update_draft(
            self,
            *,
            broadcast_id: int,
            text: str,
            photo_file_id: Optional[str],
            button_text: Optional[str],
            button_url: Optional[str],
        ) -> None:
            """Перезапись черновика после «Изменить» (только status='draft')."""
            await self._execute(
                """
                UPDATE broadcasts
                SET text = ?, photo_file_id = ?,
                    button_text = ?, button_url = ?
                WHERE id = ? AND status = 'draft'
                """,
                (text, photo_file_id, button_text, button_url, broadcast_id),
            )

    async def try_start_sending(
        self,
        *,
        broadcast_id: int,
    ) -> bool:
        """
        Атомарный переход draft -> sending.

        True получает ровно один из конкурирующих подтверждений;
        остальные — False (двойной клик по «Отправить», race
        двух callback'ов). Идемпотентность отправки.
        """
        changed = await self._execute(
            """
            UPDATE broadcasts
            SET status = 'sending', started_at = ?
            WHERE id = ? AND status = 'draft'
            """,
            (self._now_utc_str(), broadcast_id),
        )
        return changed == 1

    async def set_recipient_count(
        self,
        *,
        broadcast_id: int,
        recipient_count: int,
    ) -> None:
        await self._execute(
            "UPDATE broadcasts SET recipient_count = ? WHERE id = ?",
            (recipient_count, broadcast_id),
        )

    async def cancel_draft(
        self,
        *,
        broadcast_id: int,
    ) -> bool:
        changed = await self._execute(
            """
            UPDATE broadcasts
            SET status = 'cancelled'
            WHERE id = ? AND status = 'draft'
            """,
            (broadcast_id,),
        )
        return changed == 1

    async def finish_broadcast(
        self,
        *,
        broadcast_id: int,
    ) -> None:
        await self._execute(
            "UPDATE broadcasts SET status = 'done', finished_at = ? WHERE id = ?",
            (self._now_utc_str(), broadcast_id),
        )

    async def create_deliveries(
        self,
        *,
        broadcast_id: int,
        user_ids: List[int],
    ) -> int:
        """
        Массовая запись получателей (INSERT OR IGNORE: уникальный
        индекс broadcast_id + user_id защищает от дублей при resume).
        """
        if not user_ids:
            return 0
        async with self.transaction() as db:
            await db.executemany(
                """
                INSERT OR IGNORE INTO broadcast_deliveries
                    (broadcast_id, user_id, status)
                VALUES (?, ?, 'pending')
                """,
                [(broadcast_id, user_id) for user_id in user_ids],
            )
        return len(user_ids)

    async def get_pending_deliveries(
        self,
        *,
        broadcast_id: int,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Порция неотправленных доставок (батчинг отправки)."""
        return await self._fetch_all(
            """
            SELECT id, user_id
            FROM broadcast_deliveries
            WHERE broadcast_id = ? AND status = 'pending'
            LIMIT ?
            """,
            (broadcast_id, limit),
        )

    async def mark_delivery(
        self,
        *,
        delivery_id: int,
        status: str,
        error_code: Optional[str] = None,
    ) -> None:
        await self._execute(
            """
            UPDATE broadcast_deliveries
            SET status = ?, error_code = ?,
                sent_at = CASE WHEN ? = 'sent' THEN ? ELSE NULL END
            WHERE id = ?
            """,
            (status, error_code, status, self._now_utc_str(), delivery_id),
        )

    async def get_delivery_counts(
        self,
        *,
        broadcast_id: int,
    ) -> Dict[str, int]:
        rows = await self._fetch_all(
            """
            SELECT status, COUNT(*) AS count
            FROM broadcast_deliveries
            WHERE broadcast_id = ?
            GROUP BY status
            """,
            (broadcast_id,),
        )
        return {str(r["status"]): int(r["count"]) for r in rows}

    async def cleanup_stale_drafts(
        self,
        *,
        older_than_utc: str,
    ) -> int:
        """
        Удаляет брошенные черновики (FSM очищен, подтверждения не было).

        Scheduled cleanup, не из HTTP/bot request.
        """
        return await self._execute(
            """
            DELETE FROM broadcasts
            WHERE status = 'draft' AND created_at < ?
            """,
            (older_than_utc,),
        )