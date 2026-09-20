"""Тесты штатной миграции users.prefer_image_schedule."""

import os
import sqlite3
import tempfile

from database.migrations import (
    _add_image_schedule_preference,
    apply_migrations_sync,
)


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

        conn = sqlite3.connect(path)
        try:
            assert _add_image_schedule_preference(conn) == "users.prefer_image_schedule"
            conn.commit()
            value = conn.execute(
                "SELECT prefer_image_schedule FROM users WHERE user_id = 1"
            ).fetchone()[0]
            assert value == 1
        finally:
            conn.close()


def test_prefer_image_migration_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.db")
        _create_minimal_users_db(path)

        conn = sqlite3.connect(path)
        try:
            assert _add_image_schedule_preference(conn) == "users.prefer_image_schedule"
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
            _add_image_schedule_preference(conn)
            conn.execute("INSERT INTO users (user_id, name) VALUES (2, 'new')")
            conn.rollback()
            names = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            assert "prefer_image_schedule" not in names
        finally:
            conn.close()


def test_full_migration_pipeline_adds_preference_when_legacy_tables_exist() -> None:
    """Проверяет именно apply_migrations_sync на минимальной legacy-схеме."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.db")
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("CREATE TABLE family_invites (id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE schedule_cache (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO users (user_id, name) VALUES (1, 'existing')")
            conn.commit()
        finally:
            conn.close()

        applied = apply_migrations_sync(path)
        assert "users.prefer_image_schedule" in applied

        conn = sqlite3.connect(path)
        try:
            names = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            assert "prefer_image_schedule" in names
        finally:
            conn.close()
