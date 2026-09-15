# services/schedule_service.py
from typing import List, Optional, Literal
from datetime import timedelta, datetime, time
from collections import Counter
import logging

from core.repository.schedule_repository import ScheduleRepository
from core.models.domain import LessonInstance
from services.time_service import TimeService
from services.extra_classes_service import ExtraClassesService
from core.mappers.lesson_mapper import LessonMapper


from core.mappers.metadata_mapper import MetadataMapper

from core.models.dto import (
    DayScheduleDTO,
    DaySummaryDTO,
    WeekSummaryDTO,
    FullWeekScheduleDTO,
    ClassListDTO,
    GroupListDTO,
    TeacherListDTO,
    SchoolDictionariesDTO,
    ExtraClassItemDTO, 
    DayChangesDetailDTO,
    LessonDTO,
)
from core.models.metadata import SchoolMetadata

logger = logging.getLogger(__name__)


class ScheduleService:

    def __init__(
        self,
        schedule_repo: ScheduleRepository,
        time_service: TimeService,
        extra_classes_service: ExtraClassesService,
    ):
        self.schedule_repo = schedule_repo
        self.time_service = time_service
        self.extra_classes_service = extra_classes_service

    # ==========================================================
    # Вспомогательные методы
    # ==========================================================

    @staticmethod
    def _parse_hhmm(value: str) -> time:
        hour, minute = map(int, value.split(":"))
        return time(hour, minute)

    @staticmethod
    def _sort_key(lesson: LessonDTO):
        num = lesson.lesson_num if lesson.lesson_num is not None else 999
        return (ScheduleService._parse_hhmm(lesson.start_time), num)

    # ==========================================================
    # Справочники (возвращают DTO)
    # ==========================================================

    async def get_school_dictionaries(self) -> SchoolDictionariesDTO:
        metadata = await self.schedule_repo.get_metadata()
        classes_dict = {str(k): str(getattr(v, 'name', v)) for k, v in metadata.classes.items()}
        groups_dict = {str(k): str(v) for k, v in metadata.groups.items()}
        return SchoolDictionariesDTO(classes=classes_dict, groups=groups_dict)

    async def get_classes_list(self) -> ClassListDTO:
        metadata = await self.schedule_repo.get_metadata()
        classes_dict = {str(k): str(getattr(v, 'name', v)) for k, v in metadata.classes.items()}
        return ClassListDTO(classes=classes_dict)

    async def get_groups_list(self) -> GroupListDTO:
        metadata = await self.schedule_repo.get_metadata()
        return GroupListDTO(groups=metadata.groups)

    async def get_teachers_list(self) -> TeacherListDTO:
        metadata = await self.schedule_repo.get_metadata()
        teachers = {str(k): str(getattr(v, 'name', v)) for k, v in metadata.teachers.items()}
        return TeacherListDTO(teachers=teachers)

    # ==========================================================
    # Детекция перестановок
    # ==========================================================

    @staticmethod
    def _detect_day_permutation(lessons: List['LessonInstance']) -> bool:
        """
        Определяет, являются ли изменения в расписании простой перестановкой (🔁).
        
        Алгоритм:
        Сравнивает мультимножества (Counter) 4D-сигнатур уроков.
        Использует строгое обращение к атрибутам модели без getattr.
        """
        # 1. Отбираем только замены (напрямую читаем boolean-поля)
        exchanges = [
            l for l in lessons 
            if l.is_exchange and not l.is_cancelled
        ]

        if len(exchanges) < 2:
            return False

        orig_counter = Counter(
            (
                l.original_subject_id,
                l.original_room_id,
                l.original_teacher_id,
                l.original_group_id or "ALL"
            )
            for l in exchanges
        )

        curr_counter = Counter(
            (
                l.subject_id,
                l.room_id,
                l.teacher_id,
                l.group_id or "ALL"
            )
            for l in exchanges
        )

        return orig_counter == curr_counter
    
    # ==========================================================
    # Детализация изменений
    # ==========================================================

    async def get_day_changes_detail(
        self,
        *,
        class_id: Optional[str] = None,
        teacher_id: Optional[str] = None,
        date_iso: str,
        origin: Literal["class", "teacher"] = "class",
    ) -> DayChangesDetailDTO:
        """
        Возвращает список изменённых/отменённых уроков за дату
        с полями «было → стало」для рендерера изменений.

        lessons: List[LessonDTO] — только school lessons.
        """
        if origin == "class":
            if not class_id:
                raise ValueError("class_id required for origin='class'")
            lessons = await self.schedule_repo.get_lessons_for_class(
                class_id=class_id,
                date_iso=date_iso,
            )
        else:
            if not teacher_id:
                raise ValueError("teacher_id required for origin='teacher'")
            lessons = await self.schedule_repo.get_lessons_for_teacher(
                teacher_id=teacher_id,
                date_iso=date_iso,
            )

        changed = [
            l for l in lessons
            if l.is_exchange or l.is_cancelled
        ]
        changed.sort(key=lambda l: l.lesson_num or 99)

        day_permutation = self._detect_day_permutation(changed)
        lesson_dtos = LessonMapper.to_dto_list(changed, day_permutation=day_permutation)

        # P2: Обогащаем display_num для изменений
        metadata = await self.schedule_repo.get_metadata()
        self._enrich_display_numbers_dtos(
            lessons=lesson_dtos,
            metadata=metadata,
        )
        return DayChangesDetailDTO(
            date_iso=date_iso,
            origin=origin,
            lessons=lesson_dtos,
        )

    # ==========================================================
    # Расписание студента
    # ==========================================================

    async def get_daily_schedule_for_student(
        self,
        *,
        class_id: str,
        group_id: str,
        date_iso: str,
        student_id: int | None = None,
    ) -> DayScheduleDTO:
        """
        Возвращает расписание student profile на день.

        lessons: List[LessonDTO] — school (LessonDTO)
        + extra.
        """
        base_lessons: List[LessonInstance] = (
            await self.schedule_repo.get_lessons_for_class(
                class_id=class_id,
                date_iso=date_iso,
            )
        )

        day_permutation = self._detect_day_permutation(base_lessons)

        user_groups = group_id.split(",") if group_id and group_id != "ALL" else ["ALL"]
        filtered_base: List[LessonInstance] = [
            lesson for lesson in base_lessons
            if "ALL" in user_groups or lesson.group_id == "ALL" or lesson.group_id in user_groups
        ]

        school_lessons: List[LessonDTO] = LessonMapper.to_dto_list(
            filtered_base, day_permutation=day_permutation
        )

        extra_lessons: List[LessonDTO] = []

        if student_id is not None:
            date_obj = self.time_service.date_from_iso(
                date_iso
            )
            weekday = date_obj.isoweekday()

            extra_items = (
                await self.extra_classes_service.get_extra_classes_for_student(
                    student_id=student_id,
                    day_of_week=weekday,
                )
            )

            extra_lessons = [
                self._map_extra_to_lesson(
                    extra,
                    date_iso,
                )
                for extra in extra_items
            ]

        metadata = await self.schedule_repo.get_metadata()
        self._enrich_display_numbers_dtos(
            lessons=school_lessons,
            metadata=metadata,
        )
        
        combined: List[LessonDTO] = school_lessons + extra_lessons
        combined.sort(key=self._sort_key)



        return DayScheduleDTO(
            date_iso=date_iso,
            lessons=combined,
            has_permutation=day_permutation,
        )

    # ==========================================================
    # Общие хелперы (Smart Date / Weekly)
    # ==========================================================

    async def _find_target_date(
        self,
        get_daily_schedule,
        today: datetime.date,
    ) -> str:
        now = self.time_service.get_now_base()

        for offset in range(8):
            candidate_date = today + timedelta(days=offset)
            candidate_iso = candidate_date.isoformat()
            day_dto = await get_daily_schedule(date_iso=candidate_iso)

            if not day_dto.lessons:
                continue
            if candidate_date != today:
                return candidate_iso

            end_times = [
                self._parse_hhmm(l.end_time)
                for l in day_dto.lessons
                if l.end_time
            ]
            if not end_times:
                continue

            latest_end = max(end_times)
            now_time = now.time()

            if now_time <= latest_end:
                return candidate_iso

        return today.isoformat()

    async def _build_week_schedule(
        self,
        get_daily_schedule,
        week_start_iso: str,
    ) -> FullWeekScheduleDTO:
        start_date = self.time_service.date_from_iso(week_start_iso)
        days = []
        for i in range(6):
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await get_daily_schedule(date_iso=current_date_iso)
            days.append(day_dto)
        return FullWeekScheduleDTO(week_start_iso=week_start_iso, days=days)

    async def get_smart_target_date(self, *, class_id: str, group_id: str, student_id: int | None = None) -> str:
        """
        Возвращает ближайшую дату, на которую есть ещё актуальное расписание.

        Правило:
        - если сегодня есть занятия и они ещё не завершились — вернуть сегодня;
        - если занятия сегодня закончились — искать следующий день;
        - если выходной, каникулы или пустое расписание — искать вперёд;
        - поиск ограничен 8 календарными днями.
        """
        today = self.time_service.get_now_base().date()

        async def get_daily(date_iso: str):
            return await self.get_daily_schedule_for_student(
                class_id=class_id,
                group_id=group_id,
                date_iso=date_iso,
                student_id=student_id,
            )

        return await self._find_target_date(get_daily, today)

    async def get_smart_teacher_target_date(self, *, teacher_id: str) -> str:
        today = self.time_service.get_now_base().date()

        async def get_daily(date_iso: str):
            return await self.get_daily_schedule_for_teacher(
                teacher_id=teacher_id,
                date_iso=date_iso,
            )

        return await self._find_target_date(get_daily, today)

    async def get_smart_week_start(self) -> str:
        """
        Возвращает понедельник текущей недели. Если сегодня воскресенье (или вечер субботы),
        возвращает понедельник следующей недели.
        """
        now = self.time_service.get_now_base()

        if now.isoweekday() == 7: 
            target_date = now + timedelta(days=1)
        elif now.isoweekday() == 6 and now.hour >= 15: 
            target_date = now + timedelta(days=2)
        else:
            target_date = now

        monday = target_date - timedelta(days=target_date.isoweekday() - 1)
        return monday.date().isoformat()

    async def get_full_week_schedule(
        self,
        class_id: str,
        group_id: str,
        week_start_iso: str,
        student_id: int | None = None,
    ) -> FullWeekScheduleDTO:
        """Собирает сводку (кол-во уроков, замен, доп. занятий) на неделю."""
        async def get_daily(date_iso: str):
            return await self.get_daily_schedule_for_student(
                class_id=class_id,
                group_id=group_id,
                date_iso=date_iso,
                student_id=student_id,
            )
        return await self._build_week_schedule(get_daily, week_start_iso)

    async def get_full_week_schedule_for_class(
        self,
        class_id: str,
        week_start_iso: str,
    ) -> FullWeekScheduleDTO:
        async def get_daily(date_iso: str):
            return await self.get_daily_schedule_for_class(
                class_id=class_id,
                date_iso=date_iso,
            )
        return await self._build_week_schedule(get_daily, week_start_iso)

    async def get_full_week_schedule_for_teacher(
        self,
        teacher_id: str,
        week_start_iso: str,
    ) -> FullWeekScheduleDTO:
        async def get_daily(date_iso: str):
            return await self.get_daily_schedule_for_teacher(
                teacher_id=teacher_id,
                date_iso=date_iso,
            )
        return await self._build_week_schedule(get_daily, week_start_iso)

    # ==========================================================
    # Расписание класса
    # ==========================================================

    async def get_daily_schedule_for_class(
        self,
        class_id: str,
        date_iso: str,
    ) -> DayScheduleDTO:
        lessons: List[LessonInstance] = (
            await self.schedule_repo.get_lessons_for_class(
                class_id=class_id,
                date_iso=date_iso,
            )
        )

        day_permutation = self._detect_day_permutation(lessons)

        school_lessons: List[LessonDTO] = LessonMapper.to_dto_list(
            lessons, day_permutation=day_permutation
        )

        combined = sorted(school_lessons, key=self._sort_key)

        metadata = await self.schedule_repo.get_metadata()
        self._enrich_display_numbers_dtos(
            lessons=combined,
            metadata=metadata,
        )

        return DayScheduleDTO(
            date_iso=date_iso,
            lessons=combined,
            has_permutation=day_permutation,
        )

    # ==========================================================
    # Расписание учителя
    # ==========================================================

    async def get_daily_schedule_for_teacher(
        self,
        teacher_id: str,
        date_iso: str,
    ) -> DayScheduleDTO:

        lessons: List[LessonInstance] = (
            await self.schedule_repo.get_lessons_for_teacher(
                teacher_id=teacher_id,
                date_iso=date_iso,
            )
        )
        day_permutation = self._detect_day_permutation(lessons)

        school_lessons: List[LessonDTO] = LessonMapper.to_dto_list(
            lessons, day_permutation=day_permutation
        )

        combined = sorted(school_lessons, key=self._sort_key)

        metadata = await self.schedule_repo.get_metadata()
        self._enrich_display_numbers_dtos(
            lessons=combined,
            metadata=metadata,
        )
        return DayScheduleDTO(
            date_iso=date_iso,
            lessons=combined,
            has_permutation=day_permutation,
        )

    # ==========================================================
    # Недельные сводки
    # ==========================================================

    async def get_week_schedule_summary(
        self,
        class_id: str,
        group_id: str,
        week_start_iso: str,
        student_id: int | None = None,
    ) -> WeekSummaryDTO:
        start_date = self.time_service.date_from_iso(week_start_iso)
        day_summaries = []

        for i in range(6):
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_student(
                class_id=class_id,
                group_id=group_id,
                date_iso=current_date_iso,
                student_id=student_id,
            )

            main_lesson_nums = {
                l.lesson_num
                for l in day_dto.lessons
                if not l.is_extra and l.lesson_num is not None
            }
            main_count = len(main_lesson_nums)

            exchange_nums = {
                l.lesson_num
                for l in day_dto.lessons
                if l.is_exchange and not l.is_extra
                and l.lesson_num is not None
            }
            exchange_count = len(exchange_nums)

            extra_count = sum(1 for l in day_dto.lessons if l.is_extra)

            day_summaries.append(DaySummaryDTO(
                date_iso=current_date_iso,
                lesson_count=main_count,
                extra_count=extra_count,
                exchange_count=exchange_count,
            ))

        return WeekSummaryDTO(week_start_iso=week_start_iso, days=day_summaries)

    async def get_teacher_week_schedule_summary(
        self,
        *,
        teacher_id: str,
        week_start_iso: str,
    ) -> WeekSummaryDTO:
        """
        Собирает краткое расписание учителя на неделю.

        Для учителя не применяются student groups и extra classes.
        Количество уроков — количество lesson records за день.
        """
        start_date = self.time_service.date_from_iso(week_start_iso)
        days = []

        for offset in range(6):
            current_date = start_date + timedelta(days=offset)
            current_date_iso = current_date.isoformat()

            day_dto = await self.get_daily_schedule_for_teacher(
                teacher_id=teacher_id,
                date_iso=current_date_iso,
            )

            lesson_count = len(day_dto.lessons)
            exchange_count = sum(
                1 for l in day_dto.lessons if l.is_exchange
            )

            days.append(
                DaySummaryDTO(
                    date_iso=current_date_iso,
                    lesson_count=lesson_count,
                    extra_count=0,
                    exchange_count=exchange_count,
                )
            )

        return WeekSummaryDTO(
            week_start_iso=week_start_iso,
            days=days,
        )

    @staticmethod
    def _map_extra_to_lesson(
        row: 'ExtraClassItemDTO', 
        date_iso: str,
    ) -> LessonDTO:
        return LessonDTO(
            id=f"extra-{row.id}",
            date_iso=date_iso,
            lesson_num=None,
            display_num="•",
            start_time=row.time_start,
            end_time=row.time_end,
            subject_name=row.title,
            room_name=row.location or "—",
            is_cancelled=False,
            is_exchange=False,
            is_extra=True,
            is_methodological=False,
            period_id=None,
            class_id=None,
            class_name=None,
            group_id="ALL",
            group_name="Весь класс",
            teacher_id=None,
            teacher_name=None,
            original_subject_id=None,
            original_subject_name=None,
            original_teacher_id=None,
            original_teacher_name=None,
            original_room_id=None,
            original_room_name=None,
            original_group_id=None,
            original_group_name=None,
            original_class_id=None,
            original_class_name=None,
            group_changed=False,
            day_permutation=False,
        )
    @staticmethod
    def _enrich_display_numbers_dtos(lessons: List[LessonDTO], metadata: SchoolMetadata) -> None:

        """
        Обогащает LessonDTO.display_num с учётом 2 смены.

        period_id берётся из LessonDTO.period_id.
        metadata.class_shift[period_id][class_id] = shift_start.
        """
        class_shifts = metadata.class_shift
        second_relative = metadata.second_relative

        groups = {}
        for l in lessons:
            if not l.is_methodological and l.lesson_num:
                p_id = l.period_id or l.class_id or "default"
                c_id = l.class_id or "default"
                key = (p_id, c_id)
                groups.setdefault(key, []).append(l)

        for (p_id, c_id), day_lessons in groups.items():
            shift_start = 1
            if p_id in class_shifts and c_id in class_shifts[p_id]:
                shift_start = int(class_shifts[p_id][c_id])

            day_lessons.sort(key=lambda x: x.lesson_num)

            w_flag = (shift_start == 1)
            for l in day_lessons:
                m = l.lesson_num
                v = m
                is_star = False

                if shift_start > 1 and not w_flag:
                    if m < shift_start:
                        w_flag = True
                    else:
                        v = m - shift_start + 1
                        is_star = True

                if is_star:
                    display_val = v if second_relative else m
                    l.display_num = f"{display_val}*"
                else:
                    l.display_num = str(m)

        for l in lessons:
            if l.display_num is None:
                l.display_num = "•"
                
    # ==========================================================
    # Прокидываем DTO в хендлеры
    # ==========================================================            
                
    async def get_classes_list(self) -> ClassListDTO:
        metadata = await self.schedule_repo.get_metadata()

        return MetadataMapper.to_class_list_dto(metadata)


    async def get_teachers_list(self) -> TeacherListDTO:
        metadata = await self.schedule_repo.get_metadata()

        return MetadataMapper.to_teacher_list_dto(metadata)


    async def get_groups_list(self) -> GroupListDTO:
        metadata = await self.schedule_repo.get_metadata()

        return MetadataMapper.to_group_list_dto(metadata)
    
    
    async def get_teacher_name(self, teacher_id: str) -> str:
        teacher_dto = await self.get_teachers_list()

        return teacher_dto.teachers.get(
            str(teacher_id),
            "Преподаватель",
        )


    async def get_class_name(self, class_id: str) -> str:
        class_dto = await self.get_classes_list()

        return class_dto.classes.get(
            str(class_id),
            "Класс",
        )
    # Прокидываем display_num в DTO    
    async def get_display_numbers_for_class_day(
        self,
        *,
        class_id: str,
        date_iso: str,
    ) -> dict[int, str]:
        lessons = await self.schedule_repo.get_lessons_for_class(
            class_id=class_id,
            date_iso=date_iso,
        )

        day_permutation = self._detect_day_permutation(lessons)

        lesson_dtos = LessonMapper.to_dto_list(
            lessons,
            day_permutation=day_permutation,
        )

        metadata = await self.schedule_repo.get_metadata()

        self._enrich_display_numbers_dtos(
            lessons=lesson_dtos,
            metadata=metadata,
        )

        return {
            lesson.lesson_num: (
                lesson.display_num
                or str(lesson.lesson_num)
            )
            for lesson in lesson_dtos
            if lesson.lesson_num is not None
        }