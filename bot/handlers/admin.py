import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
import aiosqlite

logger = logging.getLogger(__name__)
router = Router()

@router.message(Command("stats"))
async def cmd_stats(message: Message, db_path: str):
    """Вывод статистики по пользователям и ролям[cite: 4]."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT role, COUNT(*) FROM users GROUP BY role")
        rows = await cursor.fetchall()
        
        stats_text = "📊 <b>Статистика пользователей:</b>\n\n"
        for role, count in rows:
            stats_text += f"- {role}: {count}\n"
            
        await message.answer(stats_text, parse_mode="HTML")