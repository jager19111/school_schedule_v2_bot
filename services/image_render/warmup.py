"""Утренний прогрев кэша постеров (этап 3, системная задача).

Трейд-офф v1 (зафиксирован в обсуждении): warm-up идёт как системная
задача — в обход per-user rate limiter (user_id=None), но через общий
semaphore и circuit breaker. Пользователь, открывший бот до завершения
прогрева, встанет в общую очередь за системными рендерами — приемлемо
для раннего утра с минимальным трафиком.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from config import config
from core.repository.schedule_repository import ScheduleRepository
from services.image_render.exceptions import ImageRenderError
from services.image_render.poster_factory import (
    build_global_request_id,
    build_poster_request,
)
from services.image_render.service import ImageGenerationService
from services.image_render.version import get_schedule_version
from services.schedule_service import ScheduleService

logger = logging.getLogger(__name__)

_WEEKDAYS_RU = {
    1: "Понедельник", 2: "Вторник", 3: "Среда", 4: "Четверг",
    5: "Пятница", 6: "Суббота", 7: "Воскресенье",
}


def _today_iso() -> str:
    """Сегодня в таймзоне школы (нельзя смешивать с UTC-датой сервера)."""
    return datetime.now(ZoneInfo(config.TIMEZONE)).date().isoformat()


def _date_text(date_iso: str) -> str:
    value = date.fromisoformat(date_iso)
    weekday = _WEEKDAYS_RU.get(value.isoweekday(), "")
    return f"{weekday}, {value.strftime('%d.%m')}"


async def warmup_day_posters(
    *,
    image_service: ImageGenerationService,
    schedule_service: ScheduleService,
    schedule_repo: ScheduleRepository,
) -> dict[str, int]:
    """Прогревает глобальный кэш L1 постерами на сегодня по всем классам.

    Утренний пик (все смотрят расписание в 7:30) будет отдаваться
    из кэша/по file_id мгновенно. Ошибки отдельных классов не прерывают
    прогрев; сводка пишется в лог для калибровки констант.
    """
    classes = await schedule_service.get_classes_list()
    version = await get_schedule_version(schedule_repo)
    date_iso = _today_iso()

    rendered = 0
    skipped = 0
    failed = 0
    for class_id in classes.classes:
        try:
            day_dto = await schedule_service.get_daily_schedule_for_class(
                class_id=class_id,
                date_iso=date_iso,
            )
        except Exception:  # noqa: BLE001 — сбой одного класса не роняет прогрев
            failed += 1
            logger.warning("warmup: не удалось получить расписание %s", class_id, exc_info=True)
            continue
        if not day_dto.lessons:
            skipped += 1
            continue
        request = build_poster_request(
            request_id=build_global_request_id(version, class_id, "ALL", date_iso),
            dto=day_dto,
            title=f"Расписание · {day_dto.class_name or class_id}",
            date_text=_date_text(date_iso),
            width=config.POSTER_WIDTH,
        )
        try:
            # Системный вызов: user_id=None -> мимо rate limiter, через semaphore
            await image_service.get_poster(request, user_id=None)
            rendered += 1
        except ImageRenderError:
            failed += 1
            logger.warning("warmup: рендер %s не удался", class_id, exc_info=True)

    logger.info(
        "Warm-up постеров завершён: отрендерено=%d, пустых дней=%d, ошибок=%d",
        rendered,
        skipped,
        failed,
    )
    return {"rendered": rendered, "skipped": skipped, "failed": failed}
