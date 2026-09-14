# core/mappers/lesson_mapper.py
from typing import List
from core.models.domain import LessonInstance
from core.models.dto import LessonDTO


class LessonMapper:
    """
    Единый маппер LessonInstance → LessonDTO.
    Гарантирует консистентное преобразование доменных моделей в DTO,
    включая строгую очистку строковых данных от мусора парсера NIKA.
    """

    @staticmethod
    def to_dto(
        lesson: LessonInstance,
        *,
        day_permutation: bool = False,
        is_extra: bool = False,
    ) -> LessonDTO:
        return LessonDTO(
            id=lesson.id,
            lesson_num=lesson.lesson_num,
            start_time=lesson.start_time,
            end_time=lesson.end_time,
            subject_name=(lesson.subject_name or "").strip(),
            room_name=(lesson.room_name or "").strip(),
            is_cancelled=lesson.is_cancelled,
            is_exchange=lesson.is_exchange,
            is_extra=is_extra,
            date_iso=lesson.date,
            
            period_id=lesson.period_id,
            group_id=lesson.group_id,
            group_name=(lesson.group_name or "").strip(),
            class_id=lesson.class_id,
            class_name=lesson.class_name,
            teacher_id=lesson.teacher_id,
            teacher_name=(lesson.teacher_name or "").strip(),
            is_methodological=lesson.is_methodological,

            original_subject_id=lesson.original_subject_id,
            original_subject_name=(lesson.original_subject_name or "").strip() if lesson.original_subject_name else None,
            original_teacher_id=lesson.original_teacher_id,
            original_teacher_name=(lesson.original_teacher_name or "").strip() if lesson.original_teacher_name else None,
            original_room_id=lesson.original_room_id,
            original_room_name=(lesson.original_room_name or "").strip() if lesson.original_room_name else None,
            original_group_id=lesson.original_group_id,
            original_group_name=lesson.original_group_name,
            original_class_id=lesson.original_class_id,
            original_class_name=lesson.original_class_name,

            group_changed=(
                lesson.is_exchange
                and lesson.original_group_id is not None
                and lesson.original_group_id != lesson.group_id
            ),
            day_permutation=day_permutation,
        )

    @staticmethod
    def to_dto_list(
        lessons: List[LessonInstance],
        *,
        day_permutation: bool = False,
        is_extra: bool = False,
    ) -> List[LessonDTO]:
        return [
            LessonMapper.to_dto(lesson, day_permutation=day_permutation, is_extra=is_extra)
            for lesson in lessons
        ]