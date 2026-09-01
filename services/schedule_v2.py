from typing import List, Dict, Any
from core.repository.schedule_repository import ScheduleRepository

class ScheduleServiceV2:
    def __init__(self, repository: ScheduleRepository):
        self.repo = repository

    async def get_daily_schedule_for_child(self, class_id: str, group_id: str, date_iso: str) -> List[Dict[str, Any]]:
        """
        Формирует расписание ученика, фильтруя уроки по его подгруппе.
        Оставляет уроки с group_id = "ALL" и уроки, совпадающие с group_id ученика[cite: 1, 2].
        """
        raw_lessons = await self.repo.get_lessons_for_class(class_id, date_iso)
        filtered_lessons = []
        
        for lesson in raw_lessons:
            # Оставляем урок, если он для всего класса или совпадает с группой ребенка[cite: 2, 3]
            if lesson['group_id'] == 'ALL' or lesson['group_id'] == group_id:
                filtered_lessons.append(lesson)
                
        # TODO: Добавить логику слияния с extra_classes (Этап 6)[cite: 2, 3]
        return filtered_lessons