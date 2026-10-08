import sqlite3
from pathlib import Path

from core.repository.browser_handoff_repository import BrowserHandoffRepository
from services.browser_handoff_service import BrowserHandoffService
from services.time_service import TimeService, TimeServiceConfig


def make_service(tmp_path: Path) -> BrowserHandoffService:
    db_path = str(tmp_path / "handoff.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE browser_handoff_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code_hash TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            target_path TEXT NOT NULL DEFAULT '/',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            used_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    repo = BrowserHandoffRepository(
        db_path=db_path,
        time_service=TimeService(TimeServiceConfig(timezone="UTC")),
    )
    return BrowserHandoffService(
        repo,
        TimeService(TimeServiceConfig(timezone="UTC")),
    )


async def test_handoff_single_use(tmp_path):
    service = make_service(tmp_path)
    code = await service.issue_handoff(user_id=1)

    first = await service.consume_handoff(code)
    assert first is not None
    assert first.user_id == 1

    second = await service.consume_handoff(code)
    assert second is None


async def test_handoff_unknown_code(tmp_path):
    assert await make_service(tmp_path).consume_handoff("no-such-code-123") is None


async def test_handoff_target_allowlist(tmp_path):
    service = make_service(tmp_path)
    code = await service.issue_handoff(
        user_id=1,
        target_path="https://evil.example",
    )
    payload = await service.consume_handoff(code)
    assert payload.target_path == "/"