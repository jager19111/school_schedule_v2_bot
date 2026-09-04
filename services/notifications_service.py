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
        """Интервальный запуск: каждую 1 минуту. Проверяет точное совпадение времени."""
        now = self.time_service.get_now_base()
        current_time_str = now.strftime("%H:%M")
        today_iso = now.date().isoformat()
        weekday = now.isoweekday()

        users = await self.repo.get_users_for_morning_summary(current_time_str)
        if not users:
            return

        for user in users:
            lessons_dtos = []
            
            # Базовые уроки
            if user['class_id']:
                raw_lessons = await self.schedule_repo.get_lessons_for_class(
                    class_id=user['class_id'], 
                    date_iso=today_iso
                )
                for l in raw_lessons:
                    if l['group_id'] == 'ALL' or l['group_id'] == user['group_id']:
                        lessons_dtos.append(MorningLessonDTO(
                            lesson_num=l['lesson_num'],
                            start_time=l['start_time'],
                            end_time=l['end_time'],
                            subject_name=l['subject_name'] or "—",
                            room_name=l['room_name'] or "—",
                            is_cancelled=bool(l['is_cancelled']),
                            is_exchange=bool(l['is_exchange'])
                        ))

            # Доп занятия (Строгие именованные аргументы для защиты от * в репозитории)
            raw_extras = await self.extra_classes_repo.get_extra_classes_for_user(
                user_id=user['user_id'], 
                day_of_week=weekday
            )
            for ex in raw_extras:
                lessons_dtos.append(MorningLessonDTO(
                    lesson_num=None,
                    start_time=ex['time_start'],
                    end_time=ex['time_end'],
                    subject_name=ex['title'],
                    room_name=ex['location'] or "—",
                    is_cancelled=False,
                    is_exchange=False,
                    is_extra=True
                ))

            if not lessons_dtos:
                continue

            # Сортировка по времени начала
            lessons_dtos.sort(key=lambda x: (x.start_time, x.lesson_num or 99))
            
            summary_dto = MorningSummaryDTO(date_iso=today_iso, lessons=lessons_dtos)
            text = UIRenderer.render_morning_summary(summary_dto)
            
            await self._safe_send(user_id=user['user_id'], text=text)


    # ---------- 2. Уведомления об изменениях ----------
    async def send_upcoming_changes(self) -> None:
        """Отправка уведомлений об изменениях при их появлении в БД."""
        now = self.time_service.get_now_base()
        today = now.date()
        changes = await self.repo.get_pending_changes()

        for change in changes:
            change_date = self.time_service.date_from_iso(change["date"])
            users = await self.repo.get_users_for_change_notification(
                class_id=change["class_id"], 
                group_id=change["group_id"]
            )
            
            notified_any = False
            for user in users:
                max_date = today + datetime.timedelta(days=user["changes_window_days"])
                if not (today <= change_date <= max_date):
                    continue

                dto = ChangeReminderDTO(
                    date=change['date'],
                    lesson_num=change['lesson_num'],
                    subject_name=change['subject_name'],
                    is_cancelled=bool(change['is_cancelled'])
                )
                text = UIRenderer.render_change_reminder(dto)
                
                if await self._safe_send(user_id=user['user_id'], text=text):
                    notified_any = True

            if notified_any:
                await self.repo.mark_change_notified(lesson_id=change["id"])


    # ---------- 3. Предурочные уведомления ----------
    async def send_pre_lesson_reminders(self) -> None:
        """Интервальный запуск: каждые 5 минут."""
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()
        lessons = await self.repo.get_todays_lessons_for_pre_reminders(today_iso)

        for lesson in lessons:
            lesson_dt = datetime.datetime.strptime(
                f"{today_iso} {lesson['start_time']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=self.time_service.base_tz)
            delta_minutes = (lesson_dt - now).total_seconds() / 60.0
            
            if delta_minutes <= 0:
                continue

            users = await self.repo.get_users_for_pre_reminder(
                class_id=lesson["class_id"], 
                group_id=lesson["group_id"]
            )
            notified_any = False

            for user in users:
                if 0 < delta_minutes <= user["pre_lesson_offset_minutes"]:
                    dto = LessonReminderDTO(
                        subject_name=lesson['subject_name'],
                        start_time=lesson['start_time'],
                        room_name=lesson['room_name']
                    )
                    text = UIRenderer.render_lesson_reminder(dto)
                    
                    if await self._safe_send(user_id=user['user_id'], text=text):
                        notified_any = True

            if notified_any:
                await self.repo.mark_lesson_notified(lesson_id=lesson["id"])


    # ---------- 4. Уведомления о доп. занятиях ----------
    async def send_extra_class_reminders(self) -> None:
        """Интервальный запуск: каждые 5 минут."""
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()
        weekday = now.isoweekday()
        
        extras = await self.repo.get_todays_extra_classes_for_reminders(weekday)
        
        for ex in extras:
            ex_dt = datetime.datetime.strptime(
                f"{today_iso} {ex['time_start']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=self.time_service.base_tz)
            delta_minutes = (ex_dt - now).total_seconds() / 60.0
            
            if delta_minutes <= 0:
                continue

            reminder_time = ex['reminder_minutes'] if ex['reminder_minutes'] is not None else ex['global_extra_reminder']
            
            if 0 < delta_minutes <= reminder_time:
                dto = LessonReminderDTO(
                    subject_name=ex['title'],
                    start_time=ex['time_start'],
                    room_name=ex['location'] or "—",
                    is_extra=True
                )
                text = UIRenderer.render_lesson_reminder(dto)
                
                # Защита от дублей уведомлений
                if reminder_time - 5 < delta_minutes <= reminder_time:
                    await self._safe_send(user_id=ex['user_id'], text=text)