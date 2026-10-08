# tests/test_broadcast_service.py
#
# Сервисный слой broadcast: идемпотентность отправки, владение
# черновиком, отчёт, классификация доставки, cleanup черновиков.

import sqlite3
from pathlib import Path

from core.models.dto import (
    AuditAction,
    BroadcastAudience,
    BroadcastAudienceDTO,
)
from core.repository.broadcast_repository import BroadcastRepository
from services.broadcast_service import BroadcastService
from services.time_service import TimeService, TimeServiceConfig

ADMIN_ID = 42
USER_IDS = (101, 102, 103)
BLOCKED_USER_ID = 104


class FakeProfileService:
    def __init__(self) -> None:
        self.audiences: dict[
            BroadcastAudience,
            BroadcastAudienceDTO,
        ] = {}

    async def get_broadcast_audience(self, audience):
        return self.audiences.get(
            audience,
            BroadcastAudienceDTO(recipient_ids=(), skipped=0),
        )


class FakeDispatcher:
    def __init__(self) -> None:
        self.send_calls: list[int] = []
        self.fail_user_ids: set[int] = set()

    async def send_broadcast(
        self,
        *,
        chat_id: int,
        text: str,
        photo_file_id: str | None = None,
        button_text: str | None = None,
        button_url: str | None = None,
    ) -> bool:
        self.send_calls.append(chat_id)
        return chat_id not in self.fail_user_ids


class FakeAudit:
    def __init__(self) -> None:
        self.actions: list[AuditAction] = []
        self.details: list[dict] = []

    async def log_action(
        self,
        *,
        actor_id: int,
        target_id: int,
        action,
        details=None,
    ) -> None:
        self.actions.append(action)
        self.details.append(details or {})


def make_service(
    tmp_path: Path,
):
    db_path = str(tmp_path / "broadcast.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_user_id INTEGER NOT NULL,
            audience TEXT NOT NULL,
            text TEXT NOT NULL,
            photo_file_id TEXT,
            button_text TEXT,
            button_url TEXT,
            recipient_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );

        CREATE TABLE broadcast_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broadcast_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            error_code TEXT,
            sent_at TEXT
        );

        CREATE UNIQUE INDEX idx_broadcast_deliveries_unique
            ON broadcast_deliveries(broadcast_id, user_id);
        """
    )
    conn.commit()
    conn.close()

    time_service = TimeService(TimeServiceConfig(timezone="UTC"))
    repo = BroadcastRepository(
        db_path=db_path,
        time_service=time_service,
    )
    profile = FakeProfileService()
    dispatcher = FakeDispatcher()
    audit = FakeAudit()

    service = BroadcastService(
        repo,
        profile,
        dispatcher,
        audit,
    )
    return service, profile, dispatcher, audit


async def test_audience_count(tmp_path):
    service, profile, _dispatcher, _audit = make_service(tmp_path)
    profile.audiences[BroadcastAudience.FAMILY] = BroadcastAudienceDTO(
        recipient_ids=(101, 102),
        skipped=1,
    )

    assert (
        await service.get_audience_count(BroadcastAudience.FAMILY) == 2
    )


async def test_draft_owner_and_cancel(tmp_path):
    service, _profile, _dispatcher, _audit = make_service(tmp_path)

    created = await service.create_draft(
        admin_user_id=ADMIN_ID,
        audience=BroadcastAudience.ALL,
        text="Привет",
    )

    assert (
        await service.get_owned_draft_audience(
            broadcast_id=created.broadcast_id,
            admin_user_id=ADMIN_ID,
        )
        == BroadcastAudience.ALL
    )

    # Чужой админ не владеет черновиком.
    assert (
        await service.get_owned_draft_audience(
            broadcast_id=created.broadcast_id,
            admin_user_id=999,
        )
        is None
    )

    await service.cancel_draft(broadcast_id=created.broadcast_id)

    assert (
        await service.get_owned_draft_audience(
            broadcast_id=created.broadcast_id,
            admin_user_id=ADMIN_ID,
        )
        is None
    )


async def test_run_broadcast_is_idempotent(tmp_path):
    service, profile, dispatcher, audit = make_service(tmp_path)
    profile.audiences[BroadcastAudience.ALL] = BroadcastAudienceDTO(
        recipient_ids=USER_IDS,
        skipped=0,
    )

    created = await service.create_draft(
        admin_user_id=ADMIN_ID,
        audience=BroadcastAudience.ALL,
        text="Тест идемпотентности",
    )

    first = await service.run_broadcast(
        broadcast_id=created.broadcast_id,
        admin_user_id=ADMIN_ID,
    )
    second = await service.run_broadcast(
        broadcast_id=created.broadcast_id,
        admin_user_id=ADMIN_ID,
    )

    assert first is not None
    assert second is None
    assert len(dispatcher.send_calls) == len(USER_IDS)
    assert audit.actions == [AuditAction.BROADCAST_SENT]


async def test_run_broadcast_report(tmp_path):
    service, profile, dispatcher, audit = make_service(tmp_path)
    profile.audiences[BroadcastAudience.ALL] = BroadcastAudienceDTO(
        recipient_ids=USER_IDS,
        skipped=2,
    )
    dispatcher.fail_user_ids = {103}

    created = await service.create_draft(
        admin_user_id=ADMIN_ID,
        audience=BroadcastAudience.ALL,
        text="Новость",
        button_text="Открыть",
        button_url="https://example.com",
    )

    report = await service.run_broadcast(
        broadcast_id=created.broadcast_id,
        admin_user_id=ADMIN_ID,
    )

    assert report is not None
    assert report.recipient_count == 3
    assert report.sent == 2
    assert report.failed == 1
    assert report.skipped == 2
    assert 103 in dispatcher.send_calls

    audit_details = audit.details[0]
    assert audit_details["broadcast_id"] == created.broadcast_id
    assert audit_details["sent"] == 2


async def test_run_broadcast_after_cancel_returns_none(tmp_path):
    """Отменённый черновик не отправляется."""
    service, _profile, _dispatcher, _audit = make_service(tmp_path)

    created = await service.create_draft(
        admin_user_id=ADMIN_ID,
        audience=BroadcastAudience.ALL,
        text="Отмена",
    )
    await service.cancel_draft(broadcast_id=created.broadcast_id)

    assert (
        await service.run_broadcast(
            broadcast_id=created.broadcast_id,
            admin_user_id=ADMIN_ID,
        )
        is None
    )


async def test_cleanup_stale_drafts(tmp_path):
    service, _profile, _dispatcher, _audit = make_service(tmp_path)

    await service.create_draft(
        admin_user_id=ADMIN_ID,
        audience=BroadcastAudience.ALL,
        text="Брошенный черновик",
    )

    # Критерий в будущем — черновик попадает под удаление.
    removed = await service.cleanup_stale_drafts(
        older_than_utc="2999-01-01 00:00:00",
    )
    assert removed == 1

    # Повторный запуск — idempotent no-op.
    assert (
        await service.cleanup_stale_drafts(
            older_than_utc="2999-01-01 00:00:00",
        )
        == 0
    )