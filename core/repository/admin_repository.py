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
    
    async def get_all_users_csv(self) -> str:
            """
            Выгружает всех пользователей в формате CSV (строка).
            Инкапсулировано в репозитории для соблюдения манифеста.
            """
            query = """
                SELECT 
                    user_id, 
                    role, 
                    name, 
                    family_id,
                    datetime(last_active_at, 'localtime') as last_active
                FROM users
                ORDER BY last_active_at DESC
            """
            rows = await self._fetch_all(query)
            
            # Собираем CSV в памяти
            lines = ["user_id;role;name;family_id;last_active"]
            for row in rows:
                lines.append(f"{row['user_id']};{row['role'] or '-'};{row['name'] or '-'};{row['family_id'] or '-'};{row['last_active'] or '-'}")
                
            return "\n".join(lines)