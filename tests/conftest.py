# tests/conftest.py
from __future__ import annotations


from pathlib import Path
from collections.abc import AsyncIterator

import aiosqlite
import pytest
import pytest_asyncio


from core.models.domain import LessonInstance
from core.repository.watch_target_repository import (
    WatchTargetRepository,
)
from database.db import Database
from services.time_service import (
    TimeService,
    TimeServiceConfig,
)
from services.watch_targets_service import WatchTargetsService


@pytest.fixture
def lesson_factory():
    def factory(**overrides) -> LessonInstance:
        values = {
            "id": "lesson-1",
            "period_id": "period-1",
            "class_id": "013",
            "class_name": "5а",
            "date": "2026-09-07",
            "weekday": 1,
            "lesson_num": 1,
            "start_time": "08:15",
            "end_time": "09:00",
            "subject_id": "060",
            "subject_name": "Русский язык",
            "teacher_id": "002",
            "teacher_name": "Иванов И.И.",
            "room_id": "027",
            "room_name": "208(Н)",
            "group_id": "ALL",
            "group_name": "Весь класс",
            "is_exchange": False,
            "is_cancelled": False,
            "is_methodological": False,
        }
        values.update(overrides)
        return LessonInstance(**values)

    return factory


@pytest.fixture
def time_service() -> TimeService:
    """
    Real TimeService для repository tests.

    Tests не зависят от exact current timestamp:
    они проверяют persistence, ownership и transaction behavior.
    """
    return TimeService(
        TimeServiceConfig(
            timezone="Asia/Novosibirsk",
        )
    )


@pytest_asyncio.fixture
async def sqlite_connection(
    tmp_path: Path,
) -> AsyncIterator[aiosqlite.Connection]:
    """
    Изолированная SQLite database на каждый test.

    Fixture использует production Database.init_db() и Database.connect(),
    поэтому schema, PRAGMA и row_factory совпадают с real application.
    """
    database = Database(
        str(tmp_path / "watch_targets_test.db"),
    )

    await database.init_db()
    connection = await database.connect()

    try:
        yield connection
    finally:
        await database.close()


@pytest_asyncio.fixture
async def create_test_user(
    sqlite_connection: aiosqlite.Connection,
    time_service: TimeService,
):
    """
    Создаёт минимальную users row для FK schedule_watch_targets.owner_user_id.

    Сознательно использует fixture SQL напрямую:
    это test setup, а не тестируемая business operation.
    """

    async def factory(
        *,
        user_id: int,
        name: str | None = None,
        role: str = "parent",
    ) -> None:
        now_utc = time_service.now_utc_str()

        await sqlite_connection.execute(
            """
            INSERT INTO users (
                user_id,
                name,
                role,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                name or f"Пользователь {user_id}",
                role,
                now_utc,
                now_utc,
            ),
        )
        await sqlite_connection.commit()

    return factory


@pytest.fixture
def watch_target_repository(
    sqlite_connection: aiosqlite.Connection,
    time_service: TimeService,
) -> WatchTargetRepository:
    return WatchTargetRepository(
        db_path=sqlite_connection,
        time_service=time_service,
    )


@pytest.fixture
def watch_targets_service(
    watch_target_repository: WatchTargetRepository,
) -> WatchTargetsService:
    return WatchTargetsService(
        repository=watch_target_repository,
    )