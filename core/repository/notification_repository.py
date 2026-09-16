# core/repository/notification_repository.py

from __future__ import annotations

from typing import List, Any, Sequence, Set, Mapping

from core.repository.base_repository import BaseRepository
from core.models.dto import (
    PendingChangeDTO,
    MorningSummaryTaskDTO,
    TeacherMorningTaskDTO,
    PreLessonRecipientDTO,
    TeacherPreLessonRecipientDTO,
    ScheduleChangeRecipientDTO,
    TeacherChangeRecipientDTO,
    ExtraClassReminderTaskDTO,
    DeliveredKeyDTO,
    PreLessonSourceDTO,
)

from core.mappers.notification_mapper import NotificationMapper

class NotificationRepository(BaseRepository):
    """
    Репозиторий уведомлений.
    Обеспечивает доступ к расписанию и получателям.
    Избавлен от дублирования SQL благодаря внутренним Query Helpers.
    """

    # ==============================================================
    # 1. SQL Query Helpers (Фабрики запросов)
    # ==============================================================

    def _build_family_query(
        self,
        child_select: str,
        adult_select: str,
        child_where: str,
        adult_where: str,
        extra_from: str = "",
    ) -> str:
        """
        Генерирует базовый UNION ALL для Telegram-учеников и подписанных взрослых.
        Устраняет дублирование JOIN'ов и проверок базовых статусов.
        """
        child_cols = f", {child_select}" if child_select.strip() else ""
        adult_cols = f", {adult_select}" if adult_select.strip() else ""

        return f"""
        SELECT
            student.id AS student_id,
            child.user_id AS recipient_id,
            'student' AS recipient_kind,
            NULL AS child_name
            {child_cols}
        FROM student_profiles AS student
        {extra_from}
        JOIN users AS child ON child.user_id = student.telegram_user_id
        WHERE student.is_active = 1
          AND child.role = 'child'
          AND child.is_notifications_enabled = 1
          {child_where}

        UNION ALL

        SELECT
            student.id AS student_id,
            adult.user_id AS recipient_id,
            'adult' AS recipient_kind,
            COALESCE(NULLIF(TRIM(student.name), ''), 'Ученик') AS child_name
            {adult_cols}
        FROM student_profiles AS student
        JOIN parent_student_settings AS settings ON settings.student_id = student.id
        {extra_from}
        JOIN users AS adult ON adult.user_id = settings.parent_user_id
        WHERE student.is_active = 1
          AND adult.role IN ('parent', 'observer')
          AND adult.is_notifications_enabled = 1
          {adult_where}
        """

    async def _get_teacher_configs(
        self, select_fields: str, where_clause: str, params: tuple
    ) -> list[Mapping[str, Any]]:
        """Унифицированный запрос для получателей-учителей."""
        query = f"""
            SELECT
                user_id AS recipient_id,
                teacher_id
                {f', {select_fields}' if select_fields else ''}
            FROM users
            WHERE role = 'teacher'
              AND is_notifications_enabled = 1
              {where_clause}
            ORDER BY user_id
        """
        return await self._fetch_all(query, params)

    # ==============================================================
    # 2. Получение кандидатов (Students & Family)
    # ==============================================================

    async def get_recipients_for_pre_lesson_reminder(self, class_id: str, group_id: str) -> list[PreLessonRecipientDTO]:
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
        class_group_cond = "AND student.class_id = ? AND (student.group_id = ? OR student.group_id = 'ALL' OR ? = 'ALL')"
        
        query = self._build_family_query(
            child_select="child.pre_lesson_offset_minutes AS offset_minutes",
            adult_select="adult.pre_lesson_offset_minutes AS offset_minutes",
            child_where=class_group_cond,
            adult_where=f"AND settings.receive_pre_lesson_reminders = 1 {class_group_cond}",
        ) + " ORDER BY recipient_id, student_id"
        
        params = (class_id, group_id, group_id, class_id, group_id, group_id)
        rows = await self._fetch_all(query, params)
        return [NotificationMapper.to_pre_lesson_recipient_dto(row) for row in rows]

    async def get_recipients_for_schedule_change(self, class_id: str, group_id: str) -> list[ScheduleChangeRecipientDTO]:
        """
        Возвращает получателей уведомления о замене/отмене урока.

        Включает:
        - Telegram-учеников;
        - взрослых, подписанных на конкретный student profile;
        - владельцев самостоятельных watch targets.
        """
        class_group_cond = "AND student.class_id = ? AND (student.group_id = ? OR student.group_id = 'ALL' OR ? = 'ALL')"
        
        base_query = self._build_family_query(
            child_select="child.changes_window_days AS changes_window_days, NULL AS watch_target_title",
            adult_select="adult.changes_window_days AS changes_window_days, NULL AS watch_target_title",
            child_where=f"AND child.receive_schedule_changes = 1 {class_group_cond}",
            adult_where=f"AND settings.receive_schedule_changes = 1 AND adult.receive_schedule_changes = 1 {class_group_cond}",
        )
        
        # Специфичное добавление третьего UNION для Schedule Watch Targets
        watch_query = """
        UNION ALL
        SELECT
            NULL AS student_id,
            owner.user_id AS recipient_id,
            'watch' AS recipient_kind,
            NULL AS child_name,
            owner.changes_window_days AS changes_window_days,
            COALESCE(NULLIF(TRIM(watch.title), ''), watch.class_id) AS watch_target_title
        FROM schedule_watch_targets AS watch
        JOIN users AS owner ON owner.user_id = watch.owner_user_id
        WHERE watch.class_id = ?
          AND (watch.group_id = ? OR watch.group_id = 'ALL' OR ? = 'ALL')
          AND watch.is_enabled = 1
          AND watch.receive_schedule_changes = 1
          AND owner.is_notifications_enabled = 1
          AND owner.receive_schedule_changes = 1
        """
        
        query = f"{base_query} {watch_query} ORDER BY recipient_id, student_id"
        params = (class_id, group_id, group_id, class_id, group_id, group_id, class_id, group_id, group_id)
        
        rows = await self._fetch_all(query, params)
        return [NotificationMapper.to_schedule_change_recipient_dto(row) for row in rows]

    async def get_morning_summary_tasks(self, time_str: str) -> list[MorningSummaryTaskDTO]:
        """
        Возвращает задачи утренних сводок.

        target_student_id — это всегда student_profiles.id.
        Virtual student не получает сообщение сам, но может попасть
        в сводку родителя или observer.
        """
        query = self._build_family_query(
            child_select="student.id AS target_student_id, student.class_id, student.group_id",
            adult_select="student.id AS target_student_id, student.class_id, student.group_id",
            child_where="AND child.morning_summary_time = ?",
            adult_where="AND settings.receive_morning_summary = 1 AND adult.morning_summary_time = ?",
        ) + " ORDER BY recipient_id, target_student_id"
        
        rows = await self._fetch_all(query, (time_str, time_str))
        return [NotificationMapper.to_morning_summary_task_dto(row) for row in rows]

    async def get_todays_extra_classes_for_reminders(self, day_of_week: int) -> list[ExtraClassReminderTaskDTO]:
        """
        Возвращает адресные задачи напоминаний о дополнительных занятиях.

        Telegram child получает только занятия своего student profile.
        Parent/observer получает занятия student profiles, на которые
        подписан через parent_student_settings.
        """
        query = self._build_family_query(
            child_select=(
                "extra.id AS extra_id, extra.time_start, extra.title, extra.location, "
                "CAST(COALESCE(extra.reminder_minutes, child.global_extra_reminder) AS INTEGER) AS offset_minutes"
            ),
            adult_select=(
                "extra.id AS extra_id, extra.time_start, extra.title, extra.location, "
                "CAST(COALESCE(extra.reminder_minutes, adult.global_extra_reminder) AS INTEGER) AS offset_minutes"
            ),
            child_where="AND extra.day_of_week = ? AND child.receive_extra_class_reminders = 1",
            adult_where="AND extra.day_of_week = ? AND settings.receive_extra_class_reminders = 1 AND adult.receive_extra_class_reminders = 1",
            extra_from="JOIN extra_classes AS extra ON extra.student_id = student.id",
        ) + " ORDER BY recipient_id, student_id, extra_id"

        rows = await self._fetch_all(query, (day_of_week, day_of_week))
        return [NotificationMapper.to_extra_class_reminder_task_dto(row) for row in rows]

    # ==============================================================
    # 3. Получение кандидатов (Teachers)
    # ==============================================================

    async def get_teacher_morning_summary_tasks(self, *, time_str: str) -> list[TeacherMorningTaskDTO]:
        """
        Возвращает teacher accounts, для которых настало время
        личной утренней сводки.
        """
        rows = await self._get_teacher_configs(
            select_fields="name AS teacher_name",
            where_clause="AND teacher_id IS NOT NULL AND TRIM(teacher_id) != '' AND morning_summary_time = ?",
            params=(time_str,),
        )
        return [NotificationMapper.to_teacher_morning_task_dto(row) for row in rows]

    async def get_teacher_recipients_for_pre_lesson_reminder(self, *, teacher_id: str) -> list[TeacherPreLessonRecipientDTO]:
        """
        Возвращает Telegram teachers, привязанных к NIKA teacher_id.

        Teacher получает только собственные уроки.
        """
        rows = await self._get_teacher_configs(
            select_fields="pre_lesson_offset_minutes AS offset_minutes",
            where_clause="AND teacher_id = ? AND pre_lesson_offset_minutes > 0",
            params=(teacher_id,),
        )
        return [NotificationMapper.to_teacher_pre_lesson_recipient_dto(row) for row in rows]

    async def get_teacher_recipients_for_schedule_change(self, *, teacher_id: str) -> list[TeacherChangeRecipientDTO]:
        """
        Возвращает teachers, которым следует отправить уведомление
        о замене или отмене в собственном расписании.
        """
        rows = await self._get_teacher_configs(
            select_fields="changes_window_days",
            where_clause="AND teacher_id = ? AND receive_schedule_changes = 1 AND changes_window_days > 0",
            params=(teacher_id,),
        )
        return [NotificationMapper.to_teacher_change_recipient_dto(row) for row in rows]

    # ==============================================================
    # 4. Данные кэша расписания
    # ==============================================================

    async def get_todays_lessons_for_pre_reminders(self, date_iso: str) -> List[PreLessonSourceDTO]:
        """Возвращает все активные уроки текущего дня через строгий DTO."""
        rows = await self._fetch_all(
            """
            SELECT id, date, class_id, group_id, teacher_id, start_time, subject_name, room_name
            FROM schedule_cache
            WHERE date = ? AND is_cancelled = 0 AND is_methodological = 0
            ORDER BY start_time, lesson_num, id
            """,
            (date_iso,),
        )
        return [NotificationMapper.to_pre_lesson_source_dto(row) for row in rows]

    async def get_pending_changes(self, *, start_date_iso: str, end_date_iso: str | None = None) -> list[PendingChangeDTO]:
        query = """
            SELECT
                id, date, period_id, class_id, group_id, group_name, teacher_id, lesson_num,
                subject_id, subject_name, room_id, room_name, teacher_name,
                original_subject_id, original_subject_name, original_room_id, original_room_name,
                original_teacher_id, original_teacher_name, original_group_id, original_group_name,
                original_class_id, original_class_name, is_exchange, is_cancelled, is_methodological
            FROM schedule_cache
            WHERE (is_exchange = 1 OR is_cancelled = 1) AND date >= ?
        """
        params = [start_date_iso]
        if end_date_iso:
            query += " AND date <= ?"
            params.append(end_date_iso)
        
        query += " ORDER BY date, lesson_num, id"
        
        rows = await self._fetch_all(query, tuple(params))
        return [NotificationMapper.to_pending_change_dto(row) for row in rows]

    # ==============================================================
    # 5. Delivery Log и Throttling Controls
    # ==============================================================

    @staticmethod
    def _chunk_list(data: list, chunk_size: int):
        """Разбивает список на чанки заданного размера."""
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]

    @staticmethod
    def _generate_in_placeholders(count: int) -> str:
        """Генерирует строку плейсхолдеров для SQL IN (...)."""
        return ",".join(["?"] * count)

    @staticmethod
    def _filter_cross_product(rows: list[Mapping[str, Any]], valid_keys: Set[DeliveredKeyDTO]) -> Set[DeliveredKeyDTO]:
        """
        Отфильтровывает кросс-продукт, возникший из-за независимых IN-списков,
        оставляя только те ключи, которые реально запрашивались.
        """
        delivered: Set[DeliveredKeyDTO] = set()
        for row in rows:
            key = DeliveredKeyDTO(
                notification_date=row["notification_date"],
                source_id=row["source_id"],
                recipient_id=int(row["recipient_id"]),
            )
            if key in valid_keys:
                delivered.add(key)
        return delivered

    async def get_delivered_keys(self, *, notification_type: str, candidate_keys: Sequence[DeliveredKeyDTO], chunk_size: int = 400) -> Set[DeliveredKeyDTO]:
        """
        Батчевая проверка доставки с защитой от N+1.
        Использует IN-списки для извлечения кандидатов и фильтрует SQL кросс-продукт.
        
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

        unique_keys: Set[DeliveredKeyDTO] = set(candidate_keys)
        delivered: Set[DeliveredKeyDTO] = set()

        for chunk in self._chunk_list(list(unique_keys), chunk_size):
            dates = sorted({key.notification_date for key in chunk})
            sources = sorted({key.source_id for key in chunk})
            recipients = sorted({key.recipient_id for key in chunk})

            query = f"""
            SELECT notification_date, source_id, recipient_id
            FROM notification_delivery_log
            WHERE notification_type = ?
              AND notification_date IN ({self._generate_in_placeholders(len(dates))})
              AND source_id IN ({self._generate_in_placeholders(len(sources))})
              AND recipient_id IN ({self._generate_in_placeholders(len(recipients))})
            """
            
            rows = await self._fetch_all(query, (notification_type, *dates, *sources, *recipients))
            delivered.update(self._filter_cross_product(rows, unique_keys))

        return delivered

    async def record_notification_delivery(self, *, notification_type: str, notification_date: str, source_id: str, recipient_id: int) -> bool:
        """
        Фиксирует успешную доставку.

        Возвращает True, если была создана новая запись.
        INSERT OR IGNORE защищает от дублей при повторном вызове.

        Запись выполняется ПОСЛЕ КАЖДОЙ успешной отправки, а не батчем
        в конце тика: если процесс упадёт в середине рассылки,
        уже отправленные сообщения не продублируются на следующем тике.
        """
        changed = await self._execute(
            """
            INSERT OR IGNORE INTO notification_delivery_log (notification_type, notification_date, source_id, recipient_id, sent_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (notification_type, notification_date, source_id, recipient_id, self._now_utc_str()),
        )
        return changed == 1

    async def is_notification_delivered(self, *, notification_type: str, notification_date: str, source_id: str, recipient_id: int) -> bool:
        """
        Проверяет, доставлено ли уведомление (одиночная проверка).

        Оставлена для редких call-site (единичные проверки).
        В горячих циклах сервис использует get_delivered_keys.
        """
        row = await self._fetch_one(
            """
            SELECT 1 AS delivered
            FROM notification_delivery_log
            WHERE notification_type = ? AND notification_date = ? AND source_id = ? AND recipient_id = ?
            """,
            (notification_type, notification_date, source_id, recipient_id),
        )
        return row is not None

    async def mark_user_notifications_blocked(self, *, user_id: int) -> bool:
        """
        Помечает пользователя как заблокировавшего бот.

        ВАЖНО: is_notifications_enabled НЕ трогается — это личный
        выключатель пользователя и инструмент родителя.
        notifications_blocked — только системный маркер; он снимается
        автоматически при активности пользователя
        (profile_repository.update_last_active).
        """
        changed = await self._execute(
            "UPDATE users SET notifications_blocked = 1, updated_at = ? WHERE user_id = ? AND notifications_blocked = 0",
            (self._now_utc_str(), user_id),
        )
        return changed == 1

    async def get_blocked_user_ids(self) -> List[int]:
        """
        ID всех пользователей, заблокировавших бот.

        Один дешёвый запрос на тик вместо добавления фильтра в каждый
        recipient-запрос: при 500 пользователях скан таблицы тривиален.
        Загружается заново каждый тик, поэтому авто-разблокировка при
        активности подхватывается без перезапуска бота.
        """
        rows = await self._fetch_all("SELECT user_id FROM users WHERE notifications_blocked = 1")
        return [int(row["user_id"]) for row in rows]

    async def delete_notification_delivery_before(self, before_date_iso: str) -> int:
        """
        Удаляет записи успешных доставок до указанной даты.

        notification_date хранится как ISO YYYY-MM-DD, поэтому строковое
        сравнение корректно соответствует хронологическому.
        """
        return await self._execute("DELETE FROM notification_delivery_log WHERE notification_date < ?", (before_date_iso,))