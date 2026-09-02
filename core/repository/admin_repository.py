# core/repository/admin_repository.py
from typing import List, Dict, Any

from core.repository.base_repository import BaseRepository


class AdminRepository(BaseRepository):
    """
    Репозиторий административной статистики.

    Делегирует все низкоуровневые операции BaseRepository.
    """

    async def get_role_statistics(self) -> List[Dict[str, Any]]:
        """
        Возвращает список {role, count}.
        """
        query = "SELECT role, COUNT(*) as count FROM users GROUP BY role"
        return await self._fetch_all(query)