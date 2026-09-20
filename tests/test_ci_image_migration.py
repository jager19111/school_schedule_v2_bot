"""Тесты штатной миграции users.prefer_image_schedule."""

import asyncio
import os
import sqlite3
import tempfile

from database.migrations import apply_migrations_sync


def _create_minimal_users_db(path: str, with_column: bool = False) -> None:
    conn = sqlite3.connect(path)
    try:
        columns = "user_id INTEGER PRIMARY KEY, name TEXT"
        if with_column:
            columns += ", prefer_image_schedule INTEGER NOT NULL DEFAULT 1"
        conn.execute(f"CREATE TABLE users ({columns})")
        conn.execute("INSERT INTO users (user_id, name) VALUES (1, 'existing')")
        conn.commit()
    finally:
        conn.close()


def test_prefer_image_migration_adds_column_with_default_one() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.db")
        _create_minimal_users_db(path)

        applied = apply_migrations_sync(path)
        assert "users.prefer_image_schedule" in applied

        conn = sqlite3.connect(path)
        try:
            column = conn.execute(
                "PRAGMA table_info(users)"
            ).fetchall()
            names = {row[1] for row in column}
            assert "prefer_image_schedule" in names
            value = conn.execute(
                "SELECT prefer_image_schedule FROM users WHERE user_id = 1"
            ).fetchone()[0]
            assert value == 1
        finally:
            conn.close()


def test_prefer_image_migration_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.db")
        _create_minimal_users_db(path, with_column=True)

        # Миграции до image preference на минимальной БД не имеют таблиц
        # family_invites/schedule_cache, поэтому проверяем саму миграцию напрямую.
        conn = sqlite3.connect(path)
        try:
            from database.migrations import _add_image_schedule_preference

            assert _add_image_schedule_preference(conn) is None
            conn.commit()
        finally:
            conn.close()


def test_prefer_image_migration_rolls_back_on_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.db")
        _create_minimal_users_db(path)
        conn = sqlite3.connect(path)
        try:
            from database.migrations import _add_image_schedule_preference

            _add_image_schedule_preference(conn)
            conn.execute("INSERT INTO users (user_id, name) VALUES (2, 'new')")
            conn.rollback()
            names = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            assert "prefer_image_schedule" not in names
        finally:
            conn.close()
