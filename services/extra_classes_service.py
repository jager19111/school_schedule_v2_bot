import logging
from typing import Optional
from core.models.dto import ActionResponseDTO, ExtraClassItemDTO, ExtraClassListDTO
from core.repository.extra_classes_repository import ExtraClassesRepository
from services.time_service import TimeService

logger = logging.getLogger(__name__)

class ExtraClassesService:
    """Сервис бизнес-логики для управления дополнительными занятиями[cite: 2]."""
    
    def __init__(self, extra_classes_repo: ExtraClassesRepository, time_service: TimeService):
        self.repo = extra_classes_repo
        self.time_service = time_service

    async def add_extra_class(
        self, 
        user_id: int, 
        family_id: Optional[int], 
        day_of_week: int,          # <-- Теперь передается явно
        time_start: str, 
        time_end: str, 
        title: str,
        location: Optional[str],   # <-- Добавлено
        reminder_minutes: int      # <-- Добавлено
    ) -> ActionResponseDTO:
        # 1. Строгая валидация времени на стороне сервиса
        if not self.time_service.validate_time_format(time_start) or not self.time_service.validate_time_format(time_end):
            return ActionResponseDTO(success=False, error_code="invalid_time")

        try:
            # 2. Делегируем изолированный SQL-запрос репозиторию[cite: 12]
            extra_id = await self.repo.create_extra_class(
                user_id=user_id,
                family_id=family_id,
                day_of_week=day_of_week,
                time_start=time_start,
                time_end=time_end,
                title=title,
                location=location,
                reminder_minutes=reminder_minutes
            )
            return ActionResponseDTO(success=True, data={"extra_id": extra_id})
        except Exception as e:
            logger.error(f"Ошибка при создании доп. занятия: {e}", exc_info=True)
            return ActionResponseDTO(success=False, error_code="db_error")
        
    async def get_user_extra_classes(self, user_id: int) -> ExtraClassListDTO:
        """Получает список занятий пользователя через DTO."""
        rows = await self.repo.get_extra_classes_for_user(user_id=user_id)
        items = [
            ExtraClassItemDTO(
                id=r['id'],
                day_of_week=r['day_of_week'],
                time_start=r['time_start'],
                time_end=r['time_end'],
                title=r['title'],
                location=r.get('location')
            )
            for r in rows
        ]
        return ExtraClassListDTO(items=items)

    async def delete_extra_class(self, user_id: int, extra_id: int) -> ActionResponseDTO:
        """Безопасное удаление: репозиторий удалит запись, только если она принадлежит user_id."""
        success = await self.repo.delete_extra_class(extra_id=extra_id, user_id=user_id)
        if success:
            return ActionResponseDTO(success=True)
        return ActionResponseDTO(success=False, error_code="not_found")