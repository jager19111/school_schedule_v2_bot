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
        Формирует адресный fan-out предурочного уведомления.

        Возвращает:
        - самого ребёнка, которому принадлежит расписание;
        - всех взрослых, подписанных на предурочные уведомления этого ребёнка.
        """
        return await self._fetch_all(
            """
            -- Получатель: сам ребёнок.
            SELECT
                child.user_id AS child_id,
                child.user_id AS recipient_id,
                child.pre_lesson_offset_minutes AS offset_minutes,
                'child' AS recipient_kind,
                NULL AS child_name
            FROM users AS child
            WHERE child.class_id = ?
              AND (
                    child.group_id = ?
                    OR child.group_id = 'ALL'
                    OR ? = 'ALL'
                  )
              AND child.role = 'child'
              AND child.is_notifications_enabled = 1

            UNION ALL

            -- Получатель: parent или observer, подписанный на ребёнка.
            SELECT
                child.user_id AS child_id,
                adult.user_id AS recipient_id,
                adult.pre_lesson_offset_minutes AS offset_minutes,
                'adult' AS recipient_kind,
                COALESCE(
                    NULLIF(TRIM(child.name), ''),
                    'Ученик ' || child.user_id
                ) AS child_name
            FROM users AS child
            JOIN parent_child_settings AS pcs
              ON pcs.child_id = child.user_id
             AND pcs.receive_pre_lesson_reminders = 1
            JOIN users AS adult
              ON adult.user_id = pcs.parent_id
            WHERE child.class_id = ?
              AND (
                    child.group_id = ?
                    OR child.group_id = 'ALL'
                    OR ? = 'ALL'
                  )
              AND child.role = 'child'
              AND adult.role IN ('parent', 'observer')
              AND adult.is_notifications_enabled = 1

            ORDER BY recipient_id, child_id
            """,
            (
                class_id,
                group_id,
                group_id,
                class_id,
                group_id,
                group_id,
            ),
        )
# legacy-метод. Удалить после рефакторинга, когда будет использоваться только notification_delivery_log
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
        Формирует адресный fan-out уведомления об изменении расписания.

        Возвращает ребёнка и подписанных на него взрослых.
        changes_window_days принадлежит получателю, а не ребёнку.
        """
        return await self._fetch_all(
            """
            -- Получатель: сам ребёнок.
            SELECT
                child.user_id AS child_id,
                child.user_id AS recipient_id,
                child.changes_window_days AS changes_window_days,
                'child' AS recipient_kind,
                NULL AS child_name
            FROM users AS child
            WHERE child.class_id = ?
              AND (
                    child.group_id = ?
                    OR child.group_id = 'ALL'
                    OR ? = 'ALL'
                  )
              AND child.role = 'child'
              AND child.is_notifications_enabled = 1

            UNION ALL

            -- Получатель: подписанный взрослый.
            SELECT
                child.user_id AS child_id,
                adult.user_id AS recipient_id,
                adult.changes_window_days AS changes_window_days,
                'adult' AS recipient_kind,
                COALESCE(
                    NULLIF(TRIM(child.name), ''),
                    'Ученик ' || child.user_id
                ) AS child_name
            FROM users AS child
            JOIN parent_child_settings AS pcs
              ON pcs.child_id = child.user_id
             AND pcs.receive_schedule_changes = 1
            JOIN users AS adult
              ON adult.user_id = pcs.parent_id
            WHERE child.class_id = ?
              AND (
                    child.group_id = ?
                    OR child.group_id = 'ALL'
                    OR ? = 'ALL'
                  )
              AND child.role = 'child'
              AND adult.role IN ('parent', 'observer')
              AND adult.is_notifications_enabled = 1

            ORDER BY recipient_id, child_id
            """,
            (
                class_id,
                group_id,
                group_id,
                class_id,
                group_id,
                group_id,
            ),
        )
# legacy-метод.Удалить после рефакторинга, когда будет использоваться только notification_delivery_log
    async def mark_change_notified(self, lesson_id: str) -> None:
        """
        Помечает изменение расписания как уведомлённое.
        """
        await self._execute(
            "UPDATE schedule_cache SET is_change_notified = 1 WHERE id = ?",
            (lesson_id,),
        )
        
    # ---------- Утренняя сводка ----------
    async def get_morning_summary_tasks(
        self,
        time_str: str,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает адресные задачи утренней сводки.

        Каждая строка — это одна пара:
            recipient_id -> target_child_id

        Возможные варианты:
        - ребёнок получает сводку о себе;
        - parent/observer получает сводку о выбранном ребёнке.

        Группировка нескольких детей в одно Telegram-сообщение выполняется
        в NotificationService, а не в SQL.
        """
        return await self._fetch_all(
            """
            -- Личная сводка ребёнка.
            SELECT
                child.user_id AS recipient_id,
                child.user_id AS target_child_id,
                'child' AS recipient_kind,
                NULL AS child_name,
                child.class_id,
                child.group_id
            FROM users AS child
            WHERE child.role = 'child'
              AND child.is_notifications_enabled = 1
              AND child.morning_summary_time = ?

            UNION ALL

            -- Сводка взрослому по конкретному ребёнку.
            SELECT
                adult.user_id AS recipient_id,
                child.user_id AS target_child_id,
                'adult' AS recipient_kind,
                COALESCE(
                    NULLIF(TRIM(child.name), ''),
                    'Ученик ' || child.user_id
                ) AS child_name,
                child.class_id,
                child.group_id
            FROM users AS adult
            JOIN parent_child_settings AS pcs
              ON pcs.parent_id = adult.user_id
             AND pcs.receive_morning_summary = 1
            JOIN users AS child
              ON child.user_id = pcs.child_id
            WHERE adult.role IN ('parent', 'observer')
              AND adult.is_notifications_enabled = 1
              AND adult.morning_summary_time = ?
              AND child.role = 'child'

            ORDER BY recipient_id, target_child_id
            """,
            (time_str, time_str),
        )

    # ---------- Дополнительные занятия ----------
    async def get_todays_extra_classes_for_reminders(
        self,
        day_of_week: int,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает адресные задачи напоминаний о допзанятиях.

        Fan-out:
        1. Ребёнок получает только собственное занятие.
        2. Parent/observer получает занятие конкретного ребёнка только при
           receive_extra_class_reminders = 1 в parent_child_settings.

        У одного занятия может быть несколько получателей:
        ребёнок + один или несколько взрослых.
        """
        return await self._fetch_all(
            """
            -- Получатель: сам ребёнок.
            SELECT
                e.id AS extra_id,
                e.user_id AS child_id,
                e.time_start,
                e.title,
                e.location,
                e.reminder_minutes AS offset_minutes,

                child.user_id AS recipient_id,
                'child' AS recipient_kind,
                NULL AS child_name
            FROM extra_classes AS e
            JOIN users AS child
              ON child.user_id = e.user_id
            WHERE e.day_of_week = ?
              AND child.role = 'child'
              AND child.is_notifications_enabled = 1

            UNION ALL

            -- Получатель: взрослый, подписанный на этого ребёнка.
            SELECT
                e.id AS extra_id,
                e.user_id AS child_id,
                e.time_start,
                e.title,
                e.location,
                e.reminder_minutes AS offset_minutes,

                adult.user_id AS recipient_id,
                'adult' AS recipient_kind,
                COALESCE(
                    NULLIF(TRIM(child.name), ''),
                    'Ученик ' || child.user_id
                ) AS child_name
            FROM extra_classes AS e
            JOIN users AS child
              ON child.user_id = e.user_id
            JOIN parent_child_settings AS pcs
              ON pcs.child_id = child.user_id
             AND pcs.receive_extra_class_reminders = 1
            JOIN users AS adult
              ON adult.user_id = pcs.parent_id
            WHERE e.day_of_week = ?
              AND child.role = 'child'
              AND adult.role IN ('parent', 'observer')
              AND adult.is_notifications_enabled = 1

            ORDER BY time_start, recipient_id, child_id
            """,
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