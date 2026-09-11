# database/migrations.py
#
# Лёгкий мигратор: в проекте нет Alembic, db.py строит схему через
# CREATE TABLE IF NOT EXISTS. Изменения живой БД применяются здесь:
# проверка PRAGMA table_info -> ALTER TABLE при отсутствии колонки.
#
# Вызов из main.py сразу после database.init_db():
#
#     from database.migrations import apply_migrations
#     applied = await apply_migrations(config.DB_PATH)
#     if applied:
#         logger.info("DB migrations applied: %s", applied)
#
# Каждая миграция обязана быть идемпотентной: повторный запуск — no-op.
#
# Проверено в песочнице против точной схемы family_invites из db.py:
# - свежая БД: колонка + UNIQUE-индекс добавлены;
# - повторный запуск: no-op;
# - прод-БД с данными: существующие приглашения не тронуты
#   (short_code=NULL), UNIQUE-индекс допускает множество NULL.

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def _columns_of(conn: sqlite3.Connection, table: str) -> set[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _add_family_invites_short_code(conn: sqlite3.Connection) -> str | None:
    """family_invites.short_code — печатаемая форма приглашения.

    UNIQUE-индекс допускает множество NULL: легаси-приглашения
    (только deep-link) остаются валидными.
    """
    if "short_code" not in _columns_of(conn, "family_invites"):
        conn.execute("ALTER TABLE family_invites ADD COLUMN short_code TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_family_invites_short_code "
            "ON family_invites(short_code)"
        )
        return "family_invites.short_code"
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_family_invites_short_code "
        "ON family_invites(short_code)"
    )
    return None


MIGRATIONS = [
    _add_family_invites_short_code,
]


def apply_migrations_sync(db_path: str) -> list[str]:
    """Применяет все миграции. Возвращает список применённых."""
    applied: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        for migration in MIGRATIONS:
            result = migration(conn)
            if result:
                applied.append(result)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if applied:
        logger.info("DB migrations applied: %s", applied)
    return applied


async def apply_migrations(db_path: str) -> list[str]:
    """Async-обёртка для main.py."""
    import asyncio

    return await asyncio.to_thread(apply_migrations_sync, db_path)
