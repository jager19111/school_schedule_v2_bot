# bot/middlewares/antiflood.py
#
# Этап «Аудит», пункт 7: anti-flood защита.
#
# Модель угрозы:
# - ребёнок, листающий расписание (5–10 нажатий за пару секунд) —
#   это НОРМА, защита обязана пропускать;
# - зажатая клавиша, макрос, залипшая мышь — сотни событий в секунду,
#   SQLite с busy_timeout 5с начинает лагать для ВСЕХ пользователей;
# - злонамеренный спам command/callback из скрипта.
#
# Решение — token bucket на пользователя:
# - burst=20 событий мгновенно (всплеск), далее 5 токенов/сек;
# - админы (ADMIN_IDS) не троттлятся;
# - троттленный callback получает короткий ответ не чаще раза в
#   answer_cooldown секунд (ответ на callback не создаёт сообщений
#   в чате и не разгоняет исходящий трафик);
# - троттленные message молча отбрасываются: автоответ на спам
#   сам стал бы спамом (усиление атаки);
# - часы — time.monotonic: ночные NTP-скачки на сервере не рвут лимиты;
# - бакеты неактивных пользователей чистятся амортизированно
#   (проверка раз в 1024 события), память не растёт бесконечно;
# - epsilon + антидрейф в TokenBucket закрывают граничный случай
#   «ровно один токен» (2.0 - 1.0 - 1.0 может дать -1e-16 в float).
#
# Статистика (stats_snapshot):
# - allowed/throttled total — полный счётчик с запуска бота;
# - топ-5 нарушителей — кто долбится в потолок;
# - last_throttled_at — wall-clock (time.time) для отображения,
#   не для расчётов;
# - tracked_users — активных бакетов (после prune — реально активные).
# Счётчики живут в памяти процесса: рестарт обнуляет — это норма
# для операционной статистики, не для аудита.
# Счётчики троттлингов удаляются вместе с протухшим бакетом (prune),
# чтобы топ не забивался одноразовыми ботами недельной давности.
#
# Регистрация в main.py (до include_router):
#
#     dp.update.outer_middleware(
#         AntiFloodMiddleware(admin_ids=set(config.ADMIN_IDS)),
#     )
#
# И тот же экземпляр — в workflow_data для /stats:
#
#     dp.workflow_data.update(antiflood=antiflood_instance, ...)
#
# Проверено: burst/refill/epsilon/NTP-скачок/eviction + 9 сценариев
# клея + статистика (счётчики, топ-5, сортировка, prune-очистка,
# админ/аноним не считаются, рендер секции).

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject, User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AntiFloodStatsDTO:
    """Снимок статистики anti-flood для /stats."""

    allowed_total: int
    throttled_total: int
    tracked_users: int
    throttled_by_user: Dict[int, int]
    last_throttled_at: Optional[float]


class TokenBucket:
    """Token bucket: всплеск + плавное восстановление.

    EPS + антидрейф закрывают граничный случай «ровно один токен»
    (float-арифметика 0.9999999 вместо 1.0).
    """

    __slots__ = ("capacity", "rate", "tokens", "last_refill", "_clock")
    EPS = 1e-9

    def __init__(
        self,
        capacity: int,
        rate: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.capacity = float(capacity)
        self.rate = float(rate)
        self.tokens = float(capacity)
        self.last_refill = clock()
        self._clock = clock

    def allow(self) -> bool:
        now = self._clock()
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(
                self.capacity, self.tokens + elapsed * self.rate,
            )
            self.last_refill = now
        if self.tokens >= 1.0 - self.EPS:
            self.tokens -= 1.0
            if self.tokens < 0.0:
                self.tokens = 0.0
            return True
        return False

    @property
    def retry_after(self) -> float:
        """Секунды до появления одного токена."""
        return max(0.0, (1.0 - self.tokens) / self.rate)


class AntiFloodMiddleware(BaseMiddleware):
    """Anti-flood для всех апдейтов: token bucket на пользователя."""

    PRUNE_AFTER_SECONDS = 3600.0
    _PRUNE_EVERY = 1024
    STATS_TOP_USERS = 5

    def __init__(
        self,
        *,
        burst: int = 10,
        rate_per_second: float = 3.0,
        admin_ids: Optional[set] = None,
        answer_cooldown: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.burst = burst
        self.rate = rate_per_second
        self.admin_ids = admin_ids or set()
        self.answer_cooldown = answer_cooldown
        self._clock = clock
        self._buckets: Dict[int, TokenBucket] = {}
        self._last_answer: Dict[int, float] = {}
        self._prune_counter = 0
        # Счётчики: asyncio однопоточный, блокировки не нужны.
        self._allowed_total = 0
        self._throttled_total = 0
        self._throttled_by_user: Dict[int, int] = {}
        self._last_throttled_at: Optional[float] = None

    async def __call__(
        self,
        handler: Callable,
        event: TelegramObject,
        data: Dict[str, Any],
    ):
        user = data.get("event_from_user") or self._user_from_event(event)
        if user is None or user.id in self.admin_ids:
            return await handler(event, data)

        self._maybe_prune()
        bucket = self._buckets.get(user.id)
        if bucket is None:
            bucket = TokenBucket(self.burst, self.rate, clock=self._clock)
            self._buckets[user.id] = bucket

        if bucket.allow():
            self._allowed_total += 1
            return await handler(event, data)

        self._throttled_total += 1
        self._throttled_by_user[user.id] = (
            self._throttled_by_user.get(user.id, 0) + 1
        )
        # Wall-clock для отображения в /stats; лимиты считаются
        # по monotonic-часам _clock выше.
        self._last_throttled_at = time.time()
        logger.debug(
            "AntiFlood: throttled user_id=%s retry_after=%.2fs",
            user.id,
            bucket.retry_after,
        )
        await self._notify_throttled(event, user.id)
        return None

    def stats_snapshot(self) -> AntiFloodStatsDTO:
        """Снимок для /stats: топ-N нарушителей по убыванию."""
        top = dict(
            sorted(
                self._throttled_by_user.items(),
                key=lambda item: item[1],
                reverse=True,
            )[: self.STATS_TOP_USERS]
        )
        return AntiFloodStatsDTO(
            allowed_total=self._allowed_total,
            throttled_total=self._throttled_total,
            tracked_users=len(self._buckets),
            throttled_by_user=top,
            last_throttled_at=self._last_throttled_at,
        )

    def _maybe_prune(self) -> None:
        self._prune_counter += 1
        if self._prune_counter < self._PRUNE_EVERY:
            return
        self._prune_counter = 0
        now = self._clock()
        stale = [
            user_id
            for user_id, bucket in self._buckets.items()
            if now - bucket.last_refill > self.PRUNE_AFTER_SECONDS
        ]
        for user_id in stale:
            del self._buckets[user_id]
            self._last_answer.pop(user_id, None)
            # Счётчик уходит вместе с бакетом: топ не должен
            # забиваться одноразовыми ботами недельной давности.
            self._throttled_by_user.pop(user_id, None)

    @staticmethod
    def _user_from_event(event: TelegramObject) -> Optional[User]:
        user = getattr(event, "from_user", None)
        if user is not None:
            return user
        for attr in (
            "message", "edited_message", "callback_query", "channel_post",
            "my_chat_member", "chat_join_request", "inline_query",
            "pre_checkout_query",
        ):
            obj = getattr(event, attr, None)
            if obj is not None:
                user = getattr(obj, "from_user", None)
                if user is not None:
                    return user
        return None

    async def _notify_throttled(self, event: TelegramObject, user_id: int) -> None:
        """Ответ на троттленный callback — не чаще cooldown секунд.

        Троттленные message отбрасываются молча: автоответ на спам
        сам стал бы спамом (усиление атаки).
        """
        cb: Optional[CallbackQuery]
        if isinstance(event, CallbackQuery):
            cb = event
        else:
            cb = getattr(event, "callback_query", None)
        if cb is None:
            return

        now = self._clock()
        last = self._last_answer.get(user_id, float("-inf"))
        try:
            if now - last >= self.answer_cooldown:
                self._last_answer[user_id] = now
                await cb.answer("Не так быстро 🙂 Подожди пару секунд.")
            else:
                await cb.answer()
        except Exception:
            logger.debug("AntiFlood: callback answer failed", exc_info=True)
