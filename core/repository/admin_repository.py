import aiosqlite
from typing import Dict, Any

class AdminRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def get_role_statistics(self) -> list[dict]:
        """Возвращает сырые данные по ролям (Plain data)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT role, COUNT(*) as count FROM users GROUP BY role")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]