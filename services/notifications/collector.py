# services/notification/collector.py

import datetime
import logging

from bot import callbacks
from bot.keyboards.keyboard import Keyboards
from bot.utils.ui_renderer import UIRenderer

from core.repository.notification_repository import NotificationRepository
from core.repository.schedule_repository import ScheduleRepository
from services.extra_classes_service import ExtraClassesService
from services.schedule_service import ScheduleService
from services.time_service import TimeService

from core.models.dto import (
    NotificationSendDTO,
    MorningSummaryTaskDTO,
    MorningSummaryDTO,
    MorningLessonDTO,
    LessonReminderDTO,
    ScheduleChangeRecipientDTO,
    TeacherChangeRecipientDTO,
    PreLessonRecipientDTO,
    TeacherPreLessonRecipientDTO,
)
from core.mappers.notification_mapper import NotificationMapper

logger = logging.getLogger(__name__)
MAX_CHANGES_WINDOW_DAYS = 31

class NotificationCollector:
    """Сборщик кандидатов. Превращает данные базы в готовые NotificationSendDTO."""

    def __init__(
        self,
        notification_repo: NotificationRepository,
        time_service: TimeService,
        schedule_repo: ScheduleRepository,
        extra_classes_service: ExtraClassesService,
        schedule_service: ScheduleService,
    ) -> None:
        self.repo = notification_repo
        self.time_service = time_service
        self.schedule_repo = schedule_repo
        self.extra_classes_service = extra_classes_service
        self.schedule_service = schedule_service

    async def collect_morning_summaries(self) -> tuple[list[NotificationSendDTO], int]:
        now = self.time_service.get_now_base()
        current_time_str = now.strftime("%H:%M")
        today_iso = now.date().isoformat()
        weekday = now.isoweekday()

        tasks = await self.repo.get_morning_summary_tasks(time_str=current_time_str)
        if not tasks:
            return [], 0

        metadata = await self.schedule_repo.get_metadata()
        classes = metadata.classes
        groups = metadata.groups

        summaries_by_recipient: dict[int, list[tuple[MorningSummaryTaskDTO, MorningSummaryDTO]]] = {}
        display_numbers_cache: dict[tuple[str, str], dict[int, str]] = {}

        for task in tasks:
            try:
                recipient_id = task.recipient_id
                target_student_id = task.target_student_id
                child_class_id = task.class_id
                child_group_id = task.group_id or "ALL"

                lessons_dtos: list[MorningLessonDTO] = []

                if child_class_id:
                    lessons = await self.schedule_repo.get_lessons_for_class(class_id=child_class_id, date_iso=today_iso)
                    day_permutation = self.schedule_service.detect_day_permutation(lessons)
                    display_key = (child_class_id, today_iso)

                    if display_key not in display_numbers_cache:
                        display_numbers_cache[display_key] = await self.schedule_service.get_display_numbers_for_class_day(
                            class_id=child_class_id, date_iso=today_iso
                        )

                    display_numbers = display_numbers_cache[display_key]
                    user_groups = child_group_id.split(",") if child_group_id != "ALL" else ["ALL"]

                    for lesson in lessons:
                        lesson_group_id = lesson.group_id or "ALL"
                        if "ALL" not in user_groups and lesson_group_id != "ALL" and lesson_group_id not in user_groups:
                            continue

                        group_name = None
                        if lesson_group_id != "ALL":
                            group_name = groups.get(lesson_group_id, f"Группа {lesson_group_id}")

                        lesson_display_num = display_numbers.get(
                            lesson.lesson_num,
                            (str(lesson.lesson_num) if lesson.lesson_num is not None else "•")
                        )

                        lessons_dtos.append(
                            NotificationMapper.map_school_lesson_to_morning_dto(
                                lesson, display_num=lesson_display_num, group_name=group_name, day_permutation=day_permutation,
                            )
                        )

                if target_student_id is not None:
                    extra_items = await self.extra_classes_service.get_extra_classes_for_student(
                        student_id=target_student_id, day_of_week=weekday
                    )
                    lessons_dtos.extend(NotificationMapper.map_extra_to_morning_dto(extra) for extra in extra_items)

                if not lessons_dtos:
                    continue

                lessons_dtos.sort(key=lambda item: (item.start_time or "99:99", item.lesson_num if item.lesson_num is not None else 99))

                class_name = child_class_id
                if child_class_id:
                    class_obj = classes.get(child_class_id)
                    if class_obj is not None:
                        class_name = class_obj.name

                summary_dto = MorningSummaryDTO(
                    date_iso=today_iso,
                    lessons=lessons_dtos,
                    child_name=(task.child_name if task.recipient_kind == "adult" else None),
                    class_id=child_class_id,
                    class_name=class_name,
                    has_permutation=day_permutation,
                    origin="student",
                )
                summaries_by_recipient.setdefault(recipient_id, []).append((task, summary_dto))

            except Exception:
                logger.exception("Unexpected morning summary assembly error: task=%r", task)

        candidates: list[NotificationSendDTO] = []
        for recipient_id, entries in summaries_by_recipient.items():
            for task, summary_dto in entries:
                text = UIRenderer.render_morning_summary(summary_dto)
                has_changes = any((lesson.is_exchange or lesson.is_cancelled) for lesson in summary_dto.lessons if not lesson.is_extra)
                keyboard = None

                if has_changes:
                    changes_data = callbacks.DayChangesCD(
                        target_kind="student", target_id=task.target_student_id,
                        class_id=str(task.class_id), group_id=str(task.group_id or "ALL"),
                        date_iso=today_iso, origin="class", return_to="morning",
                    )
                    keyboard = Keyboards.get_day_changes_kb(changes_data)

                candidates.append(
                    NotificationSendDTO(
                        notification_type="morning_summary",
                        notification_date=today_iso,
                        source_id=f"morning_summary:{task.target_student_id}",
                        recipient_id=recipient_id,
                        text=text,
                        reply_markup=keyboard,
                        context=f"student_id={task.target_student_id}"
                    )
                )

        return candidates, len(tasks)

    async def collect_teacher_morning_summaries(self) -> tuple[list[NotificationSendDTO], int]:
        now = self.time_service.get_now_base()
        current_time_str = now.strftime("%H:%M")
        today_iso = now.date().isoformat()

        tasks = await self.repo.get_teacher_morning_summary_tasks(time_str=current_time_str)
        if not tasks:
            return [], 0

        metadata = await self.schedule_repo.get_metadata()
        classes = metadata.classes
        
        candidates: list[NotificationSendDTO] = []

        for task in tasks:
            try:
                recipient_id = task.recipient_id
                teacher_id = task.teacher_id
                teacher_name = task.teacher_name or "Учитель"

                lessons = await self.schedule_repo.get_lessons_for_teacher(teacher_id=teacher_id, date_iso=today_iso)
                lessons_dtos: list[MorningLessonDTO] = []

                for lesson in lessons:
                    class_name = lesson.class_name
                    if not class_name and lesson.class_id:
                        class_obj = classes.get(lesson.class_id)
                        class_name = class_obj.name if class_obj is not None else lesson.class_id

                    lessons_dtos.append(
                        NotificationMapper.map_school_lesson_to_morning_dto(
                            lesson, display_num=(str(lesson.lesson_num) if lesson.lesson_num is not None else "•"),
                            class_name=class_name, day_permutation=False,
                        )
                    )

                if not lessons_dtos:
                    continue

                lessons_dtos.sort(key=lambda item: (item.start_time, (item.lesson_num if item.lesson_num is not None else 99)))

                summary_dto = MorningSummaryDTO(                    
                    date_iso=today_iso, lessons=lessons_dtos, child_name=None, class_id=None,
                    class_name=None, teacher_name=teacher_name, has_permutation=False, origin="teacher",
                )

                text = UIRenderer.render_morning_summary(summary_dto)
                has_changes = any((lesson.is_exchange or lesson.is_cancelled) for lesson in summary_dto.lessons if not lesson.is_extra)
                keyboard = None

                if has_changes:
                    changes_data = callbacks.DayChangesCD(
                        target_kind="teacher", target_id=teacher_id, class_id="ALL", group_id="ALL",
                        date_iso=today_iso, origin="teacher", return_to="morning",
                    )
                    keyboard = Keyboards.get_day_changes_kb(changes_data)

                candidates.append(
                    NotificationSendDTO(
                        notification_type="teacher_morning",
                        notification_date=today_iso,
                        source_id=f"teacher_morning:{teacher_id}",
                        recipient_id=recipient_id,
                        text=text,
                        reply_markup=keyboard,
                        context=f"teacher_id={teacher_id}"
                    )
                )

            except Exception:
                logger.exception("Teacher morning summary failed: task=%r", task)

        return candidates, len(tasks)

    async def collect_upcoming_changes(self) -> tuple[list[NotificationSendDTO], int, int, int]:
        now = self.time_service.get_now_base()
        today = now.date()
        today_iso = today.isoformat()
        window_end_iso = (today + datetime.timedelta(days=MAX_CHANGES_WINDOW_DAYS)).isoformat()

        changes = await self.repo.get_pending_changes(start_date_iso=today_iso, end_date_iso=window_end_iso)
        
        recipients_cache: dict[tuple[str, str], list[ScheduleChangeRecipientDTO]] = {}
        teacher_cache: dict[str, list[TeacherChangeRecipientDTO]] = {}
        display_numbers_cache: dict[tuple[str, str], dict[int, str]] = {}
        candidates: list[NotificationSendDTO] = []

        for change in changes:
            try:
                change_date = self.time_service.date_from_iso(change.date)
                class_display_num = str(change.lesson_num)

                try:
                    display_key = (change.class_id, change.date)
                    if display_key not in display_numbers_cache:
                        display_numbers_cache[display_key] = await self.schedule_service.get_display_numbers_for_class_day(
                            class_id=change.class_id, date_iso=change.date
                        )
                    class_display_num = display_numbers_cache[display_key].get(change.lesson_num, str(change.lesson_num))
                except Exception:
                    logger.exception("Failed to calculate display number: class_id=%s date=%s", change.class_id, change.date)

                cache_key = (change.class_id, change.group_id)
                if cache_key not in recipients_cache:
                    recipients_cache[cache_key] = await self.repo.get_recipients_for_schedule_change(
                        class_id=change.class_id, group_id=change.group_id
                    )

                for recipient in recipients_cache[cache_key]:
                    window_days = recipient.changes_window_days
                    if window_days <= 0:
                        continue
                    if not (today <= change_date <= (today + datetime.timedelta(days=window_days))):
                        continue

                    dto = NotificationMapper.to_change_reminder_dto(
                        change,
                        display_num=class_display_num,
                        child_name=(recipient.child_name if recipient.recipient_kind == "adult" else None),
                        watch_target_title=(recipient.watch_target_title if recipient.recipient_kind == "watch" else None),
                    )
                    candidates.append(
                        NotificationSendDTO(
                            notification_type="schedule_change",
                            notification_date=change.date,
                            source_id=change.id,
                            recipient_id=recipient.recipient_id,
                            text=UIRenderer.render_change_reminder(dto),
                            context=f"change_id={change.id}, kind={recipient.recipient_kind}",
                        )
                    )

                teacher_id = change.teacher_id
                if not teacher_id:
                    continue

                if teacher_id not in teacher_cache:
                    teacher_cache[teacher_id] = await self.repo.get_teacher_recipients_for_schedule_change(teacher_id=teacher_id)

                for recipient in teacher_cache[teacher_id]:
                    try:
                        window_days = recipient.changes_window_days
                        if window_days <= 0:
                            continue
                        if not (today <= change_date <= (today + datetime.timedelta(days=window_days))):
                            continue

                        dto = NotificationMapper.to_change_reminder_dto(change, display_num=str(change.lesson_num))
                        teacher_name = change.teacher_name or "Учитель"
                        text = (
                            "👨‍🏫 <b>Изменение в расписании учителя</b>\n"
                            f"👤 <b>{UIRenderer.escape_html(teacher_name)}</b>\n\n"
                            f"{UIRenderer.render_change_reminder(dto)}"
                        )

                        candidates.append(
                            NotificationSendDTO(
                                notification_type="teacher_change",
                                notification_date=change.date,
                                source_id=change.id,
                                recipient_id=recipient.recipient_id,
                                text=text,
                                context=f"teacher_id={teacher_id}, change_id={change.id}",
                            )
                        )
                    except Exception:
                        logger.exception("Teacher schedule change collect failed: change=%r", change)

            except Exception:
                logger.exception("Unexpected schedule change collect error: change=%r", change)

        return candidates, len(changes), len(recipients_cache), len(teacher_cache)

    async def collect_pre_lesson_reminders(self) -> tuple[list[NotificationSendDTO], int, int, int]:
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()

        lessons = await self.repo.get_todays_lessons_for_pre_reminders(date_iso=today_iso)

        recipients_cache: dict[tuple[str, str], list[PreLessonRecipientDTO]] = {}
        teacher_cache: dict[str, list[TeacherPreLessonRecipientDTO]] = {}
        candidates: list[NotificationSendDTO] = []

        for lesson in lessons:
            try:
                lesson_start_at = datetime.datetime.strptime(f"{today_iso} {lesson.start_time}", "%Y-%m-%d %H:%M").replace(tzinfo=self.time_service.base_tz)
                delta_minutes = (lesson_start_at - now).total_seconds() / 60.0

                if delta_minutes <= 0:
                    continue

                cache_key = (lesson.class_id, lesson.group_id or "ALL")
                if cache_key not in recipients_cache:
                    recipients_cache[cache_key] = await self.repo.get_recipients_for_pre_lesson_reminder(
                        class_id=lesson.class_id, group_id=lesson.group_id or "ALL"
                    )

                for recipient in recipients_cache[cache_key]:
                    offset_minutes = recipient.offset_minutes
                    if offset_minutes <= 0 or delta_minutes > offset_minutes:
                        continue

                    dto = LessonReminderDTO(
                        subject_name=lesson.subject_name or "—",
                        start_time=lesson.start_time or "—",
                        room_name=lesson.room_name or "—",
                        is_extra=False,
                        child_name=(recipient.child_name if recipient.recipient_kind == "adult" else None),
                    )

                    candidates.append(
                        NotificationSendDTO(
                            notification_type="pre_lesson",
                            notification_date=today_iso,
                            source_id=lesson.id,
                            recipient_id=recipient.recipient_id,
                            text=UIRenderer.render_lesson_reminder(dto),
                            context=f"lesson_id={lesson.id}, kind={recipient.recipient_kind}",
                        )
                    )

                teacher_id = lesson.teacher_id
                if not teacher_id:
                    continue

                if teacher_id not in teacher_cache:
                    teacher_cache[teacher_id] = await self.repo.get_teacher_recipients_for_pre_lesson_reminder(teacher_id=teacher_id)

                for recipient in teacher_cache[teacher_id]:
                    try:
                        offset_minutes = recipient.offset_minutes
                        if offset_minutes <= 0 or delta_minutes > offset_minutes:
                            continue

                        dto = LessonReminderDTO(
                            subject_name=lesson.subject_name or "—",
                            start_time=lesson.start_time or "—",
                            room_name=lesson.room_name or "—",
                            is_extra=False,
                            child_name=None,
                        )
                        text = (
                            "👨‍🏫 <b>Напоминание об уроке</b>\n\n"
                            f"{UIRenderer.render_lesson_reminder(dto)}"
                        )

                        candidates.append(
                            NotificationSendDTO(
                                notification_type="teacher_pre_lesson",
                                notification_date=today_iso,
                                source_id=lesson.id,
                                recipient_id=recipient.recipient_id,
                                text=text,
                                context=f"teacher_id={teacher_id}, lesson_id={lesson.id}",
                            )
                        )
                    except Exception:
                        logger.exception("Teacher pre-lesson collect failed: lesson=%r", lesson)

            except Exception:
                logger.exception("Unexpected pre-lesson reminder collect error: lesson=%r", lesson)

        return candidates, len(lessons), len(recipients_cache), len(teacher_cache)

    async def collect_extra_class_reminders(self) -> list[NotificationSendDTO]:
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()
        weekday = now.isoweekday()

        extras = await self.repo.get_todays_extra_classes_for_reminders(day_of_week=weekday)
        candidates: list[NotificationSendDTO] = []

        for extra in extras:
            try:
                offset_minutes = extra.offset_minutes
                if offset_minutes <= 0:
                    continue

                start_at = datetime.datetime.strptime(f"{today_iso} {extra.time_start}", "%Y-%m-%d %H:%M").replace(tzinfo=self.time_service.base_tz)
                delta_minutes = (start_at - now).total_seconds() / 60.0

                if delta_minutes <= 0 or delta_minutes > offset_minutes:
                    continue

                dto = LessonReminderDTO(
                    subject_name=extra.title,
                    start_time=extra.time_start,
                    room_name=extra.location or "—",
                    is_extra=True,
                    child_name=(extra.child_name if extra.recipient_kind == "adult" else None),
                )

                candidates.append(
                    NotificationSendDTO(
                        notification_type="extra_class",
                        notification_date=today_iso,
                        source_id=str(extra.extra_id),
                        recipient_id=extra.recipient_id,
                        text=UIRenderer.render_lesson_reminder(dto),
                        context=f"extra_id={extra.extra_id}, kind={extra.recipient_kind}",
                    )
                )

            except Exception:
                logger.exception("Unexpected extra reminder collect error: task=%r", extra)

        return candidates