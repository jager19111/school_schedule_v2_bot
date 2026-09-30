# tests/web/phase7_checklist.py
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from web.events import ApplicationEventBus, ScheduleChanged, SessionRevoked
from web.sse import SSEConnectionManager, SSE_QUEUE_MAXSIZE

async def _read_schedule_changed(
    connection,
    *,
    expected_revision: int,
) -> None:
    message = connection.queue.get_nowait()

    assert message.startswith("event: schedule_changed\n")
    assert message.endswith("\n\n")

    lines = {
        key: value
        for key, value in (
            line.split(": ", 1)
            for line in message.strip().splitlines()
            if ": " in line
        )
    }

    assert lines["event"] == "schedule_changed"
    assert lines["data"] == f'{{"revision":{expected_revision}}}'


async def run_phase7_isolated():
    print("\n--- Running Phase 7 (Live Updates) Tests ---")

    bus = ApplicationEventBus()
    manager = SSEConnectionManager(bus)

    # ==========================================================
    # 1. Лимит: пять реальных connections одного user.
    # Две browser tabs могут принадлежать одной session.
    # ==========================================================

    tab_1 = manager.try_register(session_id=10, user_id=1)
    tab_2 = manager.try_register(session_id=10, user_id=1)

    tab_3 = manager.try_register(session_id=11, user_id=1)
    tab_4 = manager.try_register(session_id=12, user_id=1)
    tab_5 = manager.try_register(session_id=13, user_id=1)

    user_1_connections = [
        tab_1,
        tab_2,
        tab_3,
        tab_4,
        tab_5,
    ]

    assert all(
        connection is not None
        for connection in user_1_connections
    )

    rejected = manager.try_register(session_id=14, user_id=1)

    assert rejected is None, (
        "6-е SSE-соединение user #1 не было отклонено"
    )

    # Лимит обязан быть per-user, а не глобальным.
    user_2_connection = manager.try_register(
        session_id=20,
        user_id=2,
    )

    assert user_2_connection is not None, (
        "SSE limit ошибочно применяется глобально"
    )

    assert manager.active_count() == 6

    print("✅ PASS  Лимит: 6-е SSE-соединение user #1 отклонено")
    print("✅ PASS  Одна session может иметь несколько browser tabs")
    print("✅ PASS  User #2 может открыть собственное SSE connection")

    # ==========================================================
    # 2. ScheduleChanged доставляется всем connections.
    # Payload содержит только revision.
    # ==========================================================

    revision = bus.next_revision()

    await bus.publish(
        ScheduleChanged(revision=revision),
    )

    for connection in [
        *user_1_connections,
        user_2_connection,
    ]:
        await _read_schedule_changed(
            connection,
            expected_revision=revision,
        )

    print(
        "✅ PASS  ScheduleChanged доставлен всем active connections "
        "с payload только revision"
    )

    # ==========================================================
    # 3. Revoke одной session завершает все tabs этой session,
    # но не затрагивает другие sessions того же user.
    # ==========================================================

    await bus.publish(
        SessionRevoked(
            user_id=1,
            session_id=10,
        )
    )

    assert tab_1.queue.get_nowait() is None
    assert tab_2.queue.get_nowait() is None

    assert tab_3.queue.empty()
    assert tab_4.queue.empty()
    assert tab_5.queue.empty()
    assert user_2_connection.queue.empty()

    assert manager.active_count() == 4

    print(
        "✅ PASS  Revoke одной session закрывает все её browser tabs"
    )

    # ==========================================================
    # 4. Logout all завершает все оставшиеся connections user #1,
    # но не user #2.
    # ==========================================================

    await bus.publish(
        SessionRevoked(user_id=1),
    )

    assert tab_3.queue.get_nowait() is None
    assert tab_4.queue.get_nowait() is None
    assert tab_5.queue.get_nowait() is None

    assert user_2_connection.queue.empty()
    assert manager.active_count() == 1

    print(
        "✅ PASS  Logout all закрывает все SSE user #1 "
        "и не затрагивает user #2"
    )

    # ==========================================================
    # 5. Slow consumer: bounded queue не может бесконечно расти.
    # ==========================================================

    slow_bus = ApplicationEventBus()
    slow_manager = SSEConnectionManager(slow_bus)

    slow_connection = slow_manager.try_register(
        session_id=100,
        user_id=100,
    )

    assert slow_connection is not None

    for _ in range(SSE_QUEUE_MAXSIZE + 1):
        await slow_bus.publish(
            ScheduleChanged(
                revision=slow_bus.next_revision(),
            )
        )

    assert slow_connection.closed is True
    assert slow_connection.queue.get_nowait() is None
    assert slow_manager.active_count() == 0

    print(
        "✅ PASS  Slow consumer закрывается при переполнении "
        "bounded SSE queue"
    )

if __name__ == "__main__":
    asyncio.run(run_phase7_isolated())
    print("\nДля полной E2E проверки откройте 2 вкладки браузера:")
    print("1. В первой вкладке откройте расписание.")
    print("2. Во второй вкладке добавьте доп. занятие.")
    print("-> Первая вкладка должна перезагрузиться автоматически!\n")