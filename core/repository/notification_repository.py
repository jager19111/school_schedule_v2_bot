# core/repository/notification_repository.py
from __future__ import annotations

from typing import List, Dict, Any

from core.repository.base_repository import BaseRepository


class NotificationRepository(BaseRepository):
    """
    Репозиторий для работы с уведомлениями.
    schedule_cache хранит факты расписания.
    notification_delivery_log хранит факт доставки конкретному получателю.

    """

    # ---------- Предурочные уведомления ----------

    async def get_todays_lessons_for_pre_reminders(
        self,
        date_iso: str,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает все активные уроки текущего дня.

        Дедупликация выполняется не через schedule_cache.is_notified, а через
        notification_delivery_log отдельно для каждого получателя.
        """
        return await self._fetch_all(
            """
            SELECT
                id,
                date,
                class_id,
                group_id,
                teacher_id,
                start_time,
                subject_name,
                room_name
            FROM schedule_cache
            WHERE date = ?
              AND is_cancelled = 0
            ORDER BY start_time, lesson_num, id
            """,
            (date_iso,),
        )

    async def get_recipients_for_pre_lesson_reminder(
        self,
        class_id: str,
        group_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает получателей напоминания перед школьным уроком.

        student:
        - Telegram-ученик получает напоминание только для собственного
        student profile.

        adult:
        - parent/observer получает напоминание только при активной
        подписке parent_student_settings.receive_pre_lesson_reminders.

        Virtual student:
        - сам сообщения не получает;
        - его родитель/observer получает сообщения при наличии подписки.
        """
        query = """
        SELECT
            student.id AS student_id,
            child.user_id AS recipient_id,
            child.pre_lesson_offset_minutes AS offset_minutes,
            'student' AS recipient_kind,
            NULL AS child_name

        FROM student_profiles AS student
        JOIN users AS child
            ON child.user_id = student.telegram_user_id

        WHERE student.class_id = ?
        AND (
            student.group_id = ?
            OR student.group_id = 'ALL'
            OR ? = 'ALL'
        )
        AND student.is_active = 1
        AND child.role = 'child'
        AND child.is_notifications_enabled = 1

        UNION ALL

        SELECT
            student.id AS student_id,
            adult.user_id AS recipient_id,
            adult.pre_lesson_offset_minutes AS offset_minutes,
            'adult' AS recipient_kind,
            COALESCE(
                NULLIF(TRIM(student.name), ''),
                'Ученик'
            ) AS child_name

        FROM student_profiles AS student
        JOIN parent_student_settings AS settings
            ON settings.student_id = student.id
        AND settings.receive_pre_lesson_reminders = 1
        JOIN users AS adult
            ON adult.user_id = settings.parent_user_id

        WHERE student.class_id = ?
        AND (
            student.group_id = ?
            OR student.group_id = 'ALL'
            OR ? = 'ALL'
        )
        AND student.is_active = 1
        AND adult.role IN ('parent', 'observer')
        AND adult.is_notifications_enabled = 1

        ORDER BY
            recipient_id,
            student_id
        """

        return await self._fetch_all(
            query,
            (
                class_id,
                group_id,
                group_id,

                class_id,
                group_id,
                group_id,
            ),
        )
    # ---------- Уведомления об изменениях ----------
# Требует рефакторинга: сейчас используется только notification_delivery_log, а не is_change_notified
    async def get_pending_changes(self) -> List[Dict[str, Any]]:
        """
        Возвращает все отмены и замены из schedule_cache.

        Дедупликация выполняется по notification_delivery_log отдельно
        для каждого получателя, а не глобально через is_change_notified.
        """
        return await self._fetch_all(
            """
            SELECT
                id,
                date,
                class_id,
                group_id,
                teacher_id,
                lesson_num,
                subject_name,
                is_cancelled
            FROM schedule_cache
            WHERE is_exchange = 1
               OR is_cancelled = 1
            ORDER BY date, lesson_num, id
            """
        )

    async def get_recipients_for_schedule_change(
        self,
        class_id: str,
        group_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает получателей уведомления о замене/отмене урока.

        Включает:
        - Telegram-учеников;
        - взрослых, подписанных на конкретный student profile;
        - владельцев самостоятельных watch targets.
        """
        query = """
        SELECT
            student.id AS student_id,
            child.user_id AS recipient_id,
            child.changes_window_days AS changes_window_days,
            'student' AS recipient_kind,
            NULL AS child_name,
            NULL AS watch_target_title

        FROM student_profiles AS student
        JOIN users AS child
            ON child.user_id = student.telegram_user_id

        WHERE student.class_id = ?
        AND (
            student.group_id = ?
            OR student.group_id = 'ALL'
            OR ? = 'ALL'
        )
        AND student.is_active = 1
        AND child.role = 'child'
        AND child.is_notifications_enabled = 1
        AND child.receive_schedule_changes = 1

        UNION ALL

        SELECT
            student.id AS student_id,
            adult.user_id AS recipient_id,
            adult.changes_window_days AS changes_window_days,
            'adult' AS recipient_kind,
            COALESCE(
                NULLIF(TRIM(student.name), ''),
                'Ученик'
            ) AS child_name,
            NULL AS watch_target_title

        FROM student_profiles AS student
        JOIN parent_student_settings AS settings
            ON settings.student_id = student.id
        AND settings.receive_schedule_changes = 1
        JOIN users AS adult
            ON adult.user_id = settings.parent_user_id

        WHERE student.class_id = ?
        AND (
            student.group_id = ?
            OR student.group_id = 'ALL'
            OR ? = 'ALL'
        )
        AND student.is_active = 1
        AND adult.role IN ('parent', 'observer')
        AND adult.is_notifications_enabled = 1
        AND adult.receive_schedule_changes = 1

        UNION ALL

        SELECT
            NULL AS student_id,
            owner.user_id AS recipient_id,
            owner.changes_window_days AS changes_window_days,
            'watch' AS recipient_kind,
            NULL AS child_name,
            COALESCE(
                NULLIF(TRIM(watch.title), ''),
                watch.class_id
            ) AS watch_target_title

        FROM schedule_watch_targets AS watch
        JOIN users AS owner
            ON owner.user_id = watch.owner_user_id

        WHERE watch.class_id = ?
        AND (
            watch.group_id = ?
            OR watch.group_id = 'ALL'
            OR ? = 'ALL'
        )
        AND watch.is_enabled = 1
        AND watch.receive_schedule_changes = 1
        AND owner.is_notifications_enabled = 1
        AND owner.receive_schedule_changes = 1

        ORDER BY
            recipient_id,
            student_id
        """

        return await self._fetch_all(
            query,
            (
                class_id,
                group_id,
                group_id,

                class_id,
                group_id,
                group_id,

                class_id,
                group_id,
                group_id,
            ),
        )
            
    # ---------- Утренняя сводка ----------
    async def get_morning_summary_tasks(
        self,
        time_str: str,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает задачи утренних сводок.

        target_student_id — это всегда student_profiles.id.

        Virtual student не получает сообщение сам, но может попасть
        в сводку родителя или observer.
        """
        query = """
        SELECT
            child.user_id AS recipient_id,
            student.id AS target_student_id,
            'student' AS recipient_kind,
            NULL AS child_name,
            student.class_id,
            student.group_id

        FROM student_profiles AS student
        JOIN users AS child
            ON child.user_id = student.telegram_user_id

        WHERE student.is_active = 1
        AND child.role = 'child'
        AND child.is_notifications_enabled = 1
        AND child.morning_summary_time = ?

        UNION ALL

        SELECT
            adult.user_id AS recipient_id,
            student.id AS target_student_id,
            'adult' AS recipient_kind,
            COALESCE(
                NULLIF(TRIM(student.name), ''),
                'Ученик'
            ) AS child_name,
            student.class_id,
            student.group_id

        FROM parent_student_settings AS settings
        JOIN student_profiles AS student
            ON student.id = settings.student_id
        JOIN users AS adult
            ON adult.user_id = settings.parent_user_id

        WHERE student.is_active = 1
        AND settings.receive_morning_summary = 1
        AND adult.role IN ('parent', 'observer')
        AND adult.is_notifications_enabled = 1
        AND adult.morning_summary_time = ?

        ORDER BY
            recipient_id,
            target_student_id
        """

        return await self._fetch_all(
            query,
            (time_str, time_str),
        )

    # ---------- Дополнительные занятия ----------
    async def get_todays_extra_classes_for_reminders(
        self,
        day_of_week: int,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает адресные задачи напоминаний о дополнительных занятиях.

        Telegram child получает только занятия своего student profile.
        Parent/observer получает занятия student profiles, на которые
        подписан через parent_student_settings.
        """
        query = """
        SELECT
            extra.id AS extra_id,
            student.id AS student_id,
            extra.time_start,
            extra.title,
            extra.location,

            child.user_id AS recipient_id,

            CAST(
                COALESCE(
                    extra.reminder_minutes,
                    child.global_extra_reminder
                )
                AS INTEGER
            ) AS offset_minutes,

            'student' AS recipient_kind,
            NULL AS child_name

        FROM extra_classes AS extra
        JOIN student_profiles AS student
            ON student.id = extra.student_id
        JOIN users AS child
            ON child.user_id = student.telegram_user_id

        WHERE extra.day_of_week = ?
        AND student.is_active = 1
        AND child.role = 'child'
        AND child.is_notifications_enabled = 1
        AND child.receive_extra_class_reminders = 1

        UNION ALL

        SELECT
            extra.id AS extra_id,
            student.id AS student_id,
            extra.time_start,
            extra.title,
            extra.location,

            adult.user_id AS recipient_id,

            CAST(
                COALESCE(
                    extra.reminder_minutes,
                    adult.global_extra_reminder
                )
                AS INTEGER
            ) AS offset_minutes,

            'adult' AS recipient_kind,

            COALESCE(
                NULLIF(TRIM(student.name), ''),
                'Ученик'
            ) AS child_name

        FROM extra_classes AS extra
        JOIN student_profiles AS student
            ON student.id = extra.student_id
        JOIN parent_student_settings AS settings
            ON settings.student_id = student.id
        AND settings.receive_extra_class_reminders = 1
        JOIN users AS adult
            ON adult.user_id = settings.parent_user_id

        WHERE extra.day_of_week = ?
        AND student.is_active = 1
        AND adult.role IN ('parent', 'observer')
        AND adult.is_notifications_enabled = 1
        AND adult.receive_extra_class_reminders = 1

        ORDER BY
            recipient_id,
            student_id,
            extra_id
        """

        return await self._fetch_all(
            query,
            (day_of_week, day_of_week),
        )
            
    async def is_notification_delivered(
        self,
        *,
        notification_type: str,
        notification_date: str,
        source_id: str,
        recipient_id: int,
    ) -> bool:
        """
        Проверяет, зарегистрирована ли успешная доставка уведомления.

        Журналируется только успешная отправка. При Telegram-ошибке запись
        не создаётся, поэтому следующая задача сможет повторить попытку.
        """
        row = await self._fetch_one(
            """
            SELECT 1 AS delivered
            FROM notification_delivery_log
            WHERE notification_type = ?
              AND notification_date = ?
              AND source_id = ?
              AND recipient_id = ?
            """,
            (
                notification_type,
                notification_date,
                source_id,
                recipient_id,
            ),
        )
        return row is not None

    async def record_notification_delivery(
        self,
        *,
        notification_type: str,
        notification_date: str,
        source_id: str,
        recipient_id: int,
    ) -> bool:
        """
        Фиксирует успешную доставку.

        Возвращает True, если была создана новая запись.
        INSERT OR IGNORE защищает от дублей при повторном вызове.
        """
        changed = await self._execute(
            """
            INSERT OR IGNORE INTO notification_delivery_log (
                notification_type,
                notification_date,
                source_id,
                recipient_id
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                notification_type,
                notification_date,
                source_id,
                recipient_id,
            ),
        )
        return changed == 1
    
    async def delete_notification_delivery_before(
        self,
        before_date_iso: str,
    ) -> int:
        """
        Удаляет записи успешных доставок до указанной даты.

        notification_date хранится как ISO YYYY-MM-DD, поэтому строковое
        сравнение корректно соответствует хронологическому.
        """
        return await self._execute(
            """
            DELETE FROM notification_delivery_log
            WHERE notification_date < ?
            """,
            (before_date_iso,),
        )
        
    #----------------------
    #   УЧИТЕЛЬ
    #----------------------
    
    async def get_teacher_morning_summary_tasks(
        self,
        *,
        time_str: str,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает teacher accounts, для которых настало время
        личной утренней сводки.
        """
        return await self._fetch_all(
            """
            SELECT
                user_id AS recipient_id,
                teacher_id,
                name AS teacher_name
            FROM users
            WHERE role = 'teacher'
            AND teacher_id IS NOT NULL
            AND TRIM(teacher_id) != ''
            AND is_notifications_enabled = 1
            AND morning_summary_time = ?
            ORDER BY user_id
            """,
            (time_str,),
        )
        
    async def get_teacher_recipients_for_pre_lesson_reminder(
        self,
        *,
        teacher_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает Telegram teachers, привязанных к NIKA teacher_id.

        Teacher получает только собственные уроки.
        """
        return await self._fetch_all(
            """
            SELECT
                user_id AS recipient_id,
                teacher_id,
                pre_lesson_offset_minutes AS offset_minutes
            FROM users
            WHERE role = 'teacher'
            AND teacher_id = ?
            AND is_notifications_enabled = 1
            AND pre_lesson_offset_minutes > 0
            ORDER BY user_id
            """,
            (teacher_id,),
        )
        
    async def get_teacher_recipients_for_schedule_change(
        self,
        *,
        teacher_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает teachers, которым следует отправить уведомление
        о замене или отмене в собственном расписании.
        """
        return await self._fetch_all(
            """
            SELECT
                user_id AS recipient_id,
                teacher_id,
                changes_window_days
            FROM users
            WHERE role = 'teacher'
            AND teacher_id = ?
            AND is_notifications_enabled = 1
            AND receive_schedule_changes = 1
            AND changes_window_days > 0
            ORDER BY user_id
            """,
            (teacher_id,),
        )