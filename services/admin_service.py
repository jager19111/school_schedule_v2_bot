from core.repository.admin_repository import AdminRepository
from core.models.dto import AdminStatsDTO

class AdminService:
    def __init__(self, admin_repo: AdminRepository):
        self.admin_repo = admin_repo

    async def get_statistics(self) -> AdminStatsDTO:
        """Слой бизнес-логики: собирает данные и упаковывает в DTO[cite: 1]."""
        raw_stats = await self.admin_repo.get_role_statistics()
        
        distribution = {}
        total = 0
        for row in raw_stats:
            role = row['role'] or 'unknown'
            count = row['count']
            distribution[role] = count
            total += count
            
        return AdminStatsDTO(total_users=total, role_distribution=distribution)