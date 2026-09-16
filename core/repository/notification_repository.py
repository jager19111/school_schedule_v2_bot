# core/repository/notification_repository.py

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import TypeVar

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
from core.mappers.notification_mapper import NotificationMapper, DatabaseRowProtocol

T = TypeVar("T")
U = TypeVar("U")

class NotificationRepository(BaseRepository):
    """
    Репозиторий уведомлений.
    Обеспечивает доступ к расписанию и получателям.
    Строгий DTO-first подход: сырые SQL-строки не покидают этот класс.
    """

    # ==============================================================
    # 1. SQL Query Builders (Фабрики запросов)
    # ==============================================================

    @staticmethod
    def _student_class_group_cond() -> str:
        """Безопасное, жёстко привязанное к алиасу student условие класса/группы."""
        return (
            "AND student.class_id = ? "
            "AND (student.group_id = ? OR student.group_id = 'ALL' OR ? = 'ALL')"
        )

    @staticmethod
    def _class_group_params(class_id: str, group_id: str) -> tuple[str, str, str]:
        """Генерация параметров для _student_class_group_cond."""
        return (class_id, group_id, group_id)

    def _build_family_query(
        self,
        *,
        child_select: str,
        adult_select: str,
        child_where: str,
        adult_where: str,
        child_join: str = "",
        adult_join: str = "",
    ) -> str:
        """
        Генерирует базовый UNION ALL для Telegram-учеников и подписанных взрослых.
        Имеет изолированные блоки JOIN для исключения пересечений логики.
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
        {child_join}
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
        {adult_join}
        JOIN users AS adult ON adult.user_id = settings.parent_user_id
        WHERE student.is_active = 1
          AND adult.role IN ('parent', 'observer')
          AND adult.is_notifications_enabled = 1
          {adult_where}
        """

    async def _get_teacher_configs(
        self,
        *,
        select_fields: str,
        where_clause: str,
        params: tuple[object, ...],
        mapper: Callable[[DatabaseRowProtocol], T],
    ) -> list[T]:
        """Унифицированный запрос для получателей-учителей. Сразу возвращает DTO."""
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
        rows = await self._fetch_all(query, params)
        return [mapper(row) for row in rows]

    # ==============================================================
    # 2. Получение кандидатов (Students & Family)
    # ==============================================================

    async def get_recipients_for_pre_lesson_reminder(
        self, 
        class_id: str, 
        group_id: str,
    ) -> list[PreLessonRecipientDTO]:
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
        
        query = self._build_family_query(
            child_select="child.pre_lesson_offset_minutes AS offset_minutes",
            adult_select="adult.pre_lesson_offset_minutes AS offset_minutes",
            child_where=self._student_class_group_cond(),
            adult_where=f"AND settings.receive_pre_lesson_reminders = 1 {self._student_class_group_cond()}",
        ) + " ORDER BY recipient_id, student_id"
        
        params = self._class_group_params(class_id, group_id) * 2
        rows = await self._fetch_all(query, params)
        return [NotificationMapper.to_pre_lesson_recipient_dto(row) for row in rows]

    async def get_recipients_for_schedule_change(
        self, 
        class_id: str, 
        group_id: str,
    ) -> list[ScheduleChangeRecipientDTO]:
        """
        Возвращает получателей уведомления о замене/отмене урока.

        Включает:
        - Telegram-учеников;
        - взрослых, подписанных на конкретный student profile;
        - владельцев самостоятельных watch targets.
        """
        
        base_query = self._build_family_query(
            child_select="child.changes_window_days AS changes_window_days, NULL AS watch_target_title",
            adult_select="adult.changes_window_days AS changes_window_days, NULL AS watch_target_title",
            child_where=f"AND child.receive_schedule_changes = 1 {self._student_class_group_cond()}",
            adult_where=f"AND settings.receive_schedule_changes = 1 AND adult.receive_schedule_changes = 1 {self._student_class_group_cond()}",
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
        WHERE watch.is_enabled = 1
          AND watch.receive_schedule_changes = 1
          AND owner.is_notifications_enabled = 1
          AND owner.receive_schedule_changes = 1
          AND watch.class_id = ?
          AND (watch.group_id = ? OR watch.group_id = 'ALL' OR ? = 'ALL')
        """
        
        query = f"{base_query} {watch_query} ORDER BY recipient_id, student_id"
        params = self._class_group_params(class_id, group_id) * 3
        
        rows = await self._fetch_all(query, params)
        return [NotificationMapper.to_schedule_change_recipient_dto(row) for row in rows]

    async def get_morning_summary_tasks(
        self, 
        time_str: str,
    ) -> list[MorningSummaryTaskDTO]:
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

    async def get_todays_extra_classes_for_reminders(
        self, 
        day_of_week: int,
    ) -> list[ExtraClassReminderTaskDTO]:
        """
        Возвращает адресные задачи напоминаний о дополнительных занятиях.

        Telegram child получает только занятия своего student profile.
        Parent/observer получает занятия student profiles, на которые
        подписан через parent_student_settings.
        """
        join_clause = "JOIN extra_classes AS extra ON extra.student_id = student.id"
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
            child_join=join_clause,
            adult_join=join_clause,
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
        return await self._get_teacher_configs(
            select_fields="name AS teacher_name",
            where_clause="AND teacher_id IS NOT NULL AND TRIM(teacher_id) != '' AND morning_summary_time = ?",
            params=(time_str,),
            mapper=NotificationMapper.to_teacher_morning_task_dto,
        )

    async def get_teacher_recipients_for_pre_lesson_reminder(self, *, teacher_id: str) -> list[TeacherPreLessonRecipientDTO]: 
        """
        Возвращает Telegram teachers, привязанных к NIKA teacher_id.

        Teacher получает только собственные уроки.
        """
        return await self._get_teacher_configs(
            select_fields="pre_lesson_offset_minutes AS offset_minutes",
            where_clause="AND teacher_id = ? AND pre_lesson_offset_minutes > 0",
            params=(teacher_id,),
            mapper=NotificationMapper.to_teacher_pre_lesson_recipient_dto,
        )

    async def get_teacher_recipients_for_schedule_change(self, *, teacher_id: str) -> list[TeacherChangeRecipientDTO]:
        """
        Возвращает teachers, которым следует отправить уведомление
        о замене или отмене в собственном расписании.
        """
        return await self._get_teacher_configs(
            select_fields="changes_window_days",
            where_clause="AND teacher_id = ? AND receive_schedule_changes = 1 AND changes_window_days > 0",
            params=(teacher_id,),
            mapper=NotificationMapper.to_teacher_change_recipient_dto,
        )

    # ==============================================================
    # 4. Данные кэша расписания
    # ==============================================================

    async def get_todays_lessons_for_pre_reminders(self, date_iso: str) -> list[PreLessonSourceDTO]:
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

    async def get_pending_changes(
        self, 
        *, 
        start_date_iso: str, 
        end_date_iso: str | None = None,
    ) -> list[PendingChangeDTO]:
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
        params: list[object] = [start_date_iso]
        
        if end_date_iso is not None:
            query += " AND date <= ?"
            params.append(end_date_iso)
        
        query += " ORDER BY date, lesson_num, id"
        
        rows = await self._fetch_all(query, tuple(params))
        return [NotificationMapper.to_pending_change_dto(row) for row in rows]

    # ==============================================================
    # 5. Delivery Log и Throttling Controls
    # ==============================================================

    @staticmethod
    def _chunk_list(data: Sequence[U], chunk_size: int) -> Iterator[Sequence[U]]:
        """Разбивает список на чанки заданного размера."""
        for start in range(0, len(data), chunk_size):
            yield data[start:start + chunk_size]

    @staticmethod
    def _generate_in_placeholders(count: int) -> str:
        """Генерирует строку плейсхолдеров для SQL IN (...)."""
        return ",".join(["?"] * count)

    @staticmethod
    def _filter_cross_product(
        rows: Sequence[DatabaseRowProtocol], 
        valid_keys: set[DeliveredKeyDTO]
    ) -> set[DeliveredKeyDTO]:
        """
        Отфильтровывает кросс-продукт, используя строгий DTO-маппинг.
        Никаких row["..."] — только DatabaseRowProtocol.
        """
        delivered: set[DeliveredKeyDTO] = set()
        for row in rows:
            key = NotificationMapper.to_delivered_key_dto(row)
            if key in valid_keys:
                delivered.add(key)
        return delivered

    async def get_delivered_keys(
        self, 
        *, 
        notification_type: str, 
        candidate_keys: Sequence[DeliveredKeyDTO], 
        chunk_size: int = 250,
    ) -> set[DeliveredKeyDTO]:
        """
        Батчевая проверка доставки с защитой от N+1.
        Принимает и возвращает исключительно объекты DeliveredKeyDTO.
        chunk_size установлен в 250.
        1 параметр (notification_type) + до 3 * chunk_size параметров IN.
        Для chunk_size=250 максимум 751 параметр, что безопасно ниже legacy SQLite limit (999).
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
            
        if not candidate_keys:
            return set()

        unique_keys: set[DeliveredKeyDTO] = set(candidate_keys)
        delivered: set[DeliveredKeyDTO] = set()

        for chunk in self._chunk_list(list(unique_keys), chunk_size):
            # Извлекаем параметры для SQL напрямую из DTO
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
            # Фильтруем и пополняем сет готовыми DeliveredKeyDTO
            delivered.update(self._filter_cross_product(rows, unique_keys))

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
        changed = await self._execute(
            """
            INSERT OR IGNORE INTO notification_delivery_log (notification_type, notification_date, source_id, recipient_id, sent_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (notification_type, notification_date, source_id, recipient_id, self._now_utc_str()),
        )
        return changed == 1

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

    async def get_blocked_user_ids(self) -> list[int]:
        
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
        return await self._execute(
            "DELETE FROM notification_delivery_log WHERE notification_date < ?", 
            (before_date_iso,)
        )