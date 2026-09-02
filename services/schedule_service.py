# services/schedule_v2.py
from typing import List, Dict, Any, Optional

from core.repository.schedule_repository import ScheduleRepository
from core.repository.extra_classes_repository import ExtraClassesRepository
from services.time_service import TimeService
from core.models.dto import DayScheduleDTO

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