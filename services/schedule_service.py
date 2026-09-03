# services/schedule_v2.py
from typing import List, Dict, Any, Optional
from datetime import timedelta
from core.repository.schedule_repository import ScheduleRepository
from core.repository.extra_classes_repository import ExtraClassesRepository
from services.time_service import TimeService
from core.models.dto import DayScheduleDTO, DaySummaryDTO, WeekSummaryDTO, WeekSummaryDTO, FullWeekScheduleDTO

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

    async def get_daily_schedule_for_child(
        self,
        *,
        class_id: str,
        group_id: str,
        date_iso: str,
        user_id: int | None = None,
    ) -> DayScheduleDTO:
        """
        Возвращает расписание для ребёнка на день в виде DayScheduleDTO.
        """
        # 1. Базовые уроки по классу
        base_lessons = await self.schedule_repo.get_lessons_for_class(
            class_id=class_id,
            date_iso=date_iso,
        )

        # 2. Умная фильтрация по группе
        filtered_base = []
        for lesson in base_lessons:
            l_group = lesson.get("group_id")
            # Если пользователь выбрал "Весь класс", он видит все уроки
            if group_id == "ALL":
                filtered_base.append(lesson)
            # Иначе он видит общие уроки класса И уроки своей группы
            elif l_group == "ALL" or l_group == group_id:
                filtered_base.append(lesson)

        extra_lessons: list[dict] = []

        # 3. Доп. занятия пользователя
        if user_id is not None:
            date_obj = self.time_service.date_from_iso(date_iso)
            weekday = date_obj.isoweekday()

            extra_rows = await self.extra_repo.get_extra_classes_for_user(
                user_id=user_id,
                day_of_week=weekday,
            )

            extra_lessons = [self._map_extra_to_lesson(row, date_iso) for row in extra_rows]

        # 4. Мердж и сортировка
        combined = filtered_base + extra_lessons
        combined.sort(
            key=lambda l: (
                l.get("start_time") or "",
                l.get("lesson_num") or 0,
            )
        )

        metadata = await self.schedule_repo.get_metadata()
        self._enrich_display_numbers(combined, metadata)
        
        return DayScheduleDTO(date_iso=date_iso, lessons=combined)

    def _map_extra_to_lesson(self, row: Dict[str, Any], date_iso: str) -> Dict[str, Any]:
        """
        Преобразует запись extra_classes в lesson-словарь,
        совместимый с рендером расписания.
        """
        return {
            "id": f"extra-{row['id']}",
            "date": date_iso,
            "lesson_num": None,
            "start_time": row["time_start"],
            "end_time": row["time_end"],
            "subject_name": row["title"],
            "room_name": row.get("location") or "—",
            "is_extra": True,
            "is_cancelled": False,
            "is_exchange": False,
            "class_id": row["user_id"],
            "group_id": "ALL",
        }
        


    # Умная Логика времени

    async def get_smart_target_date(self, class_id: str, group_id: str, user_id: int | None = None) -> str:
        """
        Возвращает ISO-дату. Если на сегодня уроки есть и они уже закончились,
        возвращает завтрашний день. Иначе - сегодня.
        """
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()
        
        day_dto = await self.get_daily_schedule_for_child(
            class_id=class_id, group_id=group_id, date_iso=today_iso, user_id=user_id
        )
        
        if not day_dto.lessons:
            # Если сегодня уроков нет (например, воскресенье), переключаем на завтра
            if now.isoweekday() == 7:
                return (now + timedelta(days=1)).date().isoformat()
            return today_iso

        # Ищем самое позднее время окончания
        latest_end_time = "00:00"
        for lesson in day_dto.lessons:
            if lesson.get("end_time") and lesson["end_time"] > latest_end_time:
                latest_end_time = lesson["end_time"]
                
        now_time_str = now.strftime("%H:%M")
        if now_time_str > latest_end_time:
            return (now + timedelta(days=1)).date().isoformat()
            
        return today_iso

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
        self, class_id: str, group_id: str, week_start_iso: str, user_id: int | None = None
    ) -> WeekSummaryDTO:
        """Собирает сводку (кол-во уроков, замен, доп. занятий) на неделю."""
        from datetime import timedelta
        start_date = self.time_service.date_from_iso(week_start_iso)
        day_summaries = []
        
        for i in range(6): # Пн - Сб
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_child(
                class_id=class_id, group_id=group_id, date_iso=current_date_iso, user_id=user_id
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
        self, class_id: str, group_id: str, week_start_iso: str, user_id: int | None = None
    ) -> FullWeekScheduleDTO:
        """Собирает полное расписание на всю неделю."""
        start_date = self.time_service.date_from_iso(week_start_iso)
        days = []
        for i in range(6):
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_child(
                class_id=class_id, group_id=group_id, date_iso=current_date_iso, user_id=user_id
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