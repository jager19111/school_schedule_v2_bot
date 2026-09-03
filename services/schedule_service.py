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

        # 2. Фильтрация по группе
        filtered_base = [
            lesson
            for lesson in base_lessons
            if lesson.get("group_id") == "ALL" or lesson.get("group_id") == group_id
        ]

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
        start_date = self.time_service.date_from_iso(week_start_iso)
        day_summaries = []
        
        for i in range(6): # Пн - Сб
            current_date_iso = (start_date + timedelta(days=i)).isoformat()
            day_dto = await self.get_daily_schedule_for_child(
                class_id=class_id, group_id=group_id, date_iso=current_date_iso, user_id=user_id
            )
            
            main_count = sum(1 for l in day_dto.lessons if not l.get("is_extra"))
            extra_count = sum(1 for l in day_dto.lessons if l.get("is_extra"))
            exchange_count = sum(1 for l in day_dto.lessons if l.get("is_exchange"))
            
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