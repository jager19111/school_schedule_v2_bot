# services/notifications_service.py
import logging
import datetime
from aiogram import Bot

from core.repository.notification_repository import NotificationRepository
from core.repository.extra_classes_repository import ExtraClassesRepository
from core.repository.schedule_repository import ScheduleRepository
from services.time_service import TimeService
from bot.utils.ui_renderer import UIRenderer
from core.models.dto import (
    LessonReminderDTO, 
    ChangeReminderDTO, 
    MorningSummaryDTO, 
    MorningLessonDTO
)

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Сервис уведомлений (Strict DTO & Repository Pattern).
    Обеспечивает 100% отказоустойчивость рассылок.
    Введено жесткое использование именованных аргументов для защиты от TypeError.
    """

    def __init__(
        self,
        bot: Bot,
        notification_repo: NotificationRepository,
        time_service: TimeService,
        schedule_repo: ScheduleRepository,
        extra_classes_repo: ExtraClassesRepository,
    ):
        self.bot = bot
        self.repo = notification_repo
        self.time_service = time_service
        self.schedule_repo = schedule_repo
        self.extra_classes_repo = extra_classes_repo

    async def _safe_send(self, user_id: int, text: str) -> bool:
        """Внутренний метод для 100% отказоустойчивости отправки."""
        try:
            await self.bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
            return True
        except Exception as e:
            logger.warning("Failed to send notification to %s: %s", user_id, e)
            return False

    # ---------- 1. Утренняя сводка ----------
    async def send_morning_reminders(self) -> None:
        """
        Формирует и отправляет утренние сводки.

        Ребёнок получает сводку только по себе.
        Взрослый получает одно сообщение, объединяющее сводки всех детей,
        на которых он подписан через parent_child_settings.

        Успешные доставки логируются отдельно по каждой паре:
            recipient_id + target_child_id + date.
        """
        now = self.time_service.get_now_base()
        current_time_str = now.strftime("%H:%M")
        today_iso = now.date().isoformat()
        weekday = now.isoweekday()

        tasks = await self.repo.get_morning_summary_tasks(
            time_str=current_time_str,
        )

        if not tasks:
            return

        logger.info(
            "Morning summary tick: date=%s, time=%s, tasks=%d",
            today_iso,
            current_time_str,
            len(tasks),
        )

        metadata = await self.schedule_repo.get_metadata()
        classes = metadata.get("classes", {})
        groups = metadata.get("groups", {})

        summaries_by_recipient: dict[int, list[tuple[dict, MorningSummaryDTO]]] = {}

        for task in tasks:
            try:
                recipient_id = int(task["recipient_id"])
                target_child_id = int(task["target_child_id"])

                source_id = f"morning_summary:{target_child_id}"

                already_sent = await self.repo.is_notification_delivered(
                    notification_type="morning_summary",
                    notification_date=today_iso,
                    source_id=source_id,
                    recipient_id=recipient_id,
                )

                if already_sent:
                    continue

                child_class_id = task.get("class_id")
                child_group_id = task.get("group_id")

                lessons_dtos: list[MorningLessonDTO] = []

                if child_class_id:
                    raw_lessons = await self.schedule_repo.get_lessons_for_class(
                        class_id=child_class_id,
                        date_iso=today_iso,
                    )

                    for lesson in raw_lessons:
                        lesson_group_id = lesson.get("group_id", "ALL")

                        if (
                            lesson_group_id != "ALL"
                            and child_group_id != "ALL"
                            and lesson_group_id != child_group_id
                        ):
                            continue

                        group_name = None

                        if lesson_group_id != "ALL":
                            group_name = groups.get(
                                lesson_group_id,
                                f"Группа {lesson_group_id}",
                            )

                        lessons_dtos.append(
                            MorningLessonDTO(
                                lesson_num=lesson["lesson_num"],
                                start_time=lesson["start_time"],
                                end_time=lesson["end_time"],
                                subject_name=lesson["subject_name"] or "—",
                                room_name=lesson["room_name"] or "—",
                                is_cancelled=bool(
                                    lesson["is_cancelled"]
                                ),
                                is_exchange=bool(
                                    lesson["is_exchange"]
                                ),
                                is_extra=False,
                                group_name=group_name,
                            )
                        )

                raw_extras = await self.extra_classes_repo.get_extra_classes_for_user(
                    user_id=target_child_id,
                    day_of_week=weekday,
                )

                for extra in raw_extras:
                    lessons_dtos.append(
                        MorningLessonDTO(
                            lesson_num=None,
                            start_time=extra["time_start"],
                            end_time=extra["time_end"],
                            subject_name=extra["title"],
                            room_name=extra["location"] or "—",
                            is_cancelled=False,
                            is_exchange=False,
                            is_extra=True,
                        )
                    )

                # Не отправляем пустую сводку и не фиксируем delivery log.
                # Если данные появятся позже в этот же день, следующий вызов
                # сможет сформировать полноценную сводку.
                if not lessons_dtos:
                    logger.debug(
                        "Morning summary skipped: no lessons, "
                        "recipient_id=%s, child_id=%s",
                        recipient_id,
                        target_child_id,
                    )
                    continue

                lessons_dtos.sort(
                    key=lambda item: (
                        item.start_time,
                        item.lesson_num if item.lesson_num is not None else 99,
                    )
                )

                class_name = child_class_id

                if child_class_id and child_class_id in classes:
                    class_obj = classes[child_class_id]
                    class_name = getattr(
                        class_obj,
                        "name",
                        child_class_id,
                    )

                summary_dto = MorningSummaryDTO(
                    date_iso=today_iso,
                    lessons=lessons_dtos,
                    child_name=(
                        task["child_name"]
                        if task["recipient_kind"] == "adult"
                        else None
                    ),
                    class_id=class_name,
                )

                summaries_by_recipient.setdefault(
                    recipient_id,
                    [],
                ).append((task, summary_dto))

            except (KeyError, TypeError, ValueError) as exc:
                logger.exception(
                    "Invalid morning summary task: task=%r, error=%s",
                    task,
                    exc,
                )
            except Exception:
                logger.exception(
                    "Unexpected morning summary assembly error: task=%r",
                    task,
                )

        for recipient_id, entries in summaries_by_recipient.items():
            try:
                rendered_parts = [
                    UIRenderer.render_morning_summary(summary_dto)
                    for _, summary_dto in entries
                ]

                final_text = "\n\n───────────────\n\n".join(rendered_parts)

                sent = await self._safe_send(
                    user_id=recipient_id,
                    text=final_text,
                )

                if not sent:
                    logger.warning(
                        "Morning summary send failed: recipient_id=%s, "
                        "children=%s",
                        recipient_id,
                        [
                            task["target_child_id"]
                            for task, _ in entries
                        ],
                    )
                    continue

                for task, _ in entries:
                    target_child_id = int(task["target_child_id"])

                    await self.repo.record_notification_delivery(
                        notification_type="morning_summary",
                        notification_date=today_iso,
                        source_id=f"morning_summary:{target_child_id}",
                        recipient_id=recipient_id,
                    )

                logger.info(
                    "Morning summary delivered: recipient_id=%s, "
                    "children=%s",
                    recipient_id,
                    [
                        task["target_child_id"]
                        for task, _ in entries
                    ],
                )

            except Exception:
                logger.exception(
                    "Morning summary sending error: recipient_id=%s",
                    recipient_id,
                )

    # ---------- 2. Уведомления об изменениях ----------
    async def send_upcoming_changes(self) -> None:
        """
        Отправляет адресные уведомления о заменах и отменах.

        Каждая успешная доставка фиксируется отдельно для каждого ребёнка,
        родителя или observer в notification_delivery_log.
        """

        now = self.time_service.get_now_base()
        today = now.date()
        today_iso = today.isoformat()

        changes = await self.repo.get_pending_changes()

        logger.info(
            "Schedule changes tick: date=%s, changes=%d",
            today_iso,
            len(changes),
        )

        for change in changes:
            try:
                change_date = self.time_service.date_from_iso(
                    change["date"],
                )

                recipients = await self.repo.get_recipients_for_schedule_change(
                    class_id=change["class_id"],
                    group_id=change["group_id"],
                )

                for recipient in recipients:
                    recipient_id = int(recipient["recipient_id"])
                    window_days = int(
                        recipient["changes_window_days"]
                    )

                    # Ноль означает: получатель не хочет уведомления
                    # об изменениях вперёд.
                    if window_days <= 0:
                        continue

                    max_date = today + datetime.timedelta(
                        days=window_days,
                    )

                    if not (today <= change_date <= max_date):
                        continue

                    already_sent = await self.repo.is_notification_delivered(
                        notification_type="schedule_change",
                        notification_date=change["date"],
                        source_id=change["id"],
                        recipient_id=recipient_id,
                    )

                    if already_sent:
                        continue

                    dto = ChangeReminderDTO(
                        date=change["date"],
                        lesson_num=change["lesson_num"],
                        subject_name=change["subject_name"] or "—",
                        is_cancelled=bool(change["is_cancelled"]),
                        child_name=(
                            recipient["child_name"]
                            if recipient["recipient_kind"] == "adult"
                            else None
                        ),
                    )

                    sent = await self._safe_send(
                        user_id=recipient_id,
                        text=UIRenderer.render_change_reminder(dto),
                    )

                    if not sent:
                        logger.warning(
                            "Schedule change send failed: change_id=%s, "
                            "recipient_id=%s",
                            change["id"],
                            recipient_id,
                        )
                        continue

                    await self.repo.record_notification_delivery(
                        notification_type="schedule_change",
                        notification_date=change["date"],
                        source_id=change["id"],
                        recipient_id=recipient_id,
                    )

                    logger.info(
                        "Schedule change delivered: change_id=%s, "
                        "child_id=%s, recipient_id=%s, "
                        "recipient_kind=%s",
                        change["id"],
                        recipient["child_id"],
                        recipient_id,
                        recipient["recipient_kind"],
                    )

            except (KeyError, TypeError, ValueError) as exc:
                logger.exception(
                    "Invalid schedule change task: change=%r, error=%s",
                    change,
                    exc,
                )
            except Exception:
                logger.exception(
                    "Unexpected schedule change notification error: change=%r",
                    change,
                )
    # ---------- 3. Предурочные уведомления ----------
    async def send_pre_lesson_reminders(self) -> None:
        """
        Отправляет адресные предурочные напоминания.

        Каждый ребёнок и каждый взрослый — независимый получатель.
        Успешная доставка фиксируется в notification_delivery_log, поэтому
        повторный scheduler-run не создаёт дубликаты.
        """
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()

        lessons = await self.repo.get_todays_lessons_for_pre_reminders(
            date_iso=today_iso,
        )

        logger.info(
            "Pre-lesson reminder tick: date=%s, lessons=%d",
            today_iso,
            len(lessons),
        )

        for lesson in lessons:
            try:
                lesson_start_at = datetime.datetime.strptime(
                    f"{today_iso} {lesson['start_time']}",
                    "%Y-%m-%d %H:%M",
                ).replace(tzinfo=self.time_service.base_tz)

                delta_minutes = (
                    lesson_start_at - now
                ).total_seconds() / 60.0

                # Урок уже начался или прошёл.
                if delta_minutes <= 0:
                    continue

                recipients = await self.repo.get_recipients_for_pre_lesson_reminder(
                    class_id=lesson["class_id"],
                    group_id=lesson["group_id"],
                )

                for recipient in recipients:
                    recipient_id = int(recipient["recipient_id"])
                    offset_minutes = int(recipient["offset_minutes"])

                    # Значение 0 означает: данный получатель отключил этот тип
                    # напоминаний через личную настройку времени.
                    if offset_minutes <= 0:
                        continue

                    # До окна уведомления ещё далеко.
                    if delta_minutes > offset_minutes:
                        continue

                    already_sent = await self.repo.is_notification_delivered(
                        notification_type="pre_lesson",
                        notification_date=today_iso,
                        source_id=lesson["id"],
                        recipient_id=recipient_id,
                    )

                    if already_sent:
                        continue

                    dto = LessonReminderDTO(
                        subject_name=lesson["subject_name"] or "—",
                        start_time=lesson["start_time"],
                        room_name=lesson["room_name"] or "—",
                        is_extra=False,
                        child_name=(
                            recipient["child_name"]
                            if recipient["recipient_kind"] == "adult"
                            else None
                        ),
                    )

                    sent = await self._safe_send(
                        user_id=recipient_id,
                        text=UIRenderer.render_lesson_reminder(dto),
                    )

                    if not sent:
                        logger.warning(
                            "Pre-lesson reminder send failed: lesson_id=%s, "
                            "recipient_id=%s",
                            lesson["id"],
                            recipient_id,
                        )
                        continue

                    await self.repo.record_notification_delivery(
                        notification_type="pre_lesson",
                        notification_date=today_iso,
                        source_id=lesson["id"],
                        recipient_id=recipient_id,
                    )

                    logger.info(
                        "Pre-lesson reminder delivered: lesson_id=%s, "
                        "child_id=%s, recipient_id=%s, recipient_kind=%s",
                        lesson["id"],
                        recipient["child_id"],
                        recipient_id,
                        recipient["recipient_kind"],
                    )

            except (KeyError, TypeError, ValueError) as exc:
                logger.exception(
                    "Invalid pre-lesson reminder task: lesson=%r, error=%s",
                    lesson,
                    exc,
                )
            except Exception:
                logger.exception(
                    "Unexpected pre-lesson reminder error: lesson=%r",
                    lesson,
                )


    # ---------- 4. Уведомления о доп. занятиях ----------
    async def send_extra_class_reminders(self) -> None:
        """
        Отправляет адресные напоминания о дополнительных занятиях.

        Получатели формируются в NotificationRepository:
        - ребёнок получает только своё занятие;
        - взрослые получают занятия только тех детей, на которых подписаны.

        Успешные отправки фиксируются в notification_delivery_log. Это защищает
        от дублей при минутном scheduler и при перезапуске приложения.
        """
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()
        weekday = now.isoweekday()

        extras = await self.repo.get_todays_extra_classes_for_reminders(
            day_of_week=weekday,
        )

        logger.info(
            "Extra reminder tick: date=%s, weekday=%s, candidates=%d",
            today_iso,
            weekday,
            len(extras),
        )

        for extra in extras:
            try:
                extra_id = int(extra["extra_id"])
                recipient_id = int(extra["recipient_id"])
                offset_minutes = int(extra["offset_minutes"])

                if offset_minutes <= 0:
                    logger.debug(
                        "Extra reminder disabled by zero offset: extra_id=%s, "
                        "recipient_id=%s",
                        extra_id,
                        recipient_id,
                    )
                    continue

                start_at = datetime.datetime.strptime(
                    f"{today_iso} {extra['time_start']}",
                    "%Y-%m-%d %H:%M",
                ).replace(tzinfo=self.time_service.base_tz)

                delta_minutes = (
                    start_at - now
                ).total_seconds() / 60.0

                logger.debug(
                    "Extra candidate: extra_id=%s, child_id=%s, "
                    "recipient_id=%s, recipient_kind=%s, start=%s, "
                    "offset=%s, delta=%.2f",
                    extra_id,
                    extra["child_id"],
                    recipient_id,
                    extra["recipient_kind"],
                    extra["time_start"],
                    offset_minutes,
                    delta_minutes,
                )

                # Занятие уже началось: обычное pre-reminder больше не нужно.
                if delta_minutes <= 0:
                    continue

                # Ещё не вошли в окно напоминания.
                if delta_minutes > offset_minutes:
                    continue

                source_id = str(extra_id)

                already_sent = await self.repo.is_notification_delivered(
                    notification_type="extra_class",
                    notification_date=today_iso,
                    source_id=source_id,
                    recipient_id=recipient_id,
                )

                if already_sent:
                    continue

                dto = LessonReminderDTO(
                    subject_name=extra["title"],
                    start_time=extra["time_start"],
                    room_name=extra["location"] or "—",
                    is_extra=True,
                    child_name=(
                        extra["child_name"]
                        if extra["recipient_kind"] == "adult"
                        else None
                    ),
                )

                sent = await self._safe_send(
                    user_id=recipient_id,
                    text=UIRenderer.render_lesson_reminder(dto),
                )

                if not sent:
                    logger.warning(
                        "Extra reminder send failed: extra_id=%s, "
                        "recipient_id=%s",
                        extra_id,
                        recipient_id,
                    )
                    continue

                logged = await self.repo.record_notification_delivery(
                    notification_type="extra_class",
                    notification_date=today_iso,
                    source_id=source_id,
                    recipient_id=recipient_id,
                )

                logger.info(
                    "Extra reminder delivered: extra_id=%s, child_id=%s, "
                    "recipient_id=%s, recipient_kind=%s, log_created=%s",
                    extra_id,
                    extra["child_id"],
                    recipient_id,
                    extra["recipient_kind"],
                    logged,
                )

            except (KeyError, TypeError, ValueError) as exc:
                logger.exception(
                    "Invalid extra reminder task: task=%r, error=%s",
                    extra,
                    exc,
                )
            except Exception:
                logger.exception(
                    "Unexpected extra reminder processing error: task=%r",
                    extra,
                )