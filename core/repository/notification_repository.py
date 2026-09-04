# core/repository/notification_repository.py
from __future__ import annotations

from typing import List, Dict, Any

from core.repository.base_repository import BaseRepository


class NotificationRepository(BaseRepository):
    """
    Репозиторий для работы с уведомлениями.

    Отвечает только за выборку уроков/пользователей и обновление флагов:
    - schedule_cache.is_notified
    - schedule_cache.is_change_notified
    """

    # ---------- Предурочные уведомления ----------

    async def get_todays_lessons_for_pre_reminders(self, date_iso: str) -> List[Dict[str, Any]]:
        """
        Уроки на сегодня, по которым ещё не отправлены предурочные уведомления.
        """
        return await self._fetch_all(
            """
            SELECT id, class_id, group_id, start_time, subject_name, room_name
            FROM schedule_cache
            WHERE date = ?
              AND is_cancelled = 0
              AND is_notified = 0
            """,
            (date_iso,),
        )

    async def get_users_for_pre_reminder(self, class_id: str, group_id: str) -> List[Dict[str, Any]]:
        """
        Пользователи класса/группы с включёнными уведомлениями.

        Фильтр по:
        - class_id
        - group_id = EXACT OR ALL OR lesson.ALL
        - is_notifications_enabled = 1
        """
        return await self._fetch_all(
            """
            SELECT user_id, pre_lesson_offset_minutes
            FROM users
            WHERE class_id = ?
              AND (group_id = ? OR group_id = 'ALL' OR ? = 'ALL')
              AND is_notifications_enabled = 1
            """,
            (class_id, group_id, group_id),
        )

    async def mark_lesson_notified(self, lesson_id: str) -> None:
        """
        Помечает урок как уведомлённый (is_notified = 1).
        """
        await self._execute(
            "UPDATE schedule_cache SET is_notified = 1 WHERE id = ?",
            (lesson_id,),
        )

    # ---------- Уведомления об изменениях ----------

    async def get_pending_changes(self) -> List[Dict[str, Any]]:
        """
        Уроки с заменами/отменами, по которым ещё не было уведомлений.
        """
        return await self._fetch_all(
            """
            SELECT id, date, class_id, group_id, lesson_num, subject_name, is_cancelled
            FROM schedule_cache
            WHERE (is_exchange = 1 OR is_cancelled = 1)
              AND is_change_notified = 0
            """,
        )

    async def get_users_for_change_notification(self, class_id: str, group_id: str) -> List[Dict[str, Any]]:
        """
        Пользователи класса/группы с включёнными уведомлениями по изменениям.
        """
        return await self._fetch_all(
            """
            SELECT user_id, changes_window_days
            FROM users
            WHERE class_id = ?
              AND (group_id = ? OR group_id = 'ALL' OR ? = 'ALL')
              AND is_notifications_enabled = 1
            """,
            (class_id, group_id, group_id),
        )

    async def mark_change_notified(self, lesson_id: str) -> None:
        """
        Помечает изменение расписания как уведомлённое.
        """
        await self._execute(
            "UPDATE schedule_cache SET is_change_notified = 1 WHERE id = ?",
            (lesson_id,),
        )
        
    # ---------- Утренняя сводка ----------
    async def get_users_for_morning_summary(self, time_str: str) -> List[Dict[str, Any]]:
        """Выбирает пользователей, у которых время сводки совпадает с текущим."""
        return await self._fetch_all(
            """
            SELECT user_id, class_id, group_id 
            FROM users 
            WHERE is_notifications_enabled = 1 
              AND morning_summary_time = ?
            """,
            (time_str,)
        )

    # ---------- Дополнительные занятия ----------
    async def get_todays_extra_classes_for_reminders(self, day_of_week: int) -> List[Dict[str, Any]]:
        """
        Выбирает доп. занятия на сегодня для пользователей с включенными уведомлениями.
        Учитывает индивидуальные и глобальные настройки напоминаний[cite: 3, 7].
        """
        return await self._fetch_all(
            """
            SELECT e.id, e.user_id, e.time_start, e.title, e.location, 
                   e.reminder_minutes, u.global_extra_reminder
            FROM extra_classes e
            JOIN users u ON e.user_id = u.user_id
            WHERE e.day_of_week = ? 
              AND u.is_notifications_enabled = 1
            """,
            (day_of_week,)
        )