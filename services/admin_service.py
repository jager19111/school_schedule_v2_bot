# services/admin_service.py

from __future__ import annotations

from core.models.dto import (
    AdminStatsDTO,
    NikaSourceHealthDTO,
)
from core.repository.admin_repository import (
    AdminRepository,
)
from core.repository.schedule_repository import (
    ScheduleRepository,
)


class AdminService:
    """
    Application service административных функций.

    Проверка admin access находится здесь, а не в handlers.
    Handlers не работают с SQL, config или repository напрямую.
    """

    def __init__(
        self,
        *,
        admin_repo: AdminRepository,
        schedule_repo: ScheduleRepository,
        admin_ids: list[int],
    ) -> None:
        self.admin_repo = admin_repo
        self.schedule_repo = schedule_repo
        self.admin_ids = set(admin_ids)

    def is_admin(
        self,
        *,
        user_id: int,
    ) -> bool:
        """
        Проверяет, разрешены ли admin commands пользователю.
        """
        return user_id in self.admin_ids

    async def get_statistics(
        self,
    ) -> AdminStatsDTO:
        """
        Возвращает общую статистику ролей.
        """
        raw_stats = await self.admin_repo.get_role_statistics()

        distribution: dict[str, int] = {}
        total = 0

        for row in raw_stats:
            role = row["role"] or "unknown"
            count = int(row["count"])

            distribution[role] = count
            total += count

        return AdminStatsDTO(
            total_users=total,
            role_distribution=distribution,
        )

    async def get_nika_source_health(self) -> NikaSourceHealthDTO:
        return await self.schedule_repo.get_nika_health_status()
    
    async def get_all_users_csv(self) -> str:
        """Генерирует CSV отчет по всем пользователям."""
        return await self.admin_repo.get_all_users_csv()