"""Утренняя сводка постерами (этап 4 ТЗ v2.2) — без правок текстового конвейера.

Механика «опережающей доставки»:
- джоба запускается на 20-й секунде минуты (текстовая сводка — на 30-й);
- отправляет постеры пользователям с prefer_image_schedule=1, чьё
  morning_summary_time совпадает с текущей минутой;
- фиксирует доставку ТЕМИ ЖЕ ключами дедупликации, что и текстовый
  конвейер (notification_type + source_id + recipient_id);
- когда на 30-й секунде запускается текстовая сводка, pipeline
  отбрасывает уже доставленных (drop_already_delivered) — дубликатов нет.

Graceful degradation: любой сбой (рендер, circuit breaker, отправка)
-> доставка НЕ фиксируется -> пользователь получает обычную текстовую
сводку на :30. Пустой день не отправляется (паритет с коллектором).

Рендеры идут как системные вызовы (user_id=None): мимо per-user rate
limiter, через общий semaphore — постер уже прогрет warm-up'ом в 6:30.
Ключи кэша совпадают с интерактивным просмотром дня: утром пользователь
видит тот же постер, что и по кнопке «Моё расписание».
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.callbacks import DayChangesCD
from bot.utils.poster_delivery import build_day_caption, send_poster
from config import config
from core.repository.notification_repository import NotificationRepository
from core.repository.schedule_repository import ScheduleRepository
from services.extra_classes_service import ExtraClassesService
from services.image_preferences import ImagePreferencesService
from services.image_render.exceptions import ImageRenderError
from services.image_render.poster_factory import (
    build_global_request_id,
    build_personal_request_id,
    build_poster_request,
    extra_classes_hash,
)
from services.image_render.service import ImageGenerationService
from services.image_render.version import get_schedule_version
from services.schedule_service import ScheduleService
from services.time_service import TimeService

logger = logging.getLogger(__name__)

_WEEKDAYS_RU = {
    1: "Понедельник", 2: "Вторник", 3: "Среда", 4: "Четверг",
    5: "Пятница", 6: "Суббота", 7: "Воскресенье",
}

# Мягкий темп между отправками (диспетчер текстовых уведомлений
# держит 0.045с глобально; постеров за минуту обычно единицы).
_SEND_INTERVAL_SEC = 0.05


def _date_text(date_iso: str) -> str:
    value = date.fromisoformat(date_iso)
    weekday = _WEEKDAYS_RU.get(value.isoweekday(), "")
    return f"{weekday}, {value.strftime('%d.%m')}"


class _BotPosterAdapter:
    """Bot.send_photo -> протокол answer_photo из poster_delivery."""

    def __init__(self, bot: Bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def answer_photo(self, photo, caption=None, reply_markup=None):  # noqa: ANN001
        return await self._bot.send_photo(
            chat_id=self._chat_id,
            photo=photo,
            caption=caption,
            reply_markup=reply_markup,
        )


def _changes_keyboard(
    *,
    target_kind: str,
    target_id,
    class_id: str,
    group_id: str,
    date_iso: str,
) -> InlineKeyboardMarkup:
    """Кнопка «Изменения» — та же, что у текстовой сводки (DayChangesCD)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Изменения",
                    callback_data=DayChangesCD(
                        target_kind=target_kind,
                        target_id=target_id,
                        class_id=class_id,
                        group_id=group_id,
                        date_iso=date_iso,
                        origin="teacher" if target_kind == "teacher" else "class",
                        return_to="morning",
                    ).pack(),
                )
            ]
        ]
    )


async def send_morning_posters(
    *,
    bot: Bot,
    time_service: TimeService,
    notification_repo: NotificationRepository,
    schedule_repo: ScheduleRepository,
    schedule_service: ScheduleService,
    extra_classes_service: ExtraClassesService,
    image_service: ImageGenerationService,
    image_prefs: ImagePreferencesService,
) -> dict[str, int]:
    """Тик утренней рассылки постерами (cron: каждые :20 секунды минуты)."""
    result = {"sent": 0, "text_pref": 0, "empty_days": 0, "failures": 0}

    if not config.ENABLE_IMAGE_GENERATION:
        return result

    now = time_service.get_now_base()
    time_str = now.strftime("%H:%M")
    today_iso = now.date().isoformat()
    weekday = now.isoweekday()

    try:
        blocked = set(await notification_repo.get_blocked_user_ids())
    except Exception:  # noqa: BLE001 — без списка блокировок тик небезопасен
        logger.exception("Morning posters: blocked users недоступны — тик пропущен")
        return result

    version = await get_schedule_version(schedule_repo)

    # 1. Ученики и их родители/наблюдатели
    try:
        tasks = await notification_repo.get_morning_summary_tasks(time_str=time_str)
    except Exception:  # noqa: BLE001
        logger.exception("Morning posters: задачи утренней сводки недоступны")
        tasks = []

    for task in tasks:
        if task.recipient_id in blocked:
            continue
        if not await image_prefs.prefers_image(task.recipient_id):
            result["text_pref"] += 1
            continue
        status = await _deliver_student_poster(
            task,
            bot=bot,
            image_service=image_service,
            schedule_service=schedule_service,
            extra_classes_service=extra_classes_service,
            notification_repo=notification_repo,
            version=version,
            today_iso=today_iso,
            weekday=weekday,
        )
        result[status] = result.get(status, 0) + 1
        if status == "sent":
            await asyncio.sleep(_SEND_INTERVAL_SEC)

    # 2. Учителя
    try:
        teacher_tasks = await notification_repo.get_teacher_morning_summary_tasks(
            time_str=time_str
        )
    except Exception:  # noqa: BLE001
        logger.exception("Morning posters: задачи утренней сводки учителей недоступны")
        teacher_tasks = []

    for task in teacher_tasks:
        if task.recipient_id in blocked:
            continue
        if not await image_prefs.prefers_image(task.recipient_id):
            result["text_pref"] += 1
            continue
        status = await _deliver_teacher_poster(
            task,
            bot=bot,
            image_service=image_service,
            schedule_service=schedule_service,
            notification_repo=notification_repo,
            version=version,
            today_iso=today_iso,
        )
        result[status] = result.get(status, 0) + 1
        if status == "sent":
            await asyncio.sleep(_SEND_INTERVAL_SEC)

    if result["sent"] or result["failures"]:
        logger.info("Morning posters: %s (time=%s)", result, time_str)
    return result


async def _deliver_student_poster(
    task,
    *,
    bot: Bot,
    image_service: ImageGenerationService,
    schedule_service: ScheduleService,
    extra_classes_service: ExtraClassesService,
    notification_repo: NotificationRepository,
    version: str,
    today_iso: str,
    weekday: int,
) -> str:
    """Возвращает 'sent' | 'empty' | 'failed' (failed = текстовый фолбэк)."""
    try:
        day_dto = await schedule_service.get_daily_schedule_for_student(
            class_id=task.class_id,
            group_id=task.group_id or "ALL",
            date_iso=today_iso,
            student_id=task.target_student_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Morning posters: расписание недоступно (student_id=%s)",
            task.target_student_id,
        )
        return "failed"

    if not day_dto.lessons:
        return "empty"  # паритет с коллектором: пустой день не отправляем

    # Ключ — как в интерактивном просмотре: персональный при наличии доп. занятий
    request_id = build_global_request_id(
        version, task.class_id, task.group_id or "ALL", today_iso
    )
    if task.target_student_id is not None:
        extras = await extra_classes_service.get_extra_classes_for_student(
            student_id=task.target_student_id, day_of_week=weekday
        )
        if extras:
            request_id = build_personal_request_id(
                version, task.target_student_id, today_iso, extra_classes_hash(extras)
            )

    subtitle = task.child_name if task.recipient_kind == "adult" else None
    request = build_poster_request(
        request_id=request_id,
        dto=day_dto,
        title=f"Расписание · {day_dto.class_name or task.class_id}",
        date_text=_date_text(today_iso),
        subtitle=subtitle,
        width=config.POSTER_WIDTH,
    )

    # Системный вызов: мимо per-user лимита, через semaphore и breaker
    try:
        poster = await image_service.get_poster(request, user_id=None)
    except ImageRenderError:
        logger.warning(
            "Morning posters: рендер не удался (student_id=%s) — текстовый фолбэк",
            task.target_student_id,
            exc_info=True,
        )
        return "failed"

    keyboard = (
        _changes_keyboard(
            target_kind="student",
            target_id=task.target_student_id,
            class_id=str(task.class_id),
            group_id=str(task.group_id or "ALL"),
            date_iso=today_iso,
        )
        if request.changes_count
        else None
    )
    caption = build_day_caption(_date_text(today_iso), request.changes_count, subtitle)

    try:
        await send_poster(
            _BotPosterAdapter(bot, task.recipient_id),
            image_service,
            poster,
            caption,
            keyboard,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Morning posters: отправка не удалась (recipient=%s) — текстовый фолбэк",
            task.recipient_id,
        )
        return "failed"

    await _record_delivery(
        notification_repo,
        notification_type="morning_summary",
        source_id=f"morning_summary_{task.target_student_id}",
        recipient_id=task.recipient_id,
        today_iso=today_iso,
    )
    return "sent"


async def _deliver_teacher_poster(
    task,
    *,
    bot: Bot,
    image_service: ImageGenerationService,
    schedule_service: ScheduleService,
    notification_repo: NotificationRepository,
    version: str,
    today_iso: str,
) -> str:
    """Постер расписания учителя. 'sent' | 'empty' | 'failed'."""
    try:
        day_dto = await schedule_service.get_daily_schedule_for_teacher(
            teacher_id=task.teacher_id,
            date_iso=today_iso,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Morning posters: расписание учителя недоступно (teacher_id=%s)",
            task.teacher_id,
        )
        return "failed"

    if not day_dto.lessons:
        return "empty"

    # Префикс T — как в lesson_id нормализатора: не пересекается с ключами классов
    request = build_poster_request(
        request_id=build_global_request_id(version, f"T{task.teacher_id}", "ALL", today_iso),
        dto=day_dto,
        title=f"Расписание · {task.teacher_name or 'учитель'}",
        date_text=_date_text(today_iso),
        subtitle=task.teacher_name,
        is_teacher=True,
        width=config.POSTER_WIDTH,
    )

    try:
        poster = await image_service.get_poster(request, user_id=None)
    except ImageRenderError:
        logger.warning(
            "Morning posters: рендер не удался (teacher_id=%s) — текстовый фолбэк",
            task.teacher_id,
            exc_info=True,
        )
        return "failed"

    keyboard = (
        _changes_keyboard(
            target_kind="teacher",
            target_id=task.teacher_id,
            class_id="ALL",
            group_id="ALL",
            date_iso=today_iso,
        )
        if request.changes_count
        else None
    )
    caption = build_day_caption(_date_text(today_iso), request.changes_count, task.teacher_name)

    try:
        await send_poster(
            _BotPosterAdapter(bot, task.recipient_id),
            image_service,
            poster,
            caption,
            keyboard,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Morning posters: отправка не удалась (teacher recipient=%s)",
            task.recipient_id,
        )
        return "failed"

    await _record_delivery(
        notification_repo,
        notification_type="teacher_morning",
        source_id=f"teacher_morning_{task.teacher_id}",
        recipient_id=task.recipient_id,
        today_iso=today_iso,
    )
    return "sent"


async def _record_delivery(
    repo: NotificationRepository,
    *,
    notification_type: str,
    source_id: str,
    recipient_id: int,
    today_iso: str,
) -> None:
    """Фиксирует доставку ключами текстового конвейера.

    Ключи обязаны СТРОГО совпадать с collect_morning_summaries /
    collect_teacher_morning_summaries — иначе пользователь получит
    и постер, и текст. При сбое записи логируем (риск дубля текстом).
    """
    try:
        await repo.record_notification_delivery(
            notification_type=notification_type,
            notification_date=today_iso,
            source_id=source_id,
            recipient_id=recipient_id,
        )
    except Exception:  # noqa: BLE001
        logger.error(
            "Morning posters: доставка не записана (recipient=%s) — возможен дубликат текстом",
            recipient_id,
            exc_info=True,
        )
