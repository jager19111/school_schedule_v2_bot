import aiosqlite
import datetime

class UserRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def deactivate_users_before(self, cutoff_utc: datetime.datetime) -> int:
        """Отключает пользователей, чья активность была до cutoff_utc[cite: 1]."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                UPDATE users 
                SET is_notifications_enabled = 0 
                WHERE last_active_at <= ? AND is_notifications_enabled = 1
            ''', (cutoff_utc,))
            await db.commit()
            return cursor.rowcount