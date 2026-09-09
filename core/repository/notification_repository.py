# core/repository/notification_repository.py
#
# РЕШЁННЫЕ ПРОБЛЕМЫ:
#
# 1. RAM-бомба (Задача 1.4): get_pending_changes с жёстким фильтром
#    по дате на уровне СУБД + частичный индекс idx_schedule_pending_changes.
#
# 2. Strict Time Governance (Задача 1.3): record_notification_delivery
#    пишет sent_at из TimeService.
#
# 3. НОВОЕ (Этап 2, фикс N+1): get_delivered_keys — батчевая проверка
#    доставки. Раньше сервис стрелял одиночным SELECT 1 ... на каждого
#    получателя каждого урока (при 100+ пользователях — тысячи мелких
#    запросов за один тик APScheduler). Теперь один запрос на чанк
#    кандидатов: WHERE type=? AND date IN (...) AND source IN (...)
#    AND recipient IN (...), точное членство кортежа проверяется в Python.
#    Одиночный is_notification_delivered сохранён для редких вызовов.
#
# 4. НОВОЕ: disable_notifications_for_user — вызывается сервисом при
#    TelegramForbiddenError (пользователь заблокировал бота), чтобы
#    не продолжать бессмысленные попытки отправки каждый тик.

from __future__ import annotations

from typing import List, Dict, Any, Optional, Sequence, Set, Tuple

from core.repository.base_repository import BaseRepository

# Ключ доставки: (notification_date, source_id, recipient_id).
DeliveryKey = Tuple[str, str, int]


class NotificationRepository(BaseRepository):
    """
    Репозиторий</arg_key>ленных данных для NotificationService.

    - Читает schedule_cache (уроки, замены, отмены).
    - Пишет/читает notification_delivery_log (дедупликация доставок).
    """

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

    async def get_pending_changes(
        self,
        *,
        start_date_iso: str,
        end_date_iso: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Замены/отмены для рассылки изменений.

        Задача 1.4 (RAM-бомба): жесткий фильтp по дате на уровне СУБД.
        - start_date_iso: обычно today (изменения в прошлом не рассылаем);
        - end_date_iso: верхняя граница окна</arg_key>лений
          (today + max(changes_window_days) = today + 31).
        """
        if end_date_iso is None:
            query = """
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
            WHERE (is_exchange = 1 OR is_cancelled = 1)
              AND date >= ?
            ORDER BY date, lesson_num, id
            """
            return await self._fetch_all(
                query,
                (start_date_iso,),
            )

        query = """
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
        WHERE (is_exchange = 1 OR is_cancelled = 1)
          AND date >= ?
          AND date <= ?
        ORDER BY date, lesson_num, id
        """
        return await self._fetch_all(
            query,
            (
                start_date_iso,
                end_date_iso,
            ),
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
        Проверяет, доставлено ли уведомление (одиночная проверка).

        Оставлена для редких call-site (единичные проверки).
        В горячих циклах сервис использует get_delivered_keys.
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

    # ==============================================================
    # НОВОЕ (Этап 2): батчевая проверка доставки — фикс N+1.
    # ==============================================================

    async def get_delivered_keys(
        self,
        *,
        notification_type: str,
        candidate_keys: Sequence[DeliveryKey],
        chunk_size: int = 400,
    ) -> Set[DeliveryKey]:
        """
        Батчевая проверка доставки списка кандидатов одним-несколькими
        запросами вместо одиночного SELECT на каждого получателя.

        candidate_keys: кортежи (notification_date, source_id, recipient_id).

        Как решается N+1:
        - кандидаты дедуплицируются и режутся на чанки (по умолчанию 400);
        - для чанка выполняется ОДИН запрос с тремя IN-списками
          (dates, sources, recipients). PK-индекс
          (notification_type, notification_date, source_id, recipient_id)
          используется по префиксу;
        - IN-списки дают возможный переселект (cross product), поэтому
          каждый вернувшийся кортеж проверяется на точное членство
          в множестве кандидатов — ложных срабатываний нет;
        - чанкинг делает метод независимым от SQLITE_MAX_VARIABLE_NUMBER
          (999 в старых SQLite, 32766 в новых: 3.45+/3.53+ поддерживают
          с запасом, но консервативный чанк работает везде).

        Возвращает set кортежей, которые УЖЕ доставлены.
        """
        if not candidate_keys:
            return set()

        unique_keys: Set[DeliveryKey] = set(candidate_keys)
        delivered: Set[DeliveryKey] = set()

        keys_list = list(unique_keys)

        for offset in range(0, len(keys_list), chunk_size):
            chunk = keys_list[offset:offset + chunk_size]

            dates = sorted({key[0] for key in chunk})
            sources = sorted({key[1] for key in chunk})
            recipients = sorted({key[2] for key in chunk})

            def _placeholders(values: list) -> str:
                return ",".join("?" for _ in values)

            query = f"""
            SELECT
                notification_date,
                source_id,
                recipient_id
            FROM notification_delivery_log
            WHERE notification_type = ?
              AND notification_date IN ({_placeholders(dates)})
              AND source_id IN ({_placeholders(sources)})
              AND recipient_id IN ({_placeholders(recipients)})
            """
            params = (
                notification_type,
                *dates,
                *sources,
                *recipients,
            )

            rows = await self._fetch_all(
                query,
                params,
            )
            for row in rows:
                key: DeliveryKey = (
                    row["notification_date"],
                    row["source_id"],
                    int(row["recipient_id"]),
                )
                if key in unique_keys:
                    delivered.add(key)

        return delivered

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

        Запись выполняется ПОСЛЕ КАЖДОЙ успешной отправки, а не батчем
        в конце тика: если процесс упадёт в середине рассылки,
        уже отправленные сообщения не продублируются на следующем тике.
        """
        now_utc = self._now_utc_str()
        changed = await self._execute(
            """
            INSERT OR IGNORE INTO notification_delivery_log (
                notification_type,
                notification_date,
                source_id,
                recipient_id,
                sent_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                notification_type,
                notification_date,
                source_id,
                recipient_id,
                now_utc,
            ),
        )
        return changed == 1

    async def disable_notifications_for_user(
        self,
        *,
        user_id: int,
    ) -> bool:
        """
        Отключает уведомленияя пользователю.

        Вызывается при TelegramForbiddenError (бот заблокирован):
        нет смысла продолжать попытки отправки каждый тик.
        Пользователь сможет снова включить уведомления в настройках,
        если разблокирует бота.
        """
        changed = await self._execute(
            """
            UPDATE users
            SET is_notifications_enabled = 0,
                updated_at = ?
            WHERE user_id = ?
              AND is_notifications_enabled = 1
            """,
            (
                self._now_utc_str(),
                user_id,
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

    # ==============================================================
    # Teacher-методы
    # ==============================================================

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
