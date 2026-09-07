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

    async def get_nika_source_health(
        self,
    ) -> NikaSourceHealthDTO:
        """
        Возвращает сохранённый status NIKA source и schedule cache.
        """
        row = await self.schedule_repo.get_nika_health_status()

        return NikaSourceHealthDTO(
            status=row["status"],
            lesson_count=int(row.get("lesson_count", 0)),

            today_date=row.get("today_date"),

            coverage_start_date=row.get(
                "coverage_start_date"
            ),
            coverage_end_date=row.get(
                "coverage_end_date"
            ),

            coverage_is_current=bool(
                row.get("coverage_is_current", False)
            ),

            coverage_has_future=bool(
                row.get("coverage_has_future", False)
            ),

            js_filename=row.get("js_filename"),
            export_date=row.get("export_date"),
            export_time=row.get("export_time"),

            last_checked_at=row.get("last_checked_at"),
            last_changed_at=row.get("last_changed_at"),

            last_error=row.get("last_error"),
            last_error_at=row.get("last_error_at"),
        )