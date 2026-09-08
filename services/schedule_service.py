# services/schedule_v2.py
from typing import List, Dict, Any, Optional
from datetime import timedelta
from core.repository.schedule_repository import ScheduleRepository
from core.repository.extra_classes_repository import ExtraClassesRepository
from services.time_service import TimeService
from core.models.dto import DayScheduleDTO, DaySummaryDTO, WeekSummaryDTO, WeekSummaryDTO, FullWeekScheduleDTO, ClassListDTO, GroupListDTO, TeacherListDTO, SchoolDictionariesDTO

class ScheduleService:
    def __init__(
        self,
        schedule_repo: ScheduleRepository,
        extra_classes_repo: ExtraClassesRepository,
        time_service: TimeService,
    ):
        self.schedule_repo = schedule_repo
        self.extra_repo = extra_classes_repo
        self.time_service = time_service

# Вспомогательный универсальный метод. Возвращает человекочитаемые названия класса и группы

    async def get_school_dictionaries(self) -> SchoolDictionariesDTO:
        """Получает справочники классов и групп за один запрос к репозиторию."""
        metadata = await self.schedule_repo.get_metadata()
        
        classes_raw = metadata.get('classes', {})
        classes_dict = {k: getattr(v, 'name', v) for k, v in classes_raw.items()}
        groups_dict = metadata.get('groups', {})
        
        return SchoolDictionariesDTO(classes=classes_dict, groups=groups_dict)
    
    if False:
        async def get_readable_class_and_group(
            self, 
            class_id: str | None, 
            group_id: str | None
        ) -> tuple[str, str]:
            """Возвращает человекочитаемые названия класса и группы."""
            classes_dto = await self.get_classes_list()
            groups_dto = await self.get_groups_list()
            
            class_name = classes_dto.classes.get(class_id, class_id) if class_id else "—"
            
            if not group_id or group_id == "ALL":
                group_name = "Весь класс"
            else:
                names = [
                    groups_dto.groups.get(g.strip(), f"Группа {g.strip()}") 
                    for g in str(group_id).split(",")
                ]
                group_name = ", ".join(names)
                
            return class_name, group_name

        async def get_classes_list(self) -> ClassListDTO:
            """Получает список классов из репозитория и упаковывает в DTO"""
            metadata = await self.schedule_repo.get_metadata()
            classes_raw = metadata.get('classes', {})
            # Извлекаем строковые имена, если объекты имеют атрибут name
            classes_dict = {k: getattr(v, 'name', v) for k, v in classes_raw.items()}
            return ClassListDTO(classes=classes_dict)

        async def get_groups_list(self) -> GroupListDTO:
            """Получает список групп из репозитория и упаковывает в DTO"""
            metadata = await self.schedule_repo.get_metadata()
            groups_raw = metadata.get('groups', {})
            return GroupListDTO(groups=groups_raw)
        
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

        school lessons:
        - определяются по class_id и group_id;

        extra classes:
        - принадлежат student_profiles.id;
        - не зависят от Telegram users.user_id.
        """
        # 1. Базовые уроки по классу
        base_lessons = await self.schedule_repo.get_lessons_for_class(
            class_id=class_id,
            date_iso=date_iso,
        )

        # 2. Умная фильтрация по группе и исключениям
        user_groups = group_id.split(",") if group_id and group_id != "ALL" else ["ALL"]
        filtered_base = []
        
        for lesson in base_lessons:
            l_group = lesson.get("group_id")
            subj_name = (lesson.get("subject_name") or "").lower()
            
            # Перехватываем номинальные предметы, чтобы вывести их деревом для всех
            is_nominal_tree = "труд" in subj_name or "технологи" in subj_name
            
            # Пропускаем урок, если совпала основная группа, ИЛИ это предмет-исключение
            if "ALL" in user_groups or l_group == "ALL" or l_group in user_groups or is_nominal_tree:
                filtered_base.append(lesson)

        # 3. Дополнительные занятия конкретного student profile.
        extra_lessons: list[dict] = []

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

        # 4. Мердж и безопасная сортировка
        combined = filtered_base + extra_lessons
        
        def safe_sort_key(l):
            safe_time = str(l.get("start_time") or "").zfill(5)
            num = l.get("lesson_num")
            safe_num = int(num) if num not in (None, "") else 99
            return (safe_time, safe_num)

        combined.sort(key=safe_sort_key)

        # 5. Обогащение данных (названия групп и смены)
        metadata = await self.schedule_repo.get_metadata()
        groups_dict = metadata.get("groups", {})
        
        for l in combined:
            g_id = l.get("group_id")
            # Назначаем имена подгруппам (игнорируя доп. занятия, у них group_id="ALL")
            if g_id and g_id != "ALL" and not l.get("is_extra"):
                l["group_name"] = groups_dict.get(g_id, f"Группа {g_id}")

        # Метод _enrich_display_numbers безопасно проигнорирует extra_lessons, 
        # так как у них is_extra=True, и поставит им display_num = "•"
        self._enrich_display_numbers(combined, metadata)

        return DayScheduleDTO(date_iso=date_iso, lessons=combined)

    def _map_extra_to_lesson(
        self,
        row: Dict[str, Any],
        date_iso: str,
    ) -> Dict[str, Any]:
        """
        Преобразует extra_classes-запись в lesson-словарь,
        совместимый с UIRenderer расписания.
        """
        return {
            "id": f"extra-{row['id']}",
            "date": date_iso,

            "lesson_num": None,
            "display_num": "•",

            "start_time": row["time_start"],
            "end_time": row["time_end"],

            "subject_name": row["title"],
            "room_name": row.get("location") or "—",

            "is_extra": True,
            "is_cancelled": False,
            "is_exchange": False,

            # Допзанятие не является школьным уроком класса.
            "class_id": None,
            "group_id": "ALL",
            "group_name": None,

            # Полезно для дальнейших diagnostics и notifications.
            "student_id": row["student_id"],
        }
        
    # Умная Логика времени

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

            latest_end_time = max(
                (
                    lesson.get("end_time", "00:00")
                    for lesson in day_dto.lessons
                ),
                default="00:00",
            )

            if now.strftime("%H:%M") <= latest_end_time:
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
        self, class_id: str, group_id: str, week_start_iso: str, student_id: int | None = None
    ) -> WeekSummaryDTO:
        """Собирает сводку (кол-во уроков, замен, доп. занятий) на неделю."""
        from datetime import timedelta
        start_date = self.time_service.date_from_iso(week_start_iso)
        day_summaries = []
        
        for i in range(6): # Пн - Сб
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_student(
                class_id=class_id, group_id=group_id, date_iso=current_date_iso, student_id=student_id
            )
            
            # Считаем уникальные номера основных уроков (set автоматически уберет дубли подгрупп)
            main_lesson_nums = {
                l.get("lesson_num") 
                for l in day_dto.lessons 
                if not l.get("is_extra") and l.get("lesson_num") is not None
            }
            main_count = len(main_lesson_nums)
            
            # Считаем уникальные номера измененных уроков
            exchange_nums = {
                l.get("lesson_num") 
                for l in day_dto.lessons 
                if l.get("is_exchange") and l.get("lesson_num") is not None
            }
            exchange_count = len(exchange_nums)

            # Доп. занятия не имеют номеров, их считаем напрямую
            extra_count = sum(1 for l in day_dto.lessons if l.get("is_extra"))
            
            day_summaries.append(DaySummaryDTO(
                date_iso=current_date_iso,
                lesson_count=main_count,
                extra_count=extra_count,
                exchange_count=exchange_count
            ))
            
        return WeekSummaryDTO(week_start_iso=week_start_iso, days=day_summaries)
        
    async def get_full_week_schedule(
        self, class_id: str, group_id: str, week_start_iso: str, student_id: int | None = None
    ) -> FullWeekScheduleDTO:
        """Собирает полное расписание на всю неделю."""
        start_date = self.time_service.date_from_iso(week_start_iso)
        days = []
        for i in range(6):
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_student(
                class_id=class_id, group_id=group_id, date_iso=current_date_iso, student_id=student_id
            )
            days.append(day_dto)
        return FullWeekScheduleDTO(week_start_iso=week_start_iso, days=days)
    
    
    # методы для формирования расписания для поиска

    # Вставить/Заменить методы в классе ScheduleService:

    async def get_daily_schedule_for_class(self, class_id: str, date_iso: str) -> DayScheduleDTO:
        lessons = await self.schedule_repo.get_lessons_for_class(class_id, date_iso)
        
        def sort_key(l):
            num = int(l.get("lesson_num") or 0)
            st = l.get("start_time") or ""
            return (num, st.zfill(5))  # zfill делает "08:15" из "8:15" для правильной сортировки

        combined = sorted(lessons, key=sort_key)
        
        # Получаем настройки смен и обогащаем номера уроков
        metadata = await self.schedule_repo.get_metadata()
        self._enrich_display_numbers(combined, metadata)
        
        return DayScheduleDTO(date_iso=date_iso, lessons=combined)

    async def get_daily_schedule_for_teacher(self, teacher_id: str, date_iso: str) -> DayScheduleDTO:
        lessons = await self.schedule_repo.get_lessons_for_teacher(teacher_id, date_iso)
        metadata = await self.schedule_repo.get_metadata()
        classes_dict = metadata.get('classes', {})
        
        # Подтягиваем названия классов
        for l in lessons:
            c_id = l.get("class_id")
            if c_id in classes_dict:
                cls_obj = classes_dict[c_id]
                l["class_name"] = cls_obj.name if hasattr(cls_obj, 'name') else cls_obj
            else:
                l["class_name"] = c_id

        def sort_key(l):
            num = int(l.get("lesson_num") or 0)
            st = l.get("start_time") or ""
            return (num, st.zfill(5))

        combined = sorted(lessons, key=sort_key)
        
        # Для учителей смены не применяются, используем абсолютные номера
        for l in combined:
            num = l.get("lesson_num")
            l["display_num"] = str(num) if num else "•"
            
        return DayScheduleDTO(date_iso=date_iso, lessons=combined)
        
    async def get_full_week_schedule_for_class(self, class_id: str, week_start_iso: str) -> FullWeekScheduleDTO:
        from datetime import timedelta
        start_date = self.time_service.date_from_iso(week_start_iso)
        days = []
        for i in range(6):
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_class(class_id, current_date_iso)
            days.append(day_dto)
        return FullWeekScheduleDTO(week_start_iso=week_start_iso, days=days)

    async def get_full_week_schedule_for_teacher(self, teacher_id: str, week_start_iso: str) -> FullWeekScheduleDTO:
        from datetime import timedelta
        start_date = self.time_service.date_from_iso(week_start_iso)
        days = []
        for i in range(6):
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_teacher(teacher_id, current_date_iso)
            days.append(day_dto)
        return FullWeekScheduleDTO(week_start_iso=week_start_iso, days=days)
    
    # Парсинг 2 смены
    def _enrich_display_numbers(self, lessons: list[dict], metadata: dict) -> None:
        class_shifts = metadata.get("class_shift", {})
        second_relative = metadata.get("second_relative", False)

        # Группируем уроки по дате и классу (особенно важно для расписания учителей)
        groups = {}
        for l in lessons:
            if not l.get("is_extra") and l.get("lesson_num"):
                key = (l["date"], l["class_id"])
                groups.setdefault(key, []).append(l)

        for (date_iso, c_id), day_lessons in groups.items():
            p_id = day_lessons[0].get("period_id")
            
            # Определяем, с какого урока начинается 2 смена для этого класса
            shift_start = 1
            if p_id in class_shifts and c_id in class_shifts[p_id]:
                shift_start = int(class_shifts[p_id][c_id])

            day_lessons.sort(key=lambda x: x["lesson_num"])

            # Точная копия логики из nika_data.js
            w_flag = (shift_start == 1)
            for l in day_lessons:
                m = l["lesson_num"]
                v = m
                is_star = False

                if shift_start > 1 and not w_flag:
                    if m < shift_start:
                        w_flag = True  # Отключает 2 смену до конца дня, если начали раньше!
                    else:
                        v = m - shift_start + 1
                        is_star = True

                if is_star:
                    display_val = v if second_relative else m
                    l["display_num"] = f"{display_val}*"
                else:
                    l["display_num"] = str(m)

        # Для доп. занятий или уроков без номера
        for l in lessons:
            if "display_num" not in l:
                l["display_num"] = "•"
                
                


    #----------------------
    #   УЧИТЕЛЬ
    #----------------------
        
    async def get_teachers_list(self) -> TeacherListDTO:
        """
        Возвращает справочник учителей NIKA для registration/search UI.
        """
        metadata = await self.schedule_repo.get_metadata()

        teachers_raw = metadata.get("teachers", {})

        teachers = {
            teacher_id: getattr(
                teacher,
                "name",
                teacher,
            )
            for teacher_id, teacher in teachers_raw.items()
        }

        return TeacherListDTO(
            teachers=teachers,
        )
        
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

        for offset in range(8):
            candidate_date = today + timedelta(days=offset)
            candidate_iso = candidate_date.isoformat()

            day_dto = await self.get_daily_schedule_for_teacher(
                teacher_id=teacher_id,
                date_iso=candidate_iso,
            )

            if not day_dto.lessons:
                continue

            if candidate_date != today:
                return candidate_iso

            latest_end_time = max(
                (
                    lesson.get("end_time", "00:00")
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
        start_date = self.time_service.date_from_iso(
            week_start_iso,
        )

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
                1
                for lesson in day_dto.lessons
                if lesson.get("is_exchange")
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