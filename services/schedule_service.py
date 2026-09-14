# services/schedule_service.py
#
# ЭТАП 3 (репозиторий → сервис): переход на типизированные DTO
# (LessonInstance), детекция перестановок уроков (🔁 vs 🔀),
# детализация изменений «было → стало」для кнопок UI.
#
# РЕШЁННЫЕ ПРОБЛЕМЫ:
#
# 1. Типизация: сервис больше не работает со словарями из репозитория.
#    Все методы используют get_lesson_instances_for_*() и оперируют
#    LessonInstance (DTO), что гарантирует наличие полей original_*,
#    class_name, is_methodological и т.д.
#
# 2. Детекция перестановок: добавлен метод _detect_day_permutation(),
#    который сравнивает мультимножество (subject_id, room_id) до и
#    после замены. Если множества совпадают — уроки просто поменялись
#    местами (🔁), иначе — реальная замена предмета/кабинета (🔀).
#
# 3. Детализация изменений: новый публичный метод
#    get_day_changes_detail() возвращает список уроков с
#    is_exchange/is_cancelled, обогащённый полями «было → стало」.
#    Рендерер использует его для кнопки «посмотреть изменения подробно」。
#
# 4. Группа изменилась: если original_group_id != group_id, в DTO
#    добавляется флаг group_changed=True (рендерер может подсветить
#    смену группы отдельной иконкой).
#
# 5. Учительский кэш: get_daily_schedule_for_teacher() берёт class_name
#    напрямую из LessonInstance (репозиторий уже сохранил), а не из
#    отдельного metadata-запроса.
#
# 6. Extra-уроки: маппинг extra_classes → lesson-словарь сохранён,
#    но теперь явно помечается is_extra=True и не смешивается с
#    school-уроками при детекции перестановок.

from typing import List, Dict, Any, Optional, Literal, Union
from datetime import timedelta
from collections import Counter
import logging
from core.repository.schedule_repository import ScheduleRepository
from core.repository.extra_classes_repository import ExtraClassesRepository
from core.models.domain import LessonInstance
from services.time_service import TimeService
from core.models.dto import (
    DayScheduleDTO,
    DaySummaryDTO,
    WeekSummaryDTO,
    FullWeekScheduleDTO,
    ClassListDTO,
    GroupListDTO,
    TeacherListDTO,
    SchoolDictionariesDTO,
    DayChangesDetailDTO, LessonDTO
)


logger = logging.getLogger(__name__)


class ScheduleService:
    """
    Сервис школьного расписания.

    Основные правила:
    - Работает только с LessonInstance (DTO), не со словарями;
    - Детектирует перестановки уроков (🔁) vs реальные замены (🔀);
    - Возвращает детализацию изменений для UI-кнопок;
    - Умная фильтрация по группам с учётом «неделимых」предметов.
    """

    def __init__(
        self,
        schedule_repo: ScheduleRepository,
        extra_classes_repo: ExtraClassesRepository,
        time_service: TimeService,
    ):
        self.schedule_repo = schedule_repo
        self.extra_repo = extra_classes_repo
        self.time_service = time_service


    # ==========================================================
    # Справочники (возвращают DTO)
    # ==========================================================


    async def get_school_dictionaries(self) -> SchoolDictionariesDTO:
        """Получает справочники классов и групп за один запрос к репозиторию."""
        metadata: dict = await self.schedule_repo.get_metadata()

        classes_raw = metadata.get('classes', {})
        # Извлекаем name, приводим ключи и значения к строкам для надежности
        classes_dict = {
            str(k): str(getattr(v, 'name', v))
            for k, v in classes_raw.items()
        }

        groups_raw = metadata.get('groups', {})
        groups_dict = {
            str(k): str(v)
            for k, v in groups_raw.items()
        }

        return SchoolDictionariesDTO(classes=classes_dict, groups=groups_dict)


    async def get_classes_list(self) -> ClassListDTO:
        metadata = await self.schedule_repo.get_metadata()
        classes_raw = metadata.get('classes', {})
        classes_dict = {k: getattr(v, 'name', v) for k, v in classes_raw.items()}
        return ClassListDTO(classes=classes_dict)


    async def get_groups_list(self) -> GroupListDTO:
        """Получает список групп из репозитория и упаковывает в DTO"""
        metadata = await self.schedule_repo.get_metadata()
        groups_raw = metadata.get('groups', {})
        return GroupListDTO(groups=groups_raw)


    async def get_teachers_list(self) -> TeacherListDTO:
        metadata = await self.schedule_repo.get_metadata()
        teachers_raw = metadata.get("teachers", {})
        teachers = {
            teacher_id: getattr(teacher, "name", teacher)
            for teacher_id, teacher in teachers_raw.items()
        }
        return TeacherListDTO(teachers=teachers)
   
    @staticmethod
    def _lesson_to_dto(
        lesson: LessonInstance,
        *,
        day_permutation: bool = False,
    ) -> LessonDTO:
        return LessonDTO(
            id=lesson.id,
            lesson_num=lesson.lesson_num,
            start_time=lesson.start_time,
            end_time=lesson.end_time,
            subject_name=lesson.subject_name or "",
            room_name=lesson.room_name or "",
            is_cancelled=lesson.is_cancelled,
            is_exchange=lesson.is_exchange,
            is_extra=False,
            date_iso=lesson.date,
            
            period_id=lesson.period_id,
            group_id=lesson.group_id,
            group_name=lesson.group_name,
            class_id=lesson.class_id,
            class_name=lesson.class_name,
            teacher_id=lesson.teacher_id,
            teacher_name=lesson.teacher_name,
            is_methodological=lesson.is_methodological,

            original_subject_id=lesson.original_subject_id,
            original_subject_name=lesson.original_subject_name,
            original_teacher_id=lesson.original_teacher_id,
            original_teacher_name=lesson.original_teacher_name,
            original_room_id=lesson.original_room_id,
            original_room_name=lesson.original_room_name,
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
    # ==========================================================
    # Детекция перестановок (🔁 vs 🔀)
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

        # 2. Строим сигнатуру «Было». 
        # Если кабинета или учителя нет, поле честно отдаст None. 
        # Пустую группу нормализуем к "ALL" для страховки.
        orig_counter = Counter(
            (
                l.original_subject_id,
                l.original_room_id,
                l.original_teacher_id,
                l.original_group_id or "ALL"
            )
            for l in exchanges
        )

        # 3. Строим сигнатуру «Стало».
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
    # Детализация изменений (было → стало)
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
            lessons = await self.schedule_repo.get_lesson_instances_for_class(
                class_id=class_id,
                date_iso=date_iso,
            )
        else:
            if not teacher_id:
                raise ValueError("teacher_id required for origin='teacher'")
            lessons = await self.schedule_repo.get_lesson_instances_for_teacher(
                teacher_id=teacher_id,
                date_iso=date_iso,
            )

        changed = [
            l for l in lessons
            if l.is_exchange or l.is_cancelled
        ]
        changed.sort(key=lambda l: l.lesson_num or 99)

        # Детекция перестановок вычисляется ДО маппинга
        day_permutation = self._detect_day_permutation(changed)

        # LessonInstance → LessonDTO через единый маппер
        lesson_dtos = [
            self._lesson_to_dto(l, day_permutation=day_permutation)
            for l in changed
        ]

        return DayChangesDetailDTO(
            date_iso=date_iso,
            origin=origin,
            lessons=lesson_dtos,
        )

    # ==========================================================
    # Расписание студента (class + group + extra)
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

        lessons: List[Union[LessonDTO, Dict]] — school (LessonDTO)
        + extra (Dict).
        """
        # 1. School lessons (LessonInstance → LessonDTO)
        base_lessons: List[LessonInstance] = (
            await self.schedule_repo.get_lesson_instances_for_class(
                class_id=class_id,
                date_iso=date_iso,
            )
        )

        # 2. Фильтрация по группе
        user_groups = group_id.split(",") if group_id and group_id != "ALL" else ["ALL"]
        filtered_base: List[LessonInstance] = []

        for lesson in base_lessons:
            l_group = lesson.group_id
            subj_name = (lesson.subject_name or "").lower()
            is_nominal_tree = "труд" in subj_name or "технологи" in subj_name

            if "ALL" in user_groups or l_group == "ALL" or l_group in user_groups or is_nominal_tree:
                filtered_base.append(lesson)

        # 3. Детекция перестановок
        day_permutation = self._detect_day_permutation(filtered_base)

        # 4. LessonInstance → LessonDTO через единый маппер
        school_lessons: List[LessonDTO] = [
            self._lesson_to_dto(l, day_permutation=day_permutation)
            for l in filtered_base
        ]

        # 5. Extra lessons (Dict)
        extra_lessons: List[LessonDTO] = []
        if student_id is not None:
            date_obj = self.time_service.date_from_iso(date_iso)
            weekday = date_obj.isoweekday()
            extra_rows = await self.extra_repo.get_extra_classes_for_student(
                student_id=student_id,
                day_of_week=weekday,
            )
            extra_lessons = [
                self._map_extra_to_lesson(row, date_iso)
                for row in extra_rows
            ]

        # 6. Merge: LessonDTO + Dict
        combined: List[LessonDTO] = school_lessons + extra_lessons

        # 7. Сортировка
        def sort_key(l: LessonDTO):
            num = l.lesson_num if l.lesson_num is not None else 99
            return (l.start_time.zfill(5), num)

        combined.sort(key=sort_key)

        # 8. Обогащение групп (для school lessons)
        metadata = await self.schedule_repo.get_metadata()
        groups_dict = metadata.get("groups", {})

        for l in combined:
            if l.group_id != "ALL" and l.group_name:
                l.group_name = groups_dict.get(l.group_id, l.group_name)

        # 9. Display numbers (смены)
        self._enrich_display_numbers_dtos(
            lessons=school_lessons,
            metadata=metadata,
        )

        return DayScheduleDTO(
            date_iso=date_iso,
            lessons=combined,
            has_permutation=day_permutation,
        )


    async def get_smart_target_date(
        self,
        *,
        class_id: str,
        group_id: str,
        student_id: int | None = None,
    ) -> str:
        """
        Возвращает ближайшую дату, на которую есть ещё актуальное расписание.

        Правило:
        - если сегодня есть занятия и они ещё не завершились — вернуть сегодня;
        - если занятия сегодня закончились — искать следующий день;
        - если выходной, каникулы или пустое расписание — искать вперёд;
        - поиск ограничен 8 календарными днями.
        """
        now = self.time_service.get_now_base()
        today = now.date()

        for offset in range(8):
            candidate_date = today + timedelta(days=offset)
            candidate_iso = candidate_date.isoformat()

            day_dto = await self.get_daily_schedule_for_student(
                class_id=class_id,
                group_id=group_id,
                date_iso=candidate_iso,
                student_id=student_id,
            )

            if not day_dto.lessons:
                continue

            if candidate_date != today:
                return candidate_iso

            latest_end = max(
                (l.end_time.zfill(5) for l in day_dto.lessons),
                default="00:00",
            )

            if now.strftime("%H:%M") <= latest_end:
                return candidate_iso

        # Fallback: если кэш ещё не загружен на будущее, возвращаем сегодня.
        return today.isoformat()


    async def get_smart_week_start(self) -> str:
        """
        Возвращает понедельник текущей недели. Если сегодня воскресенье (или вечер субботы),
        возвращает понедельник следующей недели.
        """
        now = self.time_service.get_now_base()

        if now.isoweekday() == 7:  # Воскресенье -> следующая неделя
            target_date = now + timedelta(days=1)
        elif now.isoweekday() == 6 and now.hour >= 15: # Суббота после 15:00 -> следующая неделя
            target_date = now + timedelta(days=2)
        else:
            target_date = now

        monday = target_date - timedelta(days=target_date.isoweekday() - 1)
        return monday.date().isoformat()


    async def get_week_schedule_summary(
        self,
        class_id: str,
        group_id: str,
        week_start_iso: str,
        student_id: int | None = None,
    ) -> WeekSummaryDTO:
        """Собирает сводку (кол-во уроков, замен, доп. занятий) на неделю."""
        start_date = self.time_service.date_from_iso(week_start_iso)
        day_summaries = []

        for i in range(6): # Пн - Сб
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_student(
                class_id=class_id,
                group_id=group_id,
                date_iso=current_date_iso,
                student_id=student_id,
            )

            # Считаем уникальные номера основных уроков (set автоматически уберет дубли подгрупп)
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

            # Доп. занятия не имеют номеров, их считаем напрямую
            extra_count = sum(
                1
                for l in day_dto.lessons
                if l.is_extra
            )

            day_summaries.append(DaySummaryDTO(
                date_iso=current_date_iso,
                lesson_count=main_count,
                extra_count=extra_count,
                exchange_count=exchange_count,
            ))

        return WeekSummaryDTO(week_start_iso=week_start_iso, days=day_summaries)


    async def get_full_week_schedule(
        self,
        class_id: str,
        group_id: str,
        week_start_iso: str,
        student_id: int | None = None,
    ) -> FullWeekScheduleDTO:
        """Собирает полное расписание на всю неделю."""
        start_date = self.time_service.date_from_iso(week_start_iso)
        days = []
        for i in range(6):
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_student(
                class_id=class_id,
                group_id=group_id,
                date_iso=current_date_iso,
                student_id=student_id,
            )
            days.append(day_dto)
        return FullWeekScheduleDTO(week_start_iso=week_start_iso, days=days)


    # ==========================================================
    # Расписание класса (без групп, для поиска/админки)
    # ==========================================================


    async def get_daily_schedule_for_class(
        self,
        class_id: str,
        date_iso: str,
    ) -> DayScheduleDTO:
        lessons: List[LessonInstance] = (
            await self.schedule_repo.get_lesson_instances_for_class(
                class_id=class_id,
                date_iso=date_iso,
            )
        )

        day_permutation = self._detect_day_permutation(lessons)

        # Единый маппер вместо дублирования конструктора
        school_lessons: List[LessonDTO] = [
            self._lesson_to_dto(l, day_permutation=day_permutation)
            for l in lessons
        ]

        def sort_key(l: LessonDTO):
            return (l.start_time.zfill(5), l.lesson_num or 99)

        combined = sorted(school_lessons, key=sort_key)

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


    async def get_full_week_schedule_for_class(
        self,
        class_id: str,
        week_start_iso: str,
    ) -> FullWeekScheduleDTO:
        start_date = self.time_service.date_from_iso(week_start_iso)
        days = []
        for i in range(6):
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_class(
                class_id=class_id,
                date_iso=current_date_iso,
            )
            days.append(day_dto)
        return FullWeekScheduleDTO(week_start_iso=week_start_iso, days=days)


    # ==========================================================
    # Расписание учителя
    # ==========================================================


    async def get_daily_schedule_for_teacher(
        self,
        teacher_id: str,
        date_iso: str,
    ) -> DayScheduleDTO:

        lessons: List[LessonInstance] = (
            await self.schedule_repo.get_lesson_instances_for_teacher(
                teacher_id=teacher_id,
                date_iso=date_iso,
            )
        )
        day_permutation = self._detect_day_permutation(lessons)

        # Единый маппер вместо дублирования конструктора
        school_lessons: List[LessonDTO] = [
            self._lesson_to_dto(l, day_permutation=day_permutation)
            for l in lessons
        ]

        def sort_key(l: LessonDTO):
            return (l.start_time.zfill(5), l.lesson_num or 99)

        combined = sorted(
            school_lessons,
            key=lambda lesson: (
                lesson.start_time.zfill(5),
                lesson.lesson_num or 99,
            ),
        )

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

    async def get_full_week_schedule_for_teacher(
        self,
        teacher_id: str,
        week_start_iso: str,
    ) -> FullWeekScheduleDTO:
        start_date = self.time_service.date_from_iso(week_start_iso)
        days = []
        for i in range(6):
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_teacher(
                teacher_id=teacher_id,
                date_iso=current_date_iso,
            )
            days.append(day_dto)
        return FullWeekScheduleDTO(week_start_iso=week_start_iso, days=days)


    async def get_smart_teacher_target_date(
        self,
        *,
        teacher_id: str,
    ) -> str:
        """
        Возвращает ближайшую дату, когда у учителя есть занятия.

        Алгоритм:
        - сегодня, если есть будущие/текущие уроки;
        - иначе ближайший день с расписанием;
        - поиск ограничен восемью календарными днями.
        """
        now = self.time_service.get_now_base()
        today = now.date()
        logger.info(f"Тест Smart date: now={now} today={today}")  # ← ДОБАВИТЬ
        for offset in range(8):
            candidate_date = today + timedelta(days=offset)
            candidate_iso = candidate_date.isoformat()
            logger.info(f"Тест Checking date: {candidate_iso}")  # ← ДОБАВИТЬ
            day_dto = await self.get_daily_schedule_for_teacher(
                teacher_id=teacher_id,
                date_iso=candidate_iso,
            )

            if not day_dto.lessons:
                logger.info(f"Тест  → No lessons, continue")  # ← ДОБАВИТЬ
                continue

            if candidate_date != today:
                logger.info(f"Тест  → Future date, return")  # ← ДОБАВИТЬ
                return candidate_iso

            latest_end_time = max(
                (
                    lesson.end_time.zfill(5)
                    for lesson in day_dto.lessons
                ),
                default="00:00",
            )

            if now.strftime("%H:%M") <= latest_end_time:
                return candidate_iso

        return today.isoformat()



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

    # ==========================================================
    # Вспомогательные методы
    # ==========================================================


    def _map_extra_to_lesson(
        self,
        row: Dict[str, Any],
        date_iso: str,
    ) -> LessonDTO:
        """
        Доп. занятие (extra_classes) → LessonDTO с is_extra=True.
        """
        return LessonDTO(
            id=f"extra-{row['id']}",
            lesson_num=None,
            display_num="•",
            start_time=row["time_start"],
            end_time=row["time_end"],
            subject_name=row["title"],
            room_name=row.get("location") or "—",
            is_cancelled=False,
            is_exchange=False,
            is_extra=True,
            is_methodological=False,
            class_id=None,
            group_id="ALL",
            group_name=None,
            date_iso=date_iso,
            # student_id из старого словаря удалено — рендерер его не использует; если понадобится для диагностики, вернём отдельным полем осознанно.
        )

    @staticmethod
    def _enrich_display_numbers_dtos(
        lessons: List[LessonDTO],
        metadata: dict,
    ) -> None:
        """
        Обогащает LessonDTO.display_num с учётом 2 смены.

        period_id берётся из LessonDTO.period_id.
        metadata.class_shift[period_id][class_id] = shift_start.
        """
        class_shifts = metadata.get("class_shift", {})
        second_relative = metadata.get("second_relative", False)

        # Группируем уроки по period_id и class_id
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