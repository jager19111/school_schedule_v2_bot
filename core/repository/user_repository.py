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
        query = """
            UPDATE users
            SET is_notifications_enabled = 0
            WHERE last_active_at <= ? AND is_notifications_enabled = 1
        """
        # cutoff_utc уже должен быть aware-UTC, но sqlite хранит TEXT/naive,
        # поэтому сюда передаём либо строку, либо naive datetime.
        return await self._execute(query, (cutoff_utc,))