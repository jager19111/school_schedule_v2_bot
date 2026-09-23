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

        Публичный API для notification-слоя.
        Сравнивает мультимножества 4D-сигнатур «было»/«стало».
        """
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
                l.original_group_id or "ALL",
            )
            for l in exchanges
        )
        curr_counter = Counter(
            (
                l.subject_id,
                l.room_id,
                l.teacher_id,
                l.group_id or "ALL",
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
        if origin == "teacher":
            for l in lessons:
                l.display_num = str(l.lesson_num) if l.lesson_num is not None else "•"
            return
        class_shifts = metadata.class_shift
        second_relative = metadata.second_relative

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
                    display_val = v if second_relative else m
                    l.display_num = f"{display_val}*"
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
        Сводка одного дня.

        count_distinct_nums=True (класс): уникальные номера уроков
        (многогрупповой слот = один урок).
        count_distinct_nums=False (учитель): количество записей.
        """
        lessons = day_dto.lessons

        if count_distinct_nums:
            lesson_count = len({
                l.lesson_num
                for l in lessons
                if not l.is_extra and l.lesson_num is not None
            })
            exchange_count = len({
                l.lesson_num
                for l in lessons
                if l.is_exchange and not l.is_extra
                and l.lesson_num is not None
            })
        else:
            lesson_count = len(lessons)
            exchange_count = sum(1 for l in lessons if l.is_exchange)

        return DaySummaryDTO(
            date_iso=date_iso,
            lesson_count=lesson_count,
            extra_count=sum(1 for l in lessons if l.is_extra),
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
    ) -> DayScheduleDTO:
        """
        LessonInstance[] -> DayScheduleDTO:
        permutation -> map -> sort -> enrich display_num.

        Полный конвейер запускается ровно один раз на день.
        """
        day_permutation = self.detect_day_permutation(lessons)

        dtos: List[LessonDTO] = LessonMapper.to_dto_list(
            lessons, day_permutation=day_permutation
        )
        if extra_items:
            dtos += [
                self._map_extra_to_lesson(extra, date_iso)
                for extra in extra_items
            ]

        dtos.sort(key=self._sort_key)

        metadata = await self.schedule_repo.get_metadata()
        self._enrich_display_numbers_dtos(dtos, metadata, origin=origin)

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
        """Расписание учителя на день (включая методические часы)."""
        return await self._assemble_day_schedule(
            lessons=await self.schedule_repo.get_lessons_for_teacher(teacher_id=teacher_id, date_iso=date_iso),
            date_iso=date_iso, origin="teacher"
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

        changed = sorted(
            (l for l in lessons if l.is_exchange or l.is_cancelled),
            key=lambda l: l.lesson_num or 99,
        )

        day_permutation = self.detect_day_permutation(changed)
        lesson_dtos = LessonMapper.to_dto_list(
            changed, day_permutation=day_permutation
        )

        metadata = await self.schedule_repo.get_metadata()
        self._enrich_display_numbers_dtos(lesson_dtos, metadata, origin=origin)
        # Обогащаем названия классов для учителя ===
        if origin == "teacher":
            for dto in lesson_dtos:
                # Текущий класс
                if dto.class_id:
                    cls_obj = metadata.classes.get(str(dto.class_id))
                    dto.class_name = cls_obj.name if cls_obj else str(dto.class_id)
                
                # Оригинальный класс (на случай, если учителю перекинули урок с одного класса на другой)
                if dto.original_class_id:
                    orig_cls_obj = metadata.classes.get(str(dto.original_class_id))
                    dto.original_class_name = orig_cls_obj.name if orig_cls_obj else str(dto.original_class_id)
                                                           
        return DayChangesDetailDTO(
            date_iso=date_iso,
            origin=origin,
            lessons=lesson_dtos,
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
        slots_map = {}
        for l in lessons_today:
            if l.start_time and l.end_time:
                slot = (l.start_time, l.end_time)
                if slot not in slots_map and l.lesson_num:
                    slots_map[slot] = l.lesson_num
                
        sorted_slots = sorted(list(slots_map.keys()), key=lambda x: self._parse_hhmm(x[0]))
        
        # 2. Ищем целевой слот
        target_slot = None
        target_num = None
        is_break = False
        
        for start_str, end_str in sorted_slots:
            try:
                start_t = self._parse_hhmm(start_str)
                end_t = self._parse_hhmm(end_str)
                
                if current_time_obj <= end_t:
                    target_slot = (start_str, end_str)
                    target_num = slots_map.get(target_slot)
                    if current_time_obj < start_t:
                        is_break = True
                    break
            except ValueError:
                continue

        # 3. Вычисляем занятые кабинеты
        occupied_ids = set()
        if target_slot:
            t_start_obj = self._parse_hhmm(target_slot[0])
            t_end_obj = self._parse_hhmm(target_slot[1])
            
            for l in lessons_today:
                if not l.start_time or not l.end_time:
                    continue
                try:
                    l_start = self._parse_hhmm(l.start_time)
                    l_end = self._parse_hhmm(l.end_time)
                    if l_start < t_end_obj and l_end > t_start_obj:
                        occupied_ids.add(str(l.room_id))
                except ValueError:
                    pass

        # 4. Формируем DTO состояния
        status_dto = FreeRoomsStatusDTO(
            current_time_str=now.strftime("%H:%M"),
            is_finished=not bool(target_slot),
            is_break=is_break,
            target_num=target_num,
            start_time=target_slot[0] if target_slot else None,
            end_time=target_slot[1] if target_slot else None
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

        # 3. Сортировка по времени и номеру
        unique_dtos.sort(key=self._sort_key)

        # 4. Обогащение номерами уроков (со звездочками)
        metadata = await self.schedule_repo.get_metadata()
        self._enrich_display_numbers_dtos(unique_dtos, metadata)

        # Безопасное получение названия кабинета
        room_obj = metadata.rooms.get(str(room_id))
        room_name = room_obj.name if room_obj else str(room_id)

        return DayScheduleDTO(
            date_iso=date_iso,
            lessons=unique_dtos,
            has_permutation=day_permutation,
            origin="class",  # Системный origin
            class_name=room_name
        )

    async def get_smart_room_target_date(self, room_id: str) -> str:
        """
        Умная дата для кабинета.
        Для кабинетов пустой день — это полезная информация ("свободен весь день"),
        поэтому мы не ищем следующий день с уроками, а просто откидываем вечер и выходные.
        """
        now = self.time_service.get_now_base()
        target = now
        
        # Если время после 19:00, переключаем на завтра
        if target.hour >= 19:
            target += timedelta(days=1)
            
        # Если попадаем на воскресенье, переключаем на понедельник
        if target.isoweekday() == 7:
            target += timedelta(days=1)
            
        return target.date().isoformat()
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
        """
        Ближайший актуальный день ученика.

        Проба дней идёт по сырым LessonInstance (дёшево), полный
        конвейер DTO запускается один раз — для выбранного дня.
        Правила: сегодня с незаконченными занятиями -> сегодня;
        иначе первый непустой день в пределах 8 дней.
        """
        today = self.time_service.get_now_base().date()
        now_time = self.time_service.get_now_base().time()

        first_lessons: List[LessonInstance] = []
        first_extras: List[ExtraClassItemDTO] = []
        metadata = await self.schedule_repo.get_metadata()

        for offset in range(SMART_DATE_HORIZON_DAYS):
            date = today + timedelta(days=offset)
            date_iso = date.isoformat()

            lessons = self._filter_by_groups(
                await self.schedule_repo.get_lessons_for_class(class_id=class_id, date_iso=date_iso),
                group_id, metadata.groups
            )
            extra_items = await self._fetch_extra_items(student_id, date_iso)

            if offset == 0:
                first_lessons, first_extras = lessons, extra_items

            if not lessons and not extra_items:
                continue

            if date != today:
                return await self._assemble_day_schedule(lessons=lessons, date_iso=date_iso, extra_items=extra_items, origin="student", class_id=class_id, group_id=group_id)

            end_times = [self._parse_hhmm(l.end_time) for l in lessons if l.end_time] + [self._parse_hhmm(e.time_end) for e in extra_items if e.time_end]
            if not end_times: continue

            if now_time <= max(end_times):
                return await self._assemble_day_schedule(lessons=lessons, date_iso=date_iso, extra_items=extra_items, origin="student", class_id=class_id, group_id=group_id)

        return await self._assemble_day_schedule(lessons=first_lessons, date_iso=today.isoformat(), extra_items=first_extras, origin="student", class_id=class_id, group_id=group_id)
    
    
    async def get_smart_day_schedule_for_teacher(self, *, teacher_id: str) -> DayScheduleDTO:
        """Ближайший актуальный день учителя."""
        today = self.time_service.get_now_base().date()
        now_time = self.time_service.get_now_base().time()
        first_lessons: List[LessonInstance] = []

        for offset in range(SMART_DATE_HORIZON_DAYS):
            date = today + timedelta(days=offset)
            date_iso = date.isoformat()
            lessons = await self.schedule_repo.get_lessons_for_teacher(teacher_id=teacher_id, date_iso=date_iso)

            if offset == 0: first_lessons = lessons
            if not lessons: continue

            if date != today:
                return await self._assemble_day_schedule(lessons=lessons, date_iso=date_iso, origin="teacher")

            end_times = [self._parse_hhmm(l.end_time) for l in lessons if l.end_time]
            if not end_times: continue

            if now_time <= max(end_times):
                return await self._assemble_day_schedule(lessons=lessons, date_iso=date_iso, origin="teacher")

        return await self._assemble_day_schedule(lessons=first_lessons, date_iso=today.isoformat(), origin="teacher")
    

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
