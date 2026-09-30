from __future__ import annotations

import asyncio
import datetime
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import httpx
from fastapi import Request
from fastapi.responses import Response

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from main import refresh_schedule_cache
from services.web_sessions_service import WebSessionContext
from web.app import WebSettings, create_web_app
from web.events import ScheduleChanged, SessionRevoked
from web.routes.auth import logout, logout_all, revoke_session
from web.routes.extra_classes import (
    extra_classes_create,
    extra_classes_delete,
    extra_classes_update,
)


RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    suffix = f" — {detail}" if detail else ""
    print(f"{'✅ PASS' if ok else '❌ FAIL'}  {name}{suffix}")


async def check(name: str, action) -> None:
    try:
        await action()
    except Exception as exc:
        record(name, False, f"{type(exc).__name__}: {exc}")
    else:
        record(name, True)


class CollectingEventBus:
    """Минимальный test double ApplicationEventBus с наблюдаемыми events."""

    def __init__(self) -> None:
        self.events: list[object] = []
        self._revision = 0

    def next_revision(self) -> int:
        self._revision += 1
        return self._revision

    async def publish(self, event: object) -> None:
        self.events.append(event)


class FakeNotificationService:
    def __init__(self) -> None:
        self.alerts: list[dict] = []
        self.upcoming_changes_calls = 0

    async def send_admin_alert(self, **kwargs) -> None:
        self.alerts.append(kwargs)

    async def send_upcoming_changes(self) -> None:
        self.upcoming_changes_calls += 1


class FakeRefreshResult:
    def __init__(self, *, schedule_changed: bool) -> None:
        self.reason = "test"
        self.source_changed = schedule_changed
        self.schedule_changed = schedule_changed
        self.js_filename = "test_nika_data.js"
        self.lesson_count = 1 if schedule_changed else 0


class FakeScheduleRepository:
    def __init__(
        self,
        *,
        schedule_changed: bool = False,
        refresh_error: Exception | None = None,
    ) -> None:
        self.schedule_changed = schedule_changed
        self.refresh_error = refresh_error
        self.clear_error_calls = 0
        self.record_error_calls: list[str] = []

    def is_ssl_degraded(self) -> bool:
        return False

    async def refresh_if_changed(self, *, target_dates) -> FakeRefreshResult:
        if self.refresh_error is not None:
            raise self.refresh_error
        return FakeRefreshResult(schedule_changed=self.schedule_changed)

    async def clear_nika_refresh_error(self) -> None:
        self.clear_error_calls += 1

    async def record_nika_refresh_error(self, *, error_message: str) -> None:
        self.record_error_calls.append(error_message)


class FakeRequest:
    """Достаточный request facade для прямого вызова route handlers."""

    def __init__(
        self,
        *,
        state: SimpleNamespace,
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.app = SimpleNamespace(state=state)
        self.cookies = cookies or {}
        self.headers = headers or {}


class FakeIdempotencyStore:
    def __init__(self, *, consume_result: bool) -> None:
        self.consume_result = consume_result
        self.consumed: list[str] = []

    def consume(self, key: str) -> bool:
        self.consumed.append(key)
        return self.consume_result

    def new_key(self) -> str:
        return "test-idempotency-key"


class MutationResult:
    def __init__(
        self,
        *,
        success: bool,
        detail: str = "validation error",
        error_code: str = "validation_error",
    ) -> None:
        self.success = success
        self.detail = detail
        self.error_code = error_code


class FakeExtraClassesWebService:
    def __init__(self, result: MutationResult) -> None:
        self.result = result
        self.create_calls = 0
        self.update_calls = 0
        self.delete_calls = 0

    async def resolve_access(self, *, actor_user_id: int, student_id: int):
        return SimpleNamespace(
            student_id=student_id,
            student_name="Тестовый ученик",
            can_manage=True,
        )

    async def create(self, access, **kwargs) -> MutationResult:
        self.create_calls += 1
        return self.result

    async def update(self, access, extra_id: int, **kwargs) -> MutationResult:
        self.update_calls += 1
        return self.result

    async def delete(self, access, extra_id: int) -> MutationResult:
        self.delete_calls += 1
        return self.result


class FakeTemplates:
    def TemplateResponse(self, request, template_name: str, context: dict):
        return Response(
            content=f"template={template_name}",
            status_code=200,
        )


class FakeSessions:
    def __init__(
        self,
        *,
        revoke_result: bool = True,
        revoke_all_result: int = 1,
        revoke_by_id_result: bool = True,
    ) -> None:
        self.revoke_result = revoke_result
        self.revoke_all_result = revoke_all_result
        self.revoke_by_id_result = revoke_by_id_result
        self.calls: list[tuple[str, tuple]] = []

    async def revoke_session(self, *, raw_token: str, user_id: int) -> bool:
        self.calls.append(("revoke_session", (raw_token, user_id)))
        return self.revoke_result

    async def revoke_all_sessions(self, *, user_id: int) -> int:
        self.calls.append(("revoke_all_sessions", (user_id,)))
        return self.revoke_all_result

    async def revoke_session_by_id(
        self,
        *,
        session_id: int,
        user_id: int,
    ) -> bool:
        self.calls.append(("revoke_session_by_id", (session_id, user_id)))
        return self.revoke_by_id_result


def _config() -> SimpleNamespace:
    return SimpleNamespace(NIKA_COVERAGE_DAYS=7)


def _context(
    *,
    user_id: int = 100,
    session_id: int = 200,
) -> WebSessionContext:
    return WebSessionContext(
        session_id=session_id,
        session_hash="a" * 64,
        user_id=user_id,
        csrf_token="b" * 64,
    )


def _extra_request(
    *,
    bus: CollectingEventBus,
    service: FakeExtraClassesWebService,
    consume_result: bool = True,
) -> FakeRequest:
    state = SimpleNamespace(
        event_bus=bus,
        extra_classes_web_service=service,
        idempotency=FakeIdempotencyStore(
            consume_result=consume_result,
        ),
        templates=FakeTemplates(),
    )
    return FakeRequest(state=state)


async def test_refresh_no_change() -> None:
    repo = FakeScheduleRepository(schedule_changed=False)
    notifications = FakeNotificationService()
    bus = CollectingEventBus()

    await refresh_schedule_cache(
        schedule_repo=repo,
        notification_service=notifications,
        tz=datetime.UTC,
        config=_config(),
        web_event_bus=bus,
    )

    assert bus.events == []
    assert notifications.upcoming_changes_calls == 0


async def test_refresh_changed_once() -> None:
    repo = FakeScheduleRepository(schedule_changed=True)
    notifications = FakeNotificationService()
    bus = CollectingEventBus()

    await refresh_schedule_cache(
        schedule_repo=repo,
        notification_service=notifications,
        tz=datetime.UTC,
        config=_config(),
        web_event_bus=bus,
    )

    assert len(bus.events) == 1
    event = bus.events[0]
    assert isinstance(event, ScheduleChanged)
    assert event.revision == 1
    assert notifications.upcoming_changes_calls == 1


async def test_refresh_exception_no_event() -> None:
    repo = FakeScheduleRepository(
        refresh_error=aiohttp.ClientError("source unavailable"),
    )
    notifications = FakeNotificationService()
    bus = CollectingEventBus()

    await refresh_schedule_cache(
        schedule_repo=repo,
        notification_service=notifications,
        tz=datetime.UTC,
        config=_config(),
        web_event_bus=bus,
    )

    assert bus.events == []
    assert len(repo.record_error_calls) == 1
    assert notifications.upcoming_changes_calls == 0


async def test_refresh_without_web_bus() -> None:
    repo = FakeScheduleRepository(schedule_changed=True)
    notifications = FakeNotificationService()

    await refresh_schedule_cache(
        schedule_repo=repo,
        notification_service=notifications,
        tz=datetime.UTC,
        config=_config(),
        web_event_bus=None,
    )

    assert notifications.upcoming_changes_calls == 1


async def test_extra_failure_no_event() -> None:
    bus = CollectingEventBus()
    service = FakeExtraClassesWebService(
        MutationResult(success=False),
    )
    request = _extra_request(bus=bus, service=service)

    await extra_classes_create(
        request=request,
        context=_context(),
        idempotency_key="create-failure",
        title="Робототехника",
        day_of_week="1",
        time_start="15:00",
        time_end="16:00",
        location="305",
        reminder_minutes="30",
        student=1,
    )

    assert bus.events == []
    assert service.create_calls == 1


async def test_extra_duplicate_no_event() -> None:
    bus = CollectingEventBus()
    service = FakeExtraClassesWebService(
        MutationResult(success=True),
    )
    request = _extra_request(
        bus=bus,
        service=service,
        consume_result=False,
    )

    await extra_classes_create(
        request=request,
        context=_context(),
        idempotency_key="duplicate-key",
        title="Робототехника",
        day_of_week="1",
        time_start="15:00",
        time_end="16:00",
        location="305",
        reminder_minutes="30",
        student=1,
    )

    assert bus.events == []
    assert service.create_calls == 0


async def test_extra_success_events() -> None:
    bus = CollectingEventBus()
    service = FakeExtraClassesWebService(
        MutationResult(success=True),
    )
    request = _extra_request(bus=bus, service=service)
    context = _context()

    await extra_classes_create(
        request=request,
        context=context,
        idempotency_key="create-success",
        title="Робототехника",
        day_of_week="1",
        time_start="15:00",
        time_end="16:00",
        location="305",
        reminder_minutes="30",
        student=1,
    )

    await extra_classes_update(
        request=request,
        extra_id=77,
        context=context,
        title="Робототехника PRO",
        day_of_week="2",
        time_start="16:00",
        time_end="17:00",
        location="306",
        reminder_minutes="20",
        student=1,
    )

    await extra_classes_delete(
        request=request,
        extra_id=77,
        context=context,
        student=1,
    )

    assert len(bus.events) == 3
    assert all(isinstance(event, ScheduleChanged) for event in bus.events)
    assert [event.revision for event in bus.events] == [1, 2, 3]
    assert service.create_calls == 1
    assert service.update_calls == 1
    assert service.delete_calls == 1


async def test_logout_current_event_on_success() -> None:
    bus = CollectingEventBus()
    sessions = FakeSessions(revoke_result=True)
    request = FakeRequest(
        state=SimpleNamespace(event_bus=bus),
        cookies={"web_session": "raw-cookie"},
    )
    context = _context(user_id=10, session_id=20)

    response = Response()
    await logout(
        request=request,
        response=response,
        context=context,
        sessions=sessions,
    )

    assert len(bus.events) == 1
    event = bus.events[0]
    assert event == SessionRevoked(user_id=10, session_id=20)


async def test_logout_current_no_event_on_failed_revoke() -> None:
    bus = CollectingEventBus()
    sessions = FakeSessions(revoke_result=False)
    request = FakeRequest(
        state=SimpleNamespace(event_bus=bus),
        cookies={"web_session": "raw-cookie"},
    )

    await logout(
        request=request,
        response=Response(),
        context=_context(),
        sessions=sessions,
    )

    assert bus.events == []


async def test_logout_all_event_only_when_sessions_revoked() -> None:
    context = _context(user_id=10, session_id=20)

    success_bus = CollectingEventBus()
    success_sessions = FakeSessions(revoke_all_result=3)
    success_request = FakeRequest(
        state=SimpleNamespace(event_bus=success_bus),
    )

    await logout_all(
        request=success_request,
        response=Response(),
        context=context,
        sessions=success_sessions,
    )

    assert success_bus.events == [
        SessionRevoked(user_id=10, session_id=None),
    ]

    empty_bus = CollectingEventBus()
    empty_sessions = FakeSessions(revoke_all_result=0)
    empty_request = FakeRequest(
        state=SimpleNamespace(event_bus=empty_bus),
    )

    await logout_all(
        request=empty_request,
        response=Response(),
        context=context,
        sessions=empty_sessions,
    )

    assert empty_bus.events == []


async def test_revoke_exact_device_event() -> None:
    bus = CollectingEventBus()
    sessions = FakeSessions(revoke_by_id_result=True)
    request = FakeRequest(
        state=SimpleNamespace(event_bus=bus),
    )

    result = await revoke_session(
        session_id=777,
        request=request,
        context=_context(user_id=10, session_id=20),
        sessions=sessions,
    )

    assert result.ok is True
    assert bus.events == [
        SessionRevoked(user_id=10, session_id=777),
    ]


async def test_base_template_sse_contract() -> None:
    """
    Проверяет реальный GET /auth и actual rendering base.html через FastAPI.

    Private probe route существует только внутри test application и нужен,
    чтобы проверить base layout с csrf_token без поднятия всей schedule
    domain модели.
    """

    async def db_liveness() -> bool:
        return True

    app = create_web_app(
        web_settings=WebSettings(
            public_url="http://testserver",
            allowed_hosts=["testserver"],
            gateway_key=None,
            access_mode="public",
            cookie_secure=False,
        ),
        sessions_service=SimpleNamespace(),
        profile_service=SimpleNamespace(),
        schedule_service=SimpleNamespace(),
        students_service=SimpleNamespace(),
        schedule_targets_service=SimpleNamespace(),
        extra_classes_web_service=SimpleNamespace(),
        time_service=SimpleNamespace(),
        db_liveness=db_liveness,
    )

    @app.get("/__phase7/private-layout")
    async def private_layout(request: Request):
        return request.app.state.templates.TemplateResponse(
            request,
            "base.html",
            {
                "csrf_token": "phase7-test-csrf-token",
                "nav": "today",
            },
        )

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        auth_response = await client.get("/auth")
        assert auth_response.status_code == 200
        assert "sse-connect=" not in auth_response.text
        assert 'id="live-monitor"' not in auth_response.text

        private_response = await client.get("/__phase7/private-layout")
        assert private_response.status_code == 200
        assert private_response.text.count("sse-connect=") == 1
        assert private_response.text.count('id="live-monitor"') == 1
        assert "/api/v1/schedule/stream" in private_response.text


async def main() -> None:
    print("\n--- Running Phase 7 event wiring checks ---")

    await check(
        "refresh without schedule change publishes no event",
        test_refresh_no_change,
    )
    await check(
        "refresh with schedule change publishes exactly one event",
        test_refresh_changed_once,
    )
    await check(
        "refresh exception publishes no event",
        test_refresh_exception_no_event,
    )
    await check(
        "refresh works with WEB_ENABLED=False / event bus None",
        test_refresh_without_web_bus,
    )
    await check(
        "extra class create failure publishes no event",
        test_extra_failure_no_event,
    )
    await check(
        "duplicate idempotent create publishes no event",
        test_extra_duplicate_no_event,
    )
    await check(
        "extra create/update/delete each publish one event",
        test_extra_success_events,
    )
    await check(
        "logout current publishes exact SessionRevoked on success",
        test_logout_current_event_on_success,
    )
    await check(
        "logout current publishes no event when revoke failed",
        test_logout_current_no_event_on_failed_revoke,
    )
    await check(
        "logout all publishes only when one or more sessions revoked",
        test_logout_all_event_only_when_sessions_revoked,
    )
    await check(
        "revoke exact device publishes target session id",
        test_revoke_exact_device_event,
    )
    await check(
        "public auth has no SSE; private layout has exactly one SSE",
        test_base_template_sse_contract,
    )

    failed = [item for item in RESULTS if not item[1]]

    print("\n" + "=" * 60)
    print(
        "Phase 7 event wiring checklist: "
        f"{len(RESULTS) - len(failed)}/{len(RESULTS)} PASS"
    )
    print("=" * 60)

    if failed:
        print("Failed checks:")
        for name, _, detail in failed:
            print(f"- {name}: {detail}")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
