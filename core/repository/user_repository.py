# core/repository/user_repository.py
from datetime import datetime
from core.repository.base_repository import BaseRepository


class UserRepository(BaseRepository):
    """
    Репозиторий пользователей.

    Пока содержит только деактивацию неактивных по времени.
    """


    async def deactivate_users_before(self, cutoff_utc: datetime) -> int:
        """
        Отключает уведомления пользователям, чья last_active_at <= cutoff_utc (UTC).
        """
        cutoff_utc_str = cutoff_utc.strftime("%Y-%m-%d %H:%M:%S")
        query = """
            UPDATE users
            SET is_notifications_enabled = 0
            WHERE last_active_at <= ? AND is_notifications_enabled = 1
        """
        return await self._execute(query, (cutoff_utc_str,))
        
    async def optimize_database(self) -> None:
        """
        Просит SQLite обновить внутренние статистики и оптимизировать
        query planner.

        Не удаляет данные и не делает VACUUM.
        """
        async with self._connection() as db:
            await db.execute("PRAGMA optimize")