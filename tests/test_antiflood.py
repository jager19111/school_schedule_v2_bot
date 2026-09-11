# tests/test_antiflood.py
#
# Тесты anti-flood middleware: алгоритм token bucket и клей aiogram.
#
# Часы инжектируемы (FakeClock) — никакие тесты не спят и не флапают.
# События — лёгкие фейки (SimpleNamespace): реальный Telegram не нужен.
# Тесты синхронные (asyncio.run) — не зависят от pytest-asyncio.
#
# Запуск: pytest tests/test_antiflood.py -v

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bot.middlewares.antiflood import AntiFloodMiddleware, TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


# ==================== Алгоритм TokenBucket ====================

def test_bucket_burst_capacity():
    clock = FakeClock()
    bucket = TokenBucket(capacity=20, rate=5.0, clock=clock)
    allowed = sum(1 for _ in range(20) if bucket.allow())
    assert allowed == 20, "burst обязан пропускаться целиком"
    assert bucket.allow() is False, "21-е мгновенное событие — спам"


def test_bucket_refill_rate():
    clock = FakeClock()
    bucket = TokenBucket(capacity=20, rate=5.0, clock=clock)
    for _ in range(20):
        bucket.allow()
    assert bucket.allow() is False

    clock.advance(0.4)  # 5/сек -> ровно 2 токена
    assert bucket.allow() is True
    assert bucket.allow() is True
    assert bucket.allow() is False, "восстановление строго по rate"


def test_bucket_caps_at_capacity():
    clock = FakeClock()
    bucket = TokenBucket(capacity=20, rate=5.0, clock=clock)
    for _ in range(20):
        bucket.allow()
    clock.advance(3600)  # час простоя
    allowed = sum(1 for _ in range(25) if bucket.allow())
    assert allowed == 20, "выше capacity не восстанавливается"


def test_bucket_retry_after():
    clock = FakeClock()
    bucket = TokenBucket(capacity=20, rate=5.0, clock=clock)
    for _ in range(20):
        bucket.allow()
    assert bucket.allow() is False
    assert 0.0 < bucket.retry_after <= 0.2 + 1e-6  # 1/5 сек


def test_bucket_boundary_epsilon():
    """«Ровно один токен» после float-арифметики обязан проходить."""
    clock = FakeClock()
    bucket = TokenBucket(capacity=20, rate=5.0, clock=clock)
    for _ in range(20):
        bucket.allow()
    assert bucket.allow() is False  # исчерпан полностью

    clock.advance(0.2)  # rate 5/сек -> ровно ОДИН токен (с float-хвостом)
    assert bucket.allow() is True, "epsilon пропускает «почти ровно один»"
    assert bucket.allow() is False, "и только один"
    assert bucket.tokens >= 0.0, "антидрейф: отрицательного остатка нет"


def test_bucket_clock_running_backwards():
    """NTP-скачок назад не рвёт и не обнуляет бакет."""
    clock = FakeClock()
    bucket = TokenBucket(capacity=5, rate=5.0, clock=clock)
    clock.t -= 10.0
    assert bucket.allow() is True
    assert abs(bucket.tokens - 4.0) < 1e-9


# ==================== Клей middleware ====================

def _make_middleware(clock, burst=3, rate=5.0, admin_ids=None):
    return AntiFloodMiddleware(
        burst=burst,
        rate_per_second=rate,
        admin_ids=admin_ids or set(),
        answer_cooldown=2.0,
        clock=clock,
    )


def _make_update(answer_recorder):
    return SimpleNamespace(
        callback_query=SimpleNamespace(answer=answer_recorder),
    )


def test_middleware_burst_passes_and_throttles():
    async def scenario():
        clock = FakeClock()
        mw = _make_middleware(clock)
        user = SimpleNamespace(id=42)
        data = {"event_from_user": user}
        called = []

        async def handler(event, data):
            called.append(1)
            return "OK"

        answers = []

        async def answer(text=None, show_alert=False):
            answers.append(text)

        update = _make_update(answer)

        results = [await mw(handler, update, data) for _ in range(3)]
        assert results == ["OK"] * 3
        assert len(called) == 3

        assert await mw(handler, update, data) is None
        assert len(called) == 3, "хендлер не должен вызываться при троттлинге"
        assert answers == ["Не так быстро 🙂 Подожди пару секунд."]

    asyncio.run(scenario())


def test_middleware_answer_cooldown():
    """Второй троттлинг подряд — тихий answer() без текста."""
    async def scenario():
        clock = FakeClock()
        mw = _make_middleware(clock)
        user = SimpleNamespace(id=42)
        data = {"event_from_user": user}

        async def handler(event, data):
            return "OK"

        answers = []

        async def answer(text=None, show_alert=False):
            answers.append(text)

        update = _make_update(answer)
        for _ in range(3):
            await mw(handler, update, data)
        assert await mw(handler, update, data) is None
        assert await mw(handler, update, data) is None
        assert len(answers) == 2
        assert answers[0] is not None
        assert answers[1] is None, "в cooldown — тихий ответ без текста"

    asyncio.run(scenario())


def test_middleware_refill_restores():
    async def scenario():
        clock = FakeClock()
        mw = _make_middleware(clock)
        user = SimpleNamespace(id=42)
        data = {"event_from_user": user}

        async def handler(event, data):
            return "OK"

        async def answer(text=None, show_alert=False):
            pass

        update = _make_update(answer)
        for _ in range(3):
            await mw(handler, update, data)
        assert await mw(handler, update, data) is None

        clock.advance(0.5)  # rate 5/сек -> 2 токена
        assert await mw(handler, update, data) == "OK"

    asyncio.run(scenario())


def test_middleware_admin_bypass():
    async def scenario():
        clock = FakeClock()
        mw = _make_middleware(clock, admin_ids={999})
        user = SimpleNamespace(id=7)
        data = {"event_from_user": user}
        admin_data = {"event_from_user": SimpleNamespace(id=999)}

        async def handler(event, data):
            return "OK"

        async def answer(text=None, show_alert=False):
            pass

        update = _make_update(answer)
        for _ in range(3):
            assert await mw(handler, update, data) == "OK"
        assert await mw(handler, update, data) is None

        assert await mw(handler, update, admin_data) == "OK", \
            "админ не троттлится даже при исчерпанном бакете другого юзера"

    asyncio.run(scenario())


def test_middleware_anonymous_passthrough():
    """Канальные посты и системные события без пользователя — мимо."""
    async def scenario():
        clock = FakeClock()
        mw = _make_middleware(clock)

        async def handler(event, data):
            return "OK"

        anon_update = SimpleNamespace(
            message=SimpleNamespace(from_user=None),
        )
        assert await mw(handler, anon_update, {}) == "OK"

    asyncio.run(scenario())


def test_middleware_message_throttle_is_silent():
    """Троттленный message не получает ответа — нет усиления спама."""
    async def scenario():
        clock = FakeClock()
        mw = _make_middleware(clock)
        user = SimpleNamespace(id=42)
        data = {"event_from_user": user}

        async def handler(event, data):
            return "OK"

        answers = []

        async def answer(text=None, show_alert=False):
            answers.append(text)

        cb_update = _make_update(answer)
        for _ in range(3):
            await mw(handler, cb_update, data)
        await mw(handler, cb_update, data)  # троттлинг, 1 ответ
        before = len(answers)

        msg_update = SimpleNamespace(
            message=SimpleNamespace(from_user=user),
        )
        assert await mw(handler, msg_update, data) is None
        assert len(answers) == before, "на message ответа быть не должно"

    asyncio.run(scenario())


def test_middleware_user_extraction_from_event():
    """data без event_from_user — пользователь извлекается из event."""
    async def scenario():
        clock = FakeClock()
        mw = AntiFloodMiddleware(
            burst=1, rate_per_second=1.0, clock=clock,
        )
        user = SimpleNamespace(id=9)

        async def handler(event, data):
            return "OK"

        async def answer(text=None, show_alert=False):
            pass

        update = SimpleNamespace(
            callback_query=SimpleNamespace(from_user=user, answer=answer),
        )
        assert await mw(handler, update, {}) == "OK"
        assert await mw(handler, update, {}) is None

    asyncio.run(scenario())


def test_middleware_prunes_stale_buckets():
    async def scenario():
        clock = FakeClock()
        mw = _make_middleware(clock)
        mw._prune_counter = mw._PRUNE_EVERY - 1

        async def handler(event, data):
            return "OK"

        async def answer(text=None, show_alert=False):
            pass

        # Бакет, неактивный 2 часа — кандидат на удаление.
        stale_bucket = TokenBucket(1, 1.0, clock=lambda: clock.t - 7200)
        mw._buckets[12345] = stale_bucket
        update = _make_update(answer)
        await mw(handler, update, {"event_from_user": SimpleNamespace(id=777)})
        assert 12345 not in mw._buckets, "протухший бакет должен удаляться"

    asyncio.run(scenario())
    
def test_stats_counters():
    """allowed/throttled считаются; админ и аноним не считаются."""
    async def scenario():
        clock = FakeClock()
        mw = _make_middleware(clock, burst=2, admin_ids={999})
        async def handler(event, data):
            return "OK"
        async def answer(text=None, show_alert=False):
            pass
        update = _make_update(answer)

        u1 = {"event_from_user": SimpleNamespace(id=1)}
        assert await mw(handler, update, u1) == "OK"
        assert await mw(handler, update, u1) == "OK"
        for _ in range(3):
            assert await mw(handler, update, u1) is None

        u2 = {"event_from_user": SimpleNamespace(id=2)}
        assert await mw(handler, update, u2) == "OK"
        assert await mw(handler, update, u2) == "OK"
        assert await mw(handler, update, u2) is None

        # админ и аноним — мимо счётчиков
        assert await mw(
            handler, update, {"event_from_user": SimpleNamespace(id=999)},
        ) == "OK"
        anon = SimpleNamespace(message=SimpleNamespace(from_user=None))
        assert await mw(handler, anon, {}) == "OK"

        snap = mw.stats_snapshot()
        assert snap.allowed_total == 4
        assert snap.throttled_total == 4
        assert snap.throttled_by_user == {1: 3, 2: 1}
        assert snap.tracked_users == 2
        assert snap.last_throttled_at is not None

    asyncio.run(scenario())


def test_stats_top_users():
    """Топ-N по убыванию, срез STATS_TOP_USERS."""
    async def scenario():
        clock = FakeClock()
        mw = _make_middleware(clock, burst=2)
        async def handler(event, data):
            return "OK"
        async def answer(text=None, show_alert=False):
            pass
        update = _make_update(answer)

        for uid in range(10, 17):  # юзеры 10..16: 1..7 троттлингов
            bucket = TokenBucket(1, 5.0, clock=clock)
            bucket.tokens = 0.0  # бакет предисчерпан
            mw._buckets[uid] = bucket
            data = {"event_from_user": SimpleNamespace(id=uid)}
            for _ in range(uid - 9):
                assert await mw(handler, update, data) is None

        snap = mw.stats_snapshot()
        assert len(snap.throttled_by_user) == mw.STATS_TOP_USERS
        values = list(snap.throttled_by_user.values())
        assert values == sorted(values, reverse=True)
        assert snap.throttled_by_user.get(16) == 7

    asyncio.run(scenario())


def test_stats_prune_clears_counters():
    """Счётчик троттлингов уходит вместе с протухшим бакетом."""
    async def scenario():
        clock = FakeClock()
        mw = _make_middleware(clock, burst=2)
        async def handler(event, data):
            return "OK"
        async def answer(text=None, show_alert=False):
            pass
        update = _make_update(answer)
        u1 = {"event_from_user": SimpleNamespace(id=1)}

        mw._prune_counter = mw._PRUNE_EVERY - 1
        mw._buckets[777] = TokenBucket(1, 1.0, clock=lambda: clock.t - 7200)
        mw._throttled_by_user[777] = 42

        await mw(handler, update, u1)  # триггерит prune
        assert 777 not in mw._buckets
        assert 777 not in mw._throttled_by_user

    asyncio.run(scenario())
