import json
from datetime import datetime
from core.repository.base_repository import BaseRepository

class AuditRepository(BaseRepository):
    """
    Репозиторий для записи сырых логов аудита в БД.
    Наследует BaseRepository, получая доступ к self.time_service и self._execute.
    """

    async def log(self, actor_id: int, target_id: int, action: str, timestamp: datetime, payload: dict) -> None:
        query = """
            INSERT INTO audit_logs (timestamp, actor_id, target_id, action, payload)
            VALUES (?, ?, ?, ?, ?)
        """
        
        # Строгое соблюдение Time Governance: переводим aware-время в чистую UTC-строку
        # Формат: YYYY-MM-DD HH:MM:SS
        utc_str = self.time_service.utc_str_from(timestamp)
        
        # Используем _execute, который сам захватит write-lock и сделает commit
        await self._execute(
            query,
            (utc_str, actor_id, target_id, action, json.dumps(payload, ensure_ascii=False))
        )