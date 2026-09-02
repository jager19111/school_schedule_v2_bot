import logging
from core.repository.user_repository import UserRepository
from services.time_service import TimeService

logger = logging.getLogger(__name__)

class UserCleanupJob:
    def __init__(self, user_repo: UserRepository, time_service: TimeService, dormant_days: int = 60):
        self.user_repo = user_repo
        self.time_service = time_service
        self.dormant_days = dormant_days

    async def deactivate_dormant_users(self) -> None:
        try:
            # Правило 5: Вычисляем время на сервере, переводим в UTC[cite: 1]
            now_base = self.time_service.get_now_base()
            cutoff_date = now_base - self.time_service.timedelta(days=self.dormant_days)
            cutoff_utc = self.time_service.to_utc(cutoff_date)
            
            # Передаем UTC-дату в репозиторий
            deactivated_count = await self.user_repo.deactivate_users_before(cutoff_utc)
            
            if deactivated_count > 0:
                logger.info(f"💤 Переведено в спящий режим неактивных пользователей: {deactivated_count}")
        except Exception as e:
            logger.error(f"Ошибка при очистке неактивных пользователей: {e}", exc_info=True)