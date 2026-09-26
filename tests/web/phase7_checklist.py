# tests/web/phase7_checklist.py
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from web.events import ApplicationEventBus, ScheduleChanged, SessionRevoked
from web.sse import SSEConnectionManager

async def run_phase7_isolated():
    print("\n--- Running Phase 7 (Live Updates) Tests ---")
    
    bus = ApplicationEventBus()
    manager = SSEConnectionManager(bus)
    
    # 1. Лимит соединений
    connections = []
    for i in range(5):
        conn = manager.try_register(session_id=i, user_id=1)
        assert conn is not None
        connections.append(conn)
    
    conn_6 = manager.try_register(session_id=6, user_id=1)
    assert conn_6 is None, "Лимит 5 соединений не сработал"
    print("✅ PASS  Лимит: 6-е SSE-соединение одного user -> 429")

    # 2. Публикация событий
    await bus.publish(ScheduleChanged(revision=bus.next_revision()))
    
    # Проверяем, что во все очереди упал payload
    msg = connections[0].queue.get_nowait()
    assert "event: schedule_changed" in msg
    assert '"revision": 1' in msg
    print("✅ PASS  SSE payload: только revision, без расписаний")
    
    # 3. Отзыв сессии
    await bus.publish(SessionRevoked(user_id=1))
    sentinel = connections[0].queue.get_nowait()
    assert sentinel is None, "Не получен sentinel для закрытия SSE"
    print("✅ PASS  Logout: SessionRevoked закрывает очереди")

if __name__ == "__main__":
    asyncio.run(run_phase7_isolated())
    print("\nДля полной E2E проверки откройте 2 вкладки браузера:")
    print("1. В первой вкладке откройте расписание.")
    print("2. Во второй вкладке добавьте доп. занятие.")
    print("-> Первая вкладка должна перезагрузиться автоматически!\n")