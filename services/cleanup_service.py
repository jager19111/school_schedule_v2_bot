import logging
from datetime import timedelta

from core.repository.user_repository import UserRepository
from services.time_service import TimeService

logger = logging.getLogger(__name__)


class UserCleanupJob:
    """
    Фоновая задача деактивации неактивных пользователей.

    Правила:
    - Использует TimeService для расчёта текущего времени.
    - cutoff = now_base - dormant_days.
    - В репозиторий передаётся UTC datetime.
    """

    def __init__(self, user_repo: UserRepository, time_service: TimeService, dormant_days: int = 60):
        self.user_repo = user_repo
        self.time_service = time_service
        self.dormant_days = dormant_days

    async def deactivate_dormant_users(self) -> None:
        try:
            # Правило 5: Вычисляем время на сервере, переводим в UTC
            now_base = self.time_service.get_now_base()
            cutoff_base = now_base - timedelta(days=self.dormant_days)
            cutoff_utc = self.time_service.to_utc(cutoff_base)

            logger.info(
                "Запуск очистки неактивных пользователей: now_base=%s, cutoff_utc=%s",
                now_base.isoformat(),
                cutoff_utc.isoformat() if cutoff_utc else "None",
            )

            # Передаём UTC-дату/время в репозиторий
            deactivated_count = await self.user_repo.deactivate_users_before(cutoff_utc)

            if deactivated_count > 0:
                logger.info("💤 Переведено в спящий режим неактивных пользователей: %d", deactivated_count)
            else:
                logger.info("Очистка неактивных пользователей: никого не деактивировано.")
        except Exception as e:
            logger.error("Ошибка при очистке неактивных пользователей: %s", e, exc_info=True)