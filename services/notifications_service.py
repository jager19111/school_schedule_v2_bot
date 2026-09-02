# services/notifications.py
import logging
import datetime

from aiogram import Bot

from core.repository.notification_repository import NotificationRepository
from services.time_service import TimeService

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Сервис уведомлений.

    - Не содержит SQL.
    - Работает через NotificationRepository + TimeService + Bot.
    """

    def __init__(
        self,
        bot: Bot,
        notification_repo: NotificationRepository,
        time_service: TimeService,
    ):
        self.bot = bot
        self.repo = notification_repo
        self.time_service = time_service

    # ---------- Предурочные уведомления ----------

    async def send_pre_lesson_reminders(self) -> None:
        """
        Предурочные оповещения: каждые 5 минут.

        Логика:
        - Берём сейчас (TimeService.get_now_base).
        - Выбираем уроки на сегодня без is_notified.
        - Для каждого урока считаем дельту до старта.
        - Находим пользователей с классом/группой, для которых 0 < delta <= pre_lesson_offset_minutes.
        - Отправляем сообщения, помечаем урок как is_notified=1, если хоть один пользователь уведомлён.
        """
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()

        lessons = await self.repo.get_todays_lessons_for_pre_reminders(today_iso)
        if not lessons:
            logger.debug("send_pre_lesson_reminders: нет уроков для уведомлений на %s", today_iso)
            return

        for lesson in lessons:
            start_time_str = lesson["start_time"]

            # Собираем aware datetime урока (дата + время) в базовой таймзоне
            lesson_dt = datetime.datetime.strptime(
                f"{today_iso} {start_time_str}",
                "%Y-%m-%d %H:%M",
            ).replace(tzinfo=self.time_service.base_tz)

            delta_minutes = (lesson_dt - now).total_seconds() / 60.0
            if delta_minutes <= 0:
                continue

            users = await self.repo.get_users_for_pre_reminder(
                class_id=lesson["class_id"],
                group_id=lesson["group_id"],
            )

            notified_any = False
            for user in users:
                offset = user["pre_lesson_offset_minutes"]
                if 0 < delta_minutes <= offset:
                    msg = (
                        f"🔔 Урок {lesson['subject_name']} начнется в {start_time_str} "
                        f"(каб. {lesson['room_name']})"
                    )
                    try:
                        await self.bot.send_message(user["user_id"], msg)
                        notified_any = True
                    except Exception as e:
                        logger.error(
                            "Ошибка отправки предурочного уведомления пользователю %s: %s",
                            user["user_id"],
                            e,
                        )

            if notified_any:
                await self.repo.mark_lesson_notified(lesson["id"])

    # ---------- Уведомления об изменениях ----------

    async def send_upcoming_changes(self) -> None:
        """
        Уведомления об изменениях/отменах уроков.

        Логика:
        - Берём сейчас (TimeService.get_now_base).
        - Ищем все изменения (is_exchange=1 или is_cancelled=1) с is_change_notified=0.
        - Для каждого изменения ищем пользователей по классу/группе.
        - Проверяем, попадает ли дата изменения в окно [today, today + changes_window_days].
        - Отправляем сообщение, помечаем is_change_notified=1 при успехе.
        """
        now = self.time_service.get_now_base()
        today = now.date()

        changes = await self.repo.get_pending_changes()
        if not changes:
            logger.debug("send_upcoming_changes: нет изменений для уведомлений")
            return

        for change in changes:
            change_date = datetime.datetime.strptime(change["date"], "%Y-%m-%d").date()

            users = await self.repo.get_users_for_change_notification(
                class_id=change["class_id"],
                group_id=change["group_id"],
            )

            notified_any = False
            for user in users:
                window_days = user["changes_window_days"]
                max_date = today + datetime.timedelta(days=window_days)

                if not (today <= change_date <= max_date):
                    continue

                status = "🚫 ОТМЕНЕН" if change["is_cancelled"] else "🔄 ИЗМЕНЕН"
                msg = (
                    f"❗️ Внимание! {change['date']} урок №{change['lesson_num']} "
                    f"({change['subject_name']}) {status}."
                )
                try:
                    await self.bot.send_message(user["user_id"], msg)
                    notified_any = True
                except Exception as e:
                    logger.error(
                        "Ошибка отправки уведомления об изменении пользователю %s: %s",
                        user["user_id"],
                        e,
                    )

            if notified_any:
                await self.repo.mark_change_notified(change["id"])