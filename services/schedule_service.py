# services/schedule_service.py
#
# РЕФАКТОРИНГ v2 — «тонкий фасад» по образцу NotificationService:
#
# Публичный метод = один экран бота, 3–10 строк:
#   выборка (repo) -> сборка (_assemble_day_schedule) -> DTO.
#
# Ключевые оптимизации против v1:
# 1. Smart-date возвращает ГОТОВЫЙ DayScheduleDTO: проба дней идёт по
#    сырым LessonInstance (без Counter/mapper/enrich), полный конвейер
#    запускается один раз — для выбранного дня. Хендлеру больше не нужно
#    повторно запрашивать день на рендер.
# 2. Метаданные школы кешируются репозиторием в памяти: get_metadata()
#    не делает SQL после первого обращения (и после инвалидации при
#    смене NIKA-ревизии).
# 3. get_teacher_name/get_class_name — прямой lookup по метаданным
#    с параметром fallback, без построения полного списка.
# 4. Недельные сводки и полные недели — единые сборщики через
#    DayFetcher-замыкания.
#
# Архитектурные правила:
# - сервис не делает dict-запросов и не знает структуру NIKA;
# - вход: LessonInstance/SchoolMetadata, выход: только DTO;
# - лишние обращения к БД исключены: один экран = минимум запросов.

from collections import Counter
from datetime import datetime, time, timedelta
from typing import Awaitable, Callable, List, Literal, Optional
import logging, re

from core.mappers.lesson_mapper import LessonMapper
from core.mappers.metadata_mapper import MetadataMapper
from core.models.domain import LessonInstance
from core.models.dto import (
    ClassListDTO,
    DayChangesDetailDTO,
    DayScheduleDTO,
    DaySummaryDTO,
    DisplayNumbersDTO,
    ExtraClassItemDTO,
    FullWeekScheduleDTO,
    GroupListDTO,
    LessonDTO,
    NikaSourceHealthDTO,
    SchoolDictionariesDTO,
    TeacherListDTO,
    WeekSummaryDTO, RoomListDTO, FreeRoomsStatusDTO
)
from core.models.metadata import SchoolMetadata
from core.repository.schedule_repository import ScheduleRepository
from services.extra_classes_service import ExtraClassesService
from services.time_service import TimeService

logger = logging.getLogger(__name__)

ScheduleOrigin = Literal["class", "teacher"]
DayFetcher = Callable[[str], Awaitable[DayScheduleDTO]]

SMART_DATE_HORIZON_DAYS = 8


class ScheduleService:
    """Тонкий фасад расписания: repo -> DTO, без сырых данных и dict."""

    def __init__(
        self,
        schedule_repo: ScheduleRepository,
        time_service: TimeService,
        extra_classes_service: ExtraClassesService,
    ) -> None:
        self.schedule_repo = schedule_repo
        self.time_service = time_service
        self.extra_classes_service = extra_classes_service

    # ==========================================================
    # Чистые утилиты (без I/O)
    # ==========================================================

    @staticmethod
    def _parse_hhmm(value: str) -> time:
        hour, minute = map(int, value.split(":"))
        return time(hour, minute)

    @staticmethod
    def _sort_key(lesson: LessonDTO):
        num = lesson.lesson_num if lesson.lesson_num is not None else 999
        return (ScheduleService._parse_hhmm(lesson.start_time), num)

    @staticmethod
    def detect_day_permutation(lessons: List[LessonInstance]) -> bool:
        """
        True, если изменения дня — простая перестановка (🔁).

        Публичный API.
        Сравнивает мультимножества 3D-сигнатур «было»/«стало».
        Группа исключена из сигнатуры, чтобы обмен кабинетами/учителями 
        между подгруппами корректно считался перестановкой.
        Все пустые значения безопасно приводятся к None (без хаков).
        """
        exchanges = [
            l for l in lessons
            if l.is_exchange and not l.is_cancelled
        ]
        if len(exchanges) < 2:
            return False

        orig_counter = Counter(
            (
                l.original_subject_id or None,
                l.original_room_id or None,
                l.original_teacher_id or None,
            )
            for l in exchanges
        )
        curr_counter = Counter(
            (
                l.subject_id or None,
                l.room_id or None,
                l.teacher_id or None,
            )
            for l in exchanges
        )
        return orig_counter == curr_counter

    @staticmethod
    def get_equivalent_groups(group_id: str, groups_dict: dict) -> set[str]:
        """Умный алиас: находит все ID групп, в которых фигурирует та же цифра (Группа 1 == 1 группа)."""
        if not group_id or group_id == "ALL":
            return {"ALL"}
        equivs = {group_id}
        name = groups_dict.get(group_id, str(group_id))
        m = re.search(r'\d+', name)
        if m:
            digit = m.group(0)
            for k, v in groups_dict.items():
                if re.search(rf'\b{digit}\b', str(v)):
                    equivs.add(str(k))
        return equivs

    @staticmethod
    def _filter_by_groups(
        lessons: List['LessonInstance'],
        group_id: str,
        groups_dict: dict,
    ) -> List['LessonInstance']:
        """Фильтрует уроки класса по группам профиля ученика с учетом умных алиасов и агрегации Труда."""
        user_groups = [g.strip() for g in group_id.split(",") if g.strip()] if group_id and group_id != "ALL" else ["ALL"]
        
        user_equivs = set()
        for ug in user_groups:
            user_equivs.update(ScheduleService.get_equivalent_groups(ug, groups_dict))
            
        filtered = []
        for lesson in lessons:
            lesson_group_id = str(lesson.group_id).strip() if lesson.group_id else "ALL"
            subj_name = (lesson.subject_name or "").lower()
            
            # Делаем исключение для Труда/Технологии: 
            # пропускаем все подгруппы этого предмета для склейки в рендерере
            is_trud = "труд" in subj_name or "технологи" in subj_name
            
            if "ALL" in user_groups or lesson_group_id == "ALL" or is_trud:
                filtered.append(lesson)
            else:
                lesson_equivs = ScheduleService.get_equivalent_groups(lesson_group_id, groups_dict)
                if user_equivs & lesson_equivs:
                    filtered.append(lesson)
                    
        return filtered
    
    @staticmethod
    def _map_extra_to_lesson(
        extra: ExtraClassItemDTO,
        date_iso: str,
    ) -> LessonDTO:
        """Доп. занятие -> LessonDTO (is_extra=True, display_num='•')."""
        return LessonDTO(
            id=f"extra-{extra.id}",
            date_iso=date_iso,
            display_num="•",
            start_time=extra.time_start,
            end_time=extra.time_end,
            subject_name=extra.title,
            room_name=extra.location or "—",
            is_extra=True,
            group_id="ALL",
            group_name="Весь класс",
        )

    @staticmethod
    def _has_actual_resource_lessons(
        lessons: List[LessonInstance],
    ) -> bool:
        """
        Реальный lesson — любой non-window LessonInstance.

        Cancelled lesson тоже считается реальным slot:
        teacher должен увидеть отмену, а не ложное «Свободное время».

        NIKA window с subject_name='нет занятий' и is_window=True
        не считается занятием сам по себе.
        """
        return any(not lesson.is_window for lesson in lessons)


    @staticmethod
    def _complete_resource_timeline(
        lessons: List[LessonDTO],
        *,
        metadata: SchoolMetadata,
        date_iso: str,
        resource_key: str,
        window_label: str,
    ) -> List[LessonDTO]:
        """
        Достраивает timeline teacher/room до всех configured school slots.

        Rules:
        - Если нет ни одного actual lesson — возвращает [].
        - Existing NIKA windows сохраняются.
        - Missing slots становятся synthetic LessonDTO(is_window=True).
        - Actual lesson, including cancelled/methodological, занимает slot.
        - Multi-group / simultaneous teacher entries одного lesson_num
          остаются одним занятым физическим slot.
        """
        actual_lessons = [
            lesson
            for lesson in lessons
            if not lesson.is_extra and not lesson.is_window
        ]

        # Teacher without lessons = day off.
        # Room without lessons = completely free day.
        # Не генерируем 12 пустых cards подряд.
        if not actual_lessons:
            return []

        completed = list(lessons)

        existing_numbers = {
            lesson.lesson_num
            for lesson in completed
            if lesson.lesson_num is not None
        }

        # Existing NIKA-generated window gets context-aware label.
        for lesson in completed:
            if lesson.is_window:
                lesson.window_label = window_label

        for lesson_num, lesson_time in metadata.lesson_times.items():
            if lesson_num in existing_numbers:
                continue

            completed.append(
                LessonDTO(
                    id=(
                        f"window-{resource_key}-"
                        f"{date_iso}-{lesson_num}"
                    ),
                    date_iso=date_iso,
                    lesson_num=lesson_num,
                    display_num=str(lesson_num),
                    start_time=lesson_time.start_time,
                    end_time=lesson_time.end_time,
                    subject_name="",
                    room_name="",
                    group_id="ALL",
                    group_name="Весь класс",
                    is_window=True,
                    window_label=window_label,
                )
            )

        return completed
    
    @staticmethod
    def _enrich_display_numbers_dtos(
        lessons: List[LessonDTO],
        metadata: SchoolMetadata,
        origin: str = "student",
    ) -> None:
        """
        Обогащает LessonDTO.display_num с учётом 2 смены.

        metadata.class_shift[period_id][class_id] = shift_start:
        уроки до shift_start идут «как есть» (w_flag), последующие
        сдвигаются на shift_start-1 и помечаются '*'.
        """
        if origin in {"teacher", "room"}:
            for lesson in lessons:
                lesson.display_num = (
                    str(lesson.lesson_num)
                    if lesson.lesson_num is not None
                    else "•"
                )
            return
        class_shifts = metadata.class_shift

        groups: dict[tuple[str, str], List[LessonDTO]] = {}
        for l in lessons:
            if not l.is_methodological and l.lesson_num:
                p_id = l.period_id or l.class_id or "default"
                c_id = l.class_id or "default"
                groups.setdefault((p_id, c_id), []).append(l)

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
                    # Web и bot UI показывают понятный relative second-shift number
                    # without NIKA technical marker "*".
                    l.display_num = str(v)
                else:
                    l.display_num = str(m)

        for l in lessons:
            if l.display_num is None:
                l.display_num = "•"

    @staticmethod
    def _summarize_day(
        date_iso: str,
        day_dto: DayScheduleDTO,
        *,
        count_distinct_nums: bool,
    ) -> DaySummaryDTO:
        """
        Сводка для week view.

        lesson_count:
        - учитывает реальные школьные уроки;
        - не учитывает extra classes и synthetic/NIKA windows;
        - не учитывает отменённые уроки.

        exchange_count:
        - считает changed / added / cancelled schedule slots;
        - для class/room summary считает physical slots;
        - для teacher summary считает entries.
        """

        schedule_lessons = [
            lesson
            for lesson in day_dto.lessons
            if not lesson.is_extra
            and not lesson.is_window
        ]

        active_lessons = [
            lesson
            for lesson in schedule_lessons
            if not lesson.is_cancelled
        ]

        changed_lessons = [
            lesson
            for lesson in schedule_lessons
            if lesson.is_exchange or lesson.is_cancelled
        ]

        if count_distinct_nums:
            lesson_count = len(
                {
                    lesson.lesson_num
                    for lesson in active_lessons
                    if lesson.lesson_num is not None
                }
            )

            exchange_count = len(
                {
                    lesson.lesson_num
                    for lesson in changed_lessons
                    if lesson.lesson_num is not None
                }
            )
        else:
            lesson_count = len(active_lessons)
            exchange_count = len(changed_lessons)

        extra_count = sum(
            1
            for lesson in day_dto.lessons
            if lesson.is_extra
        )

        return DaySummaryDTO(
            date_iso=date_iso,
            lesson_count=lesson_count,
            extra_count=extra_count,
            exchange_count=exchange_count,
        )

    # ==========================================================
    # Сборка дня — единственная точка конвейера DTO
    # ==========================================================

    async def _assemble_day_schedule(
        self,
        *,
        lessons: List[LessonInstance],
        date_iso: str,
        extra_items: Optional[List[ExtraClassItemDTO]] = None,
        origin: Literal["class", "teacher", "student"] = "student",
        class_id: Optional[str] = None,
        group_id: Optional[str] = None,
        resource_key: Optional[str] = None,
        window_label: Optional[str] = None,
    ) -> DayScheduleDTO:
        """
        LessonInstance[] -> DayScheduleDTO:
        permutation -> map -> sort -> enrich display_num.

        Полный конвейер запускается ровно один раз на день.
        """
        day_permutation = self.detect_day_permutation(lessons)

        metadata = await self.schedule_repo.get_metadata()

        dtos: List[LessonDTO] = LessonMapper.to_dto_list(
            lessons,
            day_permutation=day_permutation,
        )

        if extra_items:
            dtos += [
                self._map_extra_to_lesson(extra, date_iso)
                for extra in extra_items
            ]

        if window_label is not None and resource_key is not None:
            dtos = self._complete_resource_timeline(
                dtos,
                metadata=metadata,
                date_iso=date_iso,
                resource_key=resource_key,
                window_label=window_label,
            )

        dtos.sort(key=self._sort_key)

        self._enrich_display_numbers_dtos(
            dtos,
            metadata,
            origin=origin,
        )

        # Извлекаем красивые названия для заголовка рендерера
        class_name = None
        group_name = None
        if origin != "teacher":
            if class_id:
                class_obj = metadata.classes.get(class_id)
                class_name = class_obj.name if class_obj else class_id
            if group_id and group_id != "ALL":
                names = [metadata.groups.get(g.strip(), f"Группа {g.strip()}") for g in group_id.split(",") if g.strip()]
                group_name = ", ".join(names)

        return DayScheduleDTO(
            date_iso=date_iso,
            lessons=dtos,
            has_permutation=day_permutation,
            origin=origin,
            class_name=class_name,
            group_name=group_name,
        )
    async def _fetch_extra_items(
        self,
        student_id: Optional[int],
        date_iso: str,
    ) -> List[ExtraClassItemDTO]:
        """Доп. занятия ученика на дату (сырые items, без маппинга)."""
        if student_id is None:
            return []

        weekday = self.time_service.date_from_iso(date_iso).isoweekday()
        return await self.extra_classes_service.get_extra_classes_for_student(
            student_id=student_id,
            day_of_week=weekday,
        )

    async def _fetch_lessons_by_origin(
        self,
        *,
        date_iso: str,
        origin: ScheduleOrigin,
        class_id: Optional[str] = None,
        teacher_id: Optional[str] = None,
    ) -> List[LessonInstance]:
        """Единая точка выборки по origin (class | teacher)."""
        if origin == "class":
            if not class_id:
                raise ValueError("class_id required for origin='class'")
            return await self.schedule_repo.get_lessons_for_class(
                class_id=class_id,
                date_iso=date_iso,
            )
        if not teacher_id:
            raise ValueError("teacher_id required for origin='teacher'")
        return await self.schedule_repo.get_lessons_for_teacher(
            teacher_id=teacher_id,
            date_iso=date_iso,
        )

    # ==========================================================
    # Публичный API: расписание на день
    # ==========================================================

    async def get_daily_schedule_for_student(
        self,
        *,
        class_id: str,
        group_id: str,
        date_iso: str,
        student_id: int | None = None,
    ) -> DayScheduleDTO:
        """Расписание student profile: школа (по группам) + доп. занятия."""
        base_lessons = await self.schedule_repo.get_lessons_for_class(class_id=class_id, date_iso=date_iso)
        extra_items = await self._fetch_extra_items(student_id, date_iso)
        metadata = await self.schedule_repo.get_metadata()

        return await self._assemble_day_schedule(
            lessons=self._filter_by_groups(base_lessons, group_id, metadata.groups),
            date_iso=date_iso, extra_items=extra_items, origin="student", class_id=class_id, group_id=group_id
        )

    async def get_daily_schedule_for_class(
        self, class_id: str, date_iso: str,
    ) -> DayScheduleDTO:
        """Расписание класса на день (все группы)."""
        return await self._assemble_day_schedule(
            lessons=await self.schedule_repo.get_lessons_for_class(class_id=class_id, date_iso=date_iso),
            date_iso=date_iso, origin="class", class_id=class_id
        )

    async def get_daily_schedule_for_teacher(
        self, teacher_id: str, date_iso: str,
    ) -> DayScheduleDTO:
        """
        Расписание учителя на день.
        Если у учителя есть хотя бы один actual lesson, service достраивает
        весь configured school timeline и добавляет windows.
        """
        lessons = await self.schedule_repo.get_lessons_for_teacher(
            teacher_id=teacher_id,
            date_iso=date_iso,
        )

        return await self._assemble_day_schedule(
            lessons=lessons,
            date_iso=date_iso,
            origin="teacher",
            resource_key=f"teacher-{teacher_id}",
            window_label="Свободное время",
        )
        
    async def get_day_changes_detail(
        self,
        *,
        class_id: Optional[str] = None,
        teacher_id: Optional[str] = None,
        date_iso: str,
        origin: ScheduleOrigin = "class",
    ) -> DayChangesDetailDTO:
        """Детализация изменений «было -> стало» за дату."""
        lessons = await self._fetch_lessons_by_origin(
            date_iso=date_iso,
            origin=origin,
            class_id=class_id,
            teacher_id=teacher_id,
        )

        # 1. Маппим ВСЕ уроки дня, чтобы обогатитель (w_flag) увидел 
        # реальное начало дня (например, 6-й урок), даже если он не менялся.
        day_permutation = self.detect_day_permutation(lessons)
        all_lesson_dtos = LessonMapper.to_dto_list(
            lessons, day_permutation=day_permutation
        )

        # 2. Вычисляем смены и номера для полного дня
        metadata = await self.schedule_repo.get_metadata()
        self._enrich_display_numbers_dtos(all_lesson_dtos, metadata, origin=origin)

        # 3. Только ТЕПЕРЬ отфильтровываем измененные уроки 
        # (они уже имеют правильный display_num без ложных звездочек)
        changed_dtos = sorted(
            (dto for dto in all_lesson_dtos if dto.is_exchange or dto.is_cancelled),
            key=lambda dto: dto.lesson_num or 99,
        )

        # === Обогащаем названия классов для учителя ===
        if origin == "teacher":
            for dto in changed_dtos:
                # Текущий класс
                if dto.class_id:
                    cls_obj = metadata.classes.get(str(dto.class_id))
                    dto.class_name = cls_obj.name if cls_obj else str(dto.class_id)
                
                # Оригинальный класс (на случай, если учителю перекинули урок)
                if dto.original_class_id:
                    orig_cls_obj = metadata.classes.get(str(dto.original_class_id))
                    dto.original_class_name = orig_cls_obj.name if orig_cls_obj else str(dto.original_class_id)
        # ====================================================

        return DayChangesDetailDTO(
            date_iso=date_iso,
            origin=origin,
            lessons=changed_dtos,
        )

    async def get_display_numbers_for_class_day(
        self,
        *,
        class_id: str,
        date_iso: str,
    ) -> DisplayNumbersDTO:
        """Номера уроков с учётом 2 смены (DTO, не dict)."""
        lessons = await self.schedule_repo.get_lessons_for_class(
            class_id=class_id,
            date_iso=date_iso,
        )

        lesson_dtos = LessonMapper.to_dto_list(
            lessons,
            day_permutation=self.detect_day_permutation(lessons),
        )

        metadata = await self.schedule_repo.get_metadata()
        self._enrich_display_numbers_dtos(lesson_dtos, metadata)

        return DisplayNumbersDTO(
            date_iso=date_iso,
            class_id=class_id,
            by_lesson_num={
                lesson.lesson_num: (
                    lesson.display_num
                    or str(lesson.lesson_num)
                )
                for lesson in lesson_dtos
                if lesson.lesson_num is not None
            },
        )

    # ==========================================================
    # Поиск кабинетов
    # ==========================================================

    async def get_rooms_list(self) -> RoomListDTO:
        """Справочник кабинетов (DTO для UI)."""
        metadata = await self.schedule_repo.get_metadata()
        rooms_dict = {str(k): room_obj.name for k, room_obj in metadata.rooms.items()}
        return RoomListDTO(rooms=rooms_dict)

    async def get_room_name(self, room_id: str, fallback: str = "Кабинет") -> str:
        """Безопасное получение имени кабинета."""
        metadata = await self.schedule_repo.get_metadata()
        room_obj = metadata.rooms.get(str(room_id))
        return room_obj.name if room_obj else fallback

    async def get_currently_free_rooms(self) -> tuple['FreeRoomsStatusDTO', dict[str, str]]:
            """
            Вычисляет свободные кабинеты на текущую минуту ИЛИ на следующий урок.
            Возвращает сухие данные: (FreeRoomsStatusDTO, dict[room_id, room_name]).
            """
            now = self.time_service.get_now_base()
            date_iso = now.date().isoformat()
            current_time_obj = now.time()

            metadata = await self.schedule_repo.get_metadata()
            lessons_today = await self.schedule_repo.get_active_lessons_for_date(date_iso)
            
            # 1. Собираем уникальные интервалы уроков
            slots_map: dict[tuple[str, str], int] = {}
            for lesson in lessons_today:
                if not lesson.start_time or not lesson.end_time:
                    continue
                slot = (
                    lesson.start_time,
                    lesson.end_time,
                )
                if slot not in slots_map and lesson.lesson_num is not None:
                    slots_map[slot] = lesson.lesson_num

            parsed_slots: list[
                tuple[time, time, str, str, int | None]
            ] = []
            for (start_str, end_str), lesson_num in slots_map.items():
                try:
                    start_time_obj = self._parse_hhmm(start_str)
                    end_time_obj = self._parse_hhmm(end_str)
                except ValueError:
                    continue
                if end_time_obj <= start_time_obj:
                    continue
                parsed_slots.append(
                    (
                        start_time_obj,
                        end_time_obj,
                        start_str,
                        end_str,
                        lesson_num,
                    )
                )
                
            parsed_slots.sort(key=lambda item: item[0])
            
            # 2. Ищем целевой слот
            occupancy_slot: tuple[str, str] | None = None
            target_num: int | None = None
            status_start_time: str | None = None
            status_end_time: str | None = None
            is_break = False
            is_finished = False
            
            if not parsed_slots:
                # Нет активных уроков на дату: школа закрыта.
                pass
            else:
                first_start, _, _, _, _ = parsed_slots[0]
                _, last_end, _, _, _ = parsed_slots[-1]
                if current_time_obj < first_start:
                    # До первого урока.
                    pass
                elif current_time_obj >= last_end:
                    # После последнего урока.
                    is_finished = True
                else:
                    for index, (
                        start_time_obj,
                        end_time_obj,
                        start_str,
                        end_str,
                        lesson_num,
                    ) in enumerate(parsed_slots):
                        if start_time_obj <= current_time_obj < end_time_obj:
                            # Сейчас идёт урок.
                            occupancy_slot = (start_str, end_str)
                            target_num = lesson_num
                            status_start_time = start_str
                            status_end_time = end_str
                            break
                        if index + 1 >= len(parsed_slots):
                            continue
                        (
                            next_start_time_obj,
                            _,
                            next_start_str,
                            _,
                            next_lesson_num,
                        ) = parsed_slots[index + 1]
                        if end_time_obj <= current_time_obj < next_start_time_obj:
                            # Перемена: кабинеты считаем свободными до следующего урока,
                            # но пользователю отображаем реальные границы перемены.
                            occupancy_slot = (
                                next_start_str,
                                parsed_slots[index + 1][3],
                            )
                            target_num = next_lesson_num
                            status_start_time = end_str
                            status_end_time = next_start_str
                            is_break = True
                            break

            # 3. Вычисляем занятые кабинеты
            occupied_ids = set()
            if occupancy_slot:
                target_start_obj = self._parse_hhmm(occupancy_slot[0])
                target_end_obj = self._parse_hhmm(occupancy_slot[1])
                for lesson in lessons_today:
                    if not lesson.start_time or not lesson.end_time:
                        continue
                    try:
                        lesson_start = self._parse_hhmm(lesson.start_time)
                        lesson_end = self._parse_hhmm(lesson.end_time)
                    except ValueError:
                        continue
                    if (
                        lesson_start < target_end_obj
                        and lesson_end > target_start_obj
                        and lesson.room_id
                    ):
                        occupied_ids.add(str(lesson.room_id))

            # 4. Формируем DTO состояния
            status_dto = FreeRoomsStatusDTO(
                current_time_str=now.strftime("%H:%M"),
                is_finished=is_finished,
                is_break=is_break,
                target_num=target_num,
                start_time=status_start_time,
                end_time=status_end_time,
            )

            free_rooms = {}
            for r_id, room_obj in metadata.rooms.items():
                if str(r_id) not in occupied_ids and room_obj.name.strip() and room_obj.name != "—":
                    free_rooms[str(r_id)] = room_obj.name

            sorted_free_rooms = {k: v for k, v in sorted(free_rooms.items(), key=lambda item: item[1])}
            return status_dto, sorted_free_rooms
    
    async def get_daily_schedule_for_room(self, room_id: str, date_iso: str) -> DayScheduleDTO:
        """Сборка расписания кабинета в чистый DTO с дедубликацией подгрупп."""
        lessons = await self.schedule_repo.get_lessons_for_room(room_id, date_iso)
        day_permutation = self.detect_day_permutation(lessons)

        # 1. Получаем сырые DTO
        raw_dtos = LessonMapper.to_dto_list(lessons, day_permutation=day_permutation)

        # 2. Дедубликация: сливаем подгруппы одного класса (без учета названия группы)
        unique_dtos = []
        seen = set()
        for dto in raw_dtos:
            # Уникальная сигнатура урока в кабинете
            sig = (dto.start_time, dto.end_time, dto.subject_name, dto.class_name, dto.teacher_name)
            if sig not in seen:
                seen.add(sig)
                unique_dtos.append(dto)

        # 3. Metadata нужен для complete room timeline.
        metadata = await self.schedule_repo.get_metadata()

        # 4. Если кабинет был занят хотя бы раз, добавляем окна
        # для всех missing configured school slots.
        unique_dtos = self._complete_resource_timeline(
            unique_dtos,
            metadata=metadata,
            date_iso=date_iso,
            resource_key=f"room-{room_id}",
            window_label="Кабинет свободен",
        )

        # 5. Сортировка complete timeline.
        unique_dtos.sort(key=self._sort_key)

        # 6. Кабинет всегда использует absolute physical numbering.
        self._enrich_display_numbers_dtos(
            unique_dtos,
            metadata,
            origin="room",
        )

        # Безопасное получение названия кабинета
        room_obj = metadata.rooms.get(str(room_id))
        room_name = room_obj.name if room_obj else str(room_id)

        return DayScheduleDTO(
            date_iso=date_iso,
            lessons=unique_dtos,
            has_permutation=day_permutation,
            origin="room",
            class_name=room_name,
        )

    # ==========================================================
    # Smart date: возвращает ГОТОВЫЙ день (без повторного запроса)
    # ==========================================================

    async def get_smart_day_schedule_for_student(
        self,
        *,
        class_id: str,
        group_id: str,
        student_id: int | None = None,
    ) -> DayScheduleDTO:
        async def fetch_day(date_iso: str) -> DayScheduleDTO:
            return await self.get_daily_schedule_for_student(
                class_id=class_id,
                group_id=group_id,
                date_iso=date_iso,
                student_id=student_id,
            )

        return await self._resolve_smart_day(fetch_day)

    async def get_smart_target_date(
        self,
        *,
        class_id: str,
        group_id: str,
        student_id: int | None = None,
    ) -> str:
        """Совместимость: только дата (день собирается один раз)."""
        return (
            await self.get_smart_day_schedule_for_student(
                class_id=class_id,
                group_id=group_id,
                student_id=student_id,
            )
        ).date_iso

    async def get_smart_teacher_target_date(self, *, teacher_id: str) -> str:
        """Совместимость: только дата."""
        return (
            await self.get_smart_day_schedule_for_teacher(
                teacher_id=teacher_id,
            )
        ).date_iso
        
    async def get_smart_day_schedule_for_teacher(
        self,
        *,
        teacher_id: str,
    ) -> DayScheduleDTO:
        async def fetch_day(date_iso: str) -> DayScheduleDTO:
            return await self.get_daily_schedule_for_teacher(
                teacher_id=teacher_id,
                date_iso=date_iso,
            )

        return await self._resolve_smart_day(fetch_day)


    async def get_smart_class_target_date(
        self,
        class_id: str,
    ) -> str:
        async def fetch_day(date_iso: str) -> DayScheduleDTO:
            return await self.get_daily_schedule_for_class(
                class_id=class_id,
                date_iso=date_iso,
            )

        dto = await self._resolve_smart_day(fetch_day)
        return dto.date_iso

    async def get_smart_room_target_date(
        self,
        room_id: str,
    ) -> str:
        async def fetch_day(date_iso: str) -> DayScheduleDTO:
            return await self.get_daily_schedule_for_room(
                room_id=room_id,
                date_iso=date_iso,
            )

        dto = await self._resolve_smart_day(fetch_day)
        return dto.date_iso

    async def get_smart_week_start(self) -> str:
        """
        Понедельник текущей недели. Воскресенье (или суббота после
        15:00) -> понедельник следующей недели.
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

    @staticmethod
    def _has_real_activities(
        day_dto: DayScheduleDTO,
    ) -> bool:
        """
        Есть ли на дату реальное занятие.
        Используется только для Sunday policy.
        Окна, методические слоты и отменённые уроки не удерживают
        personal/school smart opening на воскресенье.
        """
        return any(
            not lesson.is_window
            and not lesson.is_methodological
            and not lesson.is_cancelled
            for lesson in day_dto.lessons
        )

    @staticmethod
    def _is_day_finished_for_target(
        day_dto: DayScheduleDTO,
        *,
        now_time: time,
    ) -> bool:
        """
        True только если сегодня есть реальные занятия и последнее из них
        уже закончилось.
        Пустой будний день не переключает пользователя вперёд.
        """
        end_times: list[time] = []

        for lesson in day_dto.lessons:
            if getattr(lesson, 'is_window', False):
                continue
            if lesson.is_methodological:
                continue
            if lesson.is_cancelled:
                continue
            if not lesson.end_time:
                continue

            try:
                end_times.append(
                    ScheduleService._parse_hhmm(lesson.end_time)
                )
            except ValueError:
                continue

        return bool(end_times) and now_time >= max(end_times)

    async def _resolve_sunday_policy(
        self,
        *,
        candidate_dto: DayScheduleDTO,
        fetch_day, # Type hint is tricky here due to circular dependencies/generics, keeping it generic or using a Callable if defined. Assuming DayFetcher is defined elsewhere or using Callable[[str], Awaitable[DayScheduleDTO]]
    ) -> DayScheduleDTO:
        """
        Только smart/default opening policy.
        Explicit /day/{date} routes сюда не вызывают.
        """
        candidate_date = self.time_service.date_from_iso(
            candidate_dto.date_iso
        )

        if candidate_date.isoweekday() != 7:
            return candidate_dto

        if self._has_real_activities(candidate_dto):
            return candidate_dto

        monday_iso = (
            candidate_date + timedelta(days=1)
        ).isoformat()

        return await fetch_day(monday_iso)

    async def _resolve_smart_day(
        self,
        fetch_day: DayFetcher,
    ) -> DayScheduleDTO:
        """
        Общая smart-date policy.

        Только для default opening.
        Exact date routes никогда не используют этот метод.
        """
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()

        today_dto = await fetch_day(today_iso)

        if self._is_day_finished_for_target(
            today_dto,
            now_time=now.time(),
        ):
            tomorrow_iso = (
                now.date() + timedelta(days=1)
            ).isoformat()

            candidate_dto = await fetch_day(tomorrow_iso)
        else:
            candidate_dto = today_dto

        return await self._resolve_sunday_policy(
            candidate_dto=candidate_dto,
            fetch_day=fetch_day,
        )
    # ==========================================================
    # Неделя: полные расписания и сводные
    # ==========================================================

    async def _build_week_schedule(
        self,
        get_daily_schedule: DayFetcher,
        week_start_iso: str,
    ) -> FullWeekScheduleDTO:
        start_date = self.time_service.date_from_iso(week_start_iso)
        days = []
        for i in range(6):
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            days.append(await get_daily_schedule(current_date_iso))
        return FullWeekScheduleDTO(week_start_iso=week_start_iso, days=days)

    async def get_full_week_schedule(
        self,
        class_id: str,
        group_id: str,
        week_start_iso: str,
        student_id: int | None = None,
    ) -> FullWeekScheduleDTO:
        """Полное расписание student profile на неделю."""
        async def get_daily(date_iso: str) -> DayScheduleDTO:
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
        """Полное расписание класса на неделю."""
        async def get_daily(date_iso: str) -> DayScheduleDTO:
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
        """Полное расписание учителя на неделю."""
        async def get_daily(date_iso: str) -> DayScheduleDTO:
            return await self.get_daily_schedule_for_teacher(
                teacher_id=teacher_id,
                date_iso=date_iso,
            )
        return await self._build_week_schedule(get_daily, week_start_iso)

    async def _build_week_summary(
        self,
        get_daily_schedule: DayFetcher,
        week_start_iso: str,
        *,
        count_distinct_nums: bool,
    ) -> WeekSummaryDTO:
        start_date = self.time_service.date_from_iso(week_start_iso)
        days = []
        for i in range(6):
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await get_daily_schedule(current_date_iso)
            days.append(
                self._summarize_day(
                    current_date_iso,
                    day_dto,
                    count_distinct_nums=count_distinct_nums,
                )
            )
        return WeekSummaryDTO(week_start_iso=week_start_iso, days=days)

    async def get_week_schedule_summary(
        self,
        class_id: str,
        group_id: str,
        week_start_iso: str,
        student_id: int | None = None,
    ) -> WeekSummaryDTO:
        """Сводка недели student profile (уроки/замены/доп. занятия)."""
        async def get_daily(date_iso: str) -> DayScheduleDTO:
            return await self.get_daily_schedule_for_student(
                class_id=class_id,
                group_id=group_id,
                date_iso=date_iso,
                student_id=student_id,
            )
        return await self._build_week_summary(
            get_daily,
            week_start_iso,
            count_distinct_nums=True,
        )

    async def get_teacher_week_schedule_summary(
        self,
        *,
        teacher_id: str,
        week_start_iso: str,
    ) -> WeekSummaryDTO:
        """Сводка недели учителя (без групп и доп. занятий)."""
        async def get_daily(date_iso: str) -> DayScheduleDTO:
            return await self.get_daily_schedule_for_teacher(
                teacher_id=teacher_id,
                date_iso=date_iso,
            )
        return await self._build_week_summary(
            get_daily,
            week_start_iso,
            count_distinct_nums=False,
        )

    async def get_class_week_schedule_summary(
        self,
        class_id: str,
        week_start_iso: str,
    ) -> WeekSummaryDTO:
        """Сводка недели класса (уроки/замены)."""
        async def get_daily(date_iso: str) -> DayScheduleDTO:
            return await self.get_daily_schedule_for_class(
                class_id=class_id,
                date_iso=date_iso,
            )
        return await self._build_week_summary(
            get_daily,
            week_start_iso,
            count_distinct_nums=True,
        )

    async def get_room_week_schedule_summary(
        self,
        room_id: str,
        week_start_iso: str,
    ) -> WeekSummaryDTO:
        """Сводка недели кабинета."""
        async def get_daily(date_iso: str) -> DayScheduleDTO:
            return await self.get_daily_schedule_for_room(
                room_id=room_id,
                date_iso=date_iso,
            )
        return await self._build_week_summary(
            get_daily,
            week_start_iso,
            count_distinct_nums=True,
        )
        
    # ==========================================================
    # Справочники и имена (кеш метаданных, 0 лишних SQL)
    # ==========================================================

    async def get_school_dictionaries(self) -> SchoolDictionariesDTO:
        return MetadataMapper.to_school_dictionaries(
            await self.schedule_repo.get_metadata()
        )

    async def get_classes_list(self) -> ClassListDTO:
        return MetadataMapper.to_class_list_dto(
            await self.schedule_repo.get_metadata()
        )

    async def get_groups_list(self) -> GroupListDTO:
        return MetadataMapper.to_group_list_dto(
            await self.schedule_repo.get_metadata()
        )

    async def get_teachers_list(self) -> TeacherListDTO:
        return MetadataMapper.to_teacher_list_dto(
            await self.schedule_repo.get_metadata()
        )

    async def get_teacher_name(
        self,
        teacher_id: str,
        fallback: str = "Преподаватель",
    ) -> str:
        """Имя учителя из кеша метаданных, без полного списка."""
        metadata = await self.schedule_repo.get_metadata()
        teacher = metadata.teachers.get(str(teacher_id))
        return teacher.name if teacher else fallback

    async def get_class_name(
        self,
        class_id: str,
        fallback: str = "Класс",
    ) -> str:
        """Название класса из кеша метаданных, без полного списка."""
        metadata = await self.schedule_repo.get_metadata()
        school_class = metadata.classes.get(str(class_id))
        return school_class.name if school_class else fallback

    # ==========================================================
    # Диагностика (проксирование DTO репозитория)
    # ==========================================================

    async def get_nika_health_status(self) -> NikaSourceHealthDTO:
        return await self.schedule_repo.get_nika_health_status()
