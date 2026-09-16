# core/mappers/notification_mapper.py

from typing import Any, Optional, Protocol
from core.models.dto import (
    PreLessonSourceDTO, PreLessonRecipientDTO, PendingChangeDTO,
    ScheduleChangeRecipientDTO, MorningSummaryTaskDTO, ExtraClassReminderTaskDTO,
    TeacherMorningTaskDTO, TeacherPreLessonRecipientDTO, TeacherChangeRecipientDTO,
    MorningLessonDTO, ExtraClassItemDTO, ChangeReminderDTO, DeliveredKeyDTO
)
from core.models.domain import LessonInstance

class DatabaseRowProtocol(Protocol):
    """
    Контракт для безопасной распаковки строк базы данных.
    Отвязывает маппер от конкретного драйвера БД (sqlite3, asyncpg, dict и т.д.).
    """
    def get(self, key: str, default: Any = None) -> Any: ...
    def __getitem__(self, key: str) -> Any: ...


class FieldHelper:
    """Единый helper для безопасного извлечения и приведения типов из SQL-строк."""
    
    @staticmethod
    def as_optional_str(val: Any) -> str | None:
        if val is None:
            return None
        s = str(val).strip()
        return s if s else None

    @staticmethod
    def as_str(val: Any, default: str = "") -> str:
        return FieldHelper.as_optional_str(val) or default

    @staticmethod
    def as_optional_int(val: Any) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def as_int(val: Any, default: int = 0) -> int:
        res = FieldHelper.as_optional_int(val)
        return res if res is not None else default

    @staticmethod
    def as_bool(val: Any) -> bool:
        if val is None:
            return False
        if isinstance(val, int):
            return bool(val)
        if isinstance(val, str):
            return val.lower() in ("1", "true", "yes")
        return bool(val)


class NotificationMapper:
    """
    Слой адаптации SQL-строк и Domain-моделей в DTO.
    Используется строго внутри слоя Repository и Collector.
    """

    @staticmethod
    def to_delivered_key_dto(row: DatabaseRowProtocol) -> DeliveredKeyDTO:
        """Безопасный маппинг строки БД в ключ дедупликации."""
        return DeliveredKeyDTO(
            notification_date=FieldHelper.as_str(row.get("notification_date")),
            source_id=FieldHelper.as_str(row.get("source_id")),
            recipient_id=FieldHelper.as_int(row.get("recipient_id")),
        )
        
    # ==========================================
    # Мапперы для Репозитория (DatabaseRowProtocol -> DTO)
    # ==========================================

    @staticmethod
    def to_pre_lesson_source_dto(row: DatabaseRowProtocol) -> PreLessonSourceDTO:
        return PreLessonSourceDTO(
            id=FieldHelper.as_str(row.get("id")),
            date=FieldHelper.as_str(row.get("date")),
            class_id=FieldHelper.as_str(row.get("class_id")),
            group_id=FieldHelper.as_optional_str(row.get("group_id")),
            teacher_id=FieldHelper.as_optional_str(row.get("teacher_id")),
            start_time=FieldHelper.as_str(row.get("start_time")),
            subject_name=FieldHelper.as_optional_str(row.get("subject_name")),
            room_name=FieldHelper.as_optional_str(row.get("room_name")),
        )

    @staticmethod
    def to_pre_lesson_recipient_dto(row: DatabaseRowProtocol) -> PreLessonRecipientDTO:
        return PreLessonRecipientDTO(
            student_id=FieldHelper.as_optional_int(row.get("student_id")),
            recipient_id=FieldHelper.as_int(row.get("recipient_id")),
            offset_minutes=FieldHelper.as_int(row.get("offset_minutes")),
            recipient_kind=FieldHelper.as_str(row.get("recipient_kind")),
            child_name=FieldHelper.as_optional_str(row.get("child_name")),
        )

    @staticmethod
    def to_pending_change_dto(row: DatabaseRowProtocol) -> PendingChangeDTO:
        return PendingChangeDTO(
            id=FieldHelper.as_str(row.get("id")),
            date=FieldHelper.as_str(row.get("date")),
            period_id=FieldHelper.as_str(row.get("period_id")),
            class_id=FieldHelper.as_str(row.get("class_id")),
            group_id=FieldHelper.as_str(row.get("group_id"), default="ALL"),
            group_name=FieldHelper.as_optional_str(row.get("group_name")),
            teacher_id=FieldHelper.as_optional_str(row.get("teacher_id")),
            lesson_num=FieldHelper.as_int(row.get("lesson_num")),
            subject_id=FieldHelper.as_optional_str(row.get("subject_id")),
            subject_name=FieldHelper.as_optional_str(row.get("subject_name")),
            room_id=FieldHelper.as_optional_str(row.get("room_id")),
            room_name=FieldHelper.as_optional_str(row.get("room_name")),
            teacher_name=FieldHelper.as_optional_str(row.get("teacher_name")),
            original_subject_id=FieldHelper.as_optional_str(row.get("original_subject_id")),
            original_subject_name=FieldHelper.as_optional_str(row.get("original_subject_name")),
            original_room_id=FieldHelper.as_optional_str(row.get("original_room_id")),
            original_room_name=FieldHelper.as_optional_str(row.get("original_room_name")),
            original_teacher_id=FieldHelper.as_optional_str(row.get("original_teacher_id")),
            original_teacher_name=FieldHelper.as_optional_str(row.get("original_teacher_name")),
            original_group_id=FieldHelper.as_optional_str(row.get("original_group_id")),
            original_group_name=FieldHelper.as_optional_str(row.get("original_group_name")),
            original_class_id=FieldHelper.as_optional_str(row.get("original_class_id")),
            original_class_name=FieldHelper.as_optional_str(row.get("original_class_name")),
            is_exchange=FieldHelper.as_bool(row.get("is_exchange")),
            is_cancelled=FieldHelper.as_bool(row.get("is_cancelled")),
        )

    @staticmethod
    def to_schedule_change_recipient_dto(row: DatabaseRowProtocol) -> ScheduleChangeRecipientDTO:
        return ScheduleChangeRecipientDTO(
            student_id=FieldHelper.as_optional_int(row.get("student_id")),
            recipient_id=FieldHelper.as_int(row.get("recipient_id")),
            changes_window_days=FieldHelper.as_int(row.get("changes_window_days")),
            recipient_kind=FieldHelper.as_str(row.get("recipient_kind")),
            child_name=FieldHelper.as_optional_str(row.get("child_name")),
            watch_target_title=FieldHelper.as_optional_str(row.get("watch_target_title")),
        )

    @staticmethod
    def to_morning_summary_task_dto(row: DatabaseRowProtocol) -> MorningSummaryTaskDTO:
        return MorningSummaryTaskDTO(
            recipient_id=FieldHelper.as_int(row.get("recipient_id")),
            target_student_id=FieldHelper.as_int(row.get("target_student_id")),
            recipient_kind=FieldHelper.as_str(row.get("recipient_kind")),
            child_name=FieldHelper.as_optional_str(row.get("child_name")),
            class_id=FieldHelper.as_optional_str(row.get("class_id")),
            group_id=FieldHelper.as_optional_str(row.get("group_id")),
        )

    @staticmethod
    def to_extra_class_reminder_task_dto(row: DatabaseRowProtocol) -> ExtraClassReminderTaskDTO:
        return ExtraClassReminderTaskDTO(
            extra_id=FieldHelper.as_int(row.get("extra_id")),
            student_id=FieldHelper.as_int(row.get("student_id")),
            time_start=FieldHelper.as_str(row.get("time_start")),
            title=FieldHelper.as_str(row.get("title")),
            location=FieldHelper.as_optional_str(row.get("location")),
            recipient_id=FieldHelper.as_int(row.get("recipient_id")),
            offset_minutes=FieldHelper.as_int(row.get("offset_minutes")),
            recipient_kind=FieldHelper.as_str(row.get("recipient_kind")),
            child_name=FieldHelper.as_optional_str(row.get("child_name")),
        )

    @staticmethod
    def to_teacher_morning_task_dto(row: DatabaseRowProtocol) -> TeacherMorningTaskDTO:
        return TeacherMorningTaskDTO(
            recipient_id=FieldHelper.as_int(row.get("recipient_id")),
            teacher_id=FieldHelper.as_str(row.get("teacher_id")),
            teacher_name=FieldHelper.as_optional_str(row.get("teacher_name")),
        )

    @staticmethod
    def to_teacher_pre_lesson_recipient_dto(row: DatabaseRowProtocol) -> TeacherPreLessonRecipientDTO:
        return TeacherPreLessonRecipientDTO(
            recipient_id=FieldHelper.as_int(row.get("recipient_id")),
            teacher_id=FieldHelper.as_str(row.get("teacher_id")),
            offset_minutes=FieldHelper.as_int(row.get("offset_minutes")),
        )

    @staticmethod
    def to_teacher_change_recipient_dto(row: DatabaseRowProtocol) -> TeacherChangeRecipientDTO:
        return TeacherChangeRecipientDTO(
            recipient_id=FieldHelper.as_int(row.get("recipient_id")),
            teacher_id=FieldHelper.as_str(row.get("teacher_id")),
            changes_window_days=FieldHelper.as_int(row.get("changes_window_days")),
        )

    # ==========================================
    # Мапперы для Сервиса (Domain/DTO -> DTO)
    # ==========================================

    @staticmethod
    def map_school_lesson_to_morning_dto(
        lesson: LessonInstance,
        *,
        display_num: str | None = None,
        group_name: str | None = None,
        class_name: str | None = None,
        day_permutation: bool = False,
    ) -> MorningLessonDTO:
        return MorningLessonDTO(
            lesson_num=lesson.lesson_num,
            start_time=lesson.start_time or "—",
            end_time=lesson.end_time or "—",
            subject_name=lesson.subject_name or "—",
            room_name=lesson.room_name or "—",
            is_cancelled=lesson.is_cancelled,
            is_exchange=lesson.is_exchange,
            is_extra=False,
            is_methodological=lesson.is_methodological,
            original_subject_name=lesson.original_subject_name or None,
            original_room_name=lesson.original_room_name or None,
            group_changed=(
                lesson.is_exchange
                and lesson.original_group_id is not None
                and lesson.original_group_id != lesson.group_id
            ),
            day_permutation=day_permutation,
            group_name=group_name,
            class_name=class_name,
            teacher_name=lesson.teacher_name,
            display_num=(display_num or (str(lesson.lesson_num) if lesson.lesson_num is not None else "•")),
            group_id=lesson.group_id,
        )

    @staticmethod
    def map_extra_to_morning_dto(extra: ExtraClassItemDTO) -> MorningLessonDTO:
        return MorningLessonDTO(
            lesson_num=None,
            start_time=extra.time_start or "—",
            end_time=extra.time_end or "—",
            subject_name=extra.title or "—",
            room_name=extra.location or "—",
            is_cancelled=False,
            is_exchange=False,
            is_extra=True,
            is_methodological=False,
            original_subject_name=None,
            original_room_name=None,
            group_changed=False,
            day_permutation=False,
            group_name=None,
            class_name=None,
            teacher_name=None,
            display_num="•",
            group_id=None,
        )

    @staticmethod
    def to_change_reminder_dto(
        change: PendingChangeDTO,
        *,
        child_name: str | None = None,
        watch_target_title: str | None = None,
        display_num: str | None = None,
    ) -> ChangeReminderDTO:
        return ChangeReminderDTO(
            change_id=change.id,
            date=change.date,
            lesson_num=change.lesson_num,
            display_num=(display_num if display_num is not None else change.display_num),
            subject_name=change.subject_name or "—",
            is_cancelled=change.is_cancelled,
            original_subject_name=change.original_subject_name,
            new_subject_name=change.subject_name,
            original_room_name=change.original_room_name,
            new_room_name=change.room_name,
            original_group_name=change.original_group_name,
            new_group_name=change.group_name,
            group_changed=(bool(change.original_group_id) and change.original_group_id != change.group_id),
            child_name=child_name,
            watch_target_title=watch_target_title,
        )