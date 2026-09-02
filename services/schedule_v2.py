   
from typing import List
from core.repository.schedule_repository import ScheduleRepository
from core.models.dto import DayScheduleDTO, LessonDTO

class ScheduleServiceV2:
    def __init__(self, repository: ScheduleRepository):
        self.repo = repository

    async def get_daily_schedule_for_child(self, class_id: str, group_id: str, date_iso: str) -> DayScheduleDTO:
        """
        Формирует расписание ученика, фильтруя уроки по его подгруппе и возвращает DTO.
        Оставляет уроки с group_id = "ALL" и уроки, совпадающие с group_id ученика
        """
        raw_lessons = await self.repo.get_lessons_for_class(class_id, date_iso)
        lesson_dtos = []
        
        for l in raw_lessons:
            # Оставляем урок, если он для всего класса или совпадает с группой ребенка
            if l['group_id'] == 'ALL' or l['group_id'] == group_id:
                lesson_dtos.append(LessonDTO(
                    lesson_num=l['lesson_num'],
                    start_time=l['start_time'],
                    end_time=l['end_time'],
                    subject_name=l['subject_name'] or "—",
                    room_name=l.get('room_name') or "—",
                    is_cancelled=bool(l['is_cancelled']),
                    is_exchange=bool(l['is_exchange'])
                ))
                
        # TODO: Добавить логику слияния с extra_classes (Этап 6)[cite: 2, 3]               
        return DayScheduleDTO(date_iso=date_iso, lessons=lesson_dtos)