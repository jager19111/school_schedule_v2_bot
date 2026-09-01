import aiosqlite
import logging
from typing import Dict, Any, List, Optional
import uuid

logger = logging.getLogger(__name__)

class ProfileService:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def update_last_active(self, user_id: int) -> None:
        """Обновляет время последней активности пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE user_id = ?
            ''', (user_id,))
            await db.commit()

    async def get_user_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row:
                await self.update_last_active(user_id)
                return dict(row)
            return None

    async def create_family_and_link(self, admin_user_id: int) -> str:
        """Создает новую семью и привязывает создателя как админа[cite: 3, 7]."""
        family_code = str(uuid.uuid4())[:8].upper()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                INSERT INTO families (family_code, admin_user_id) VALUES (?, ?)
            ''', (family_code, admin_user_id))
            family_id = cursor.lastrowid
            
            await db.execute('''
                UPDATE users SET family_id = ?, role = 'parent' WHERE user_id = ?
            ''', (family_id, admin_user_id))
            await db.commit()
            return family_code

    async def link_child_to_parent(self, user_id: int, family_code: str, role: str = 'child') -> bool:
        """Привязывает пользователя (ребенка или наблюдателя) к семье по коду[cite: 2, 3]."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT id FROM families WHERE family_code = ?", (family_code,))
            family = await cursor.fetchone()
            if not family:
                return False
                
            await db.execute('''
                UPDATE users SET family_id = ?, role = ? WHERE user_id = ?
            ''', (family[0], role, user_id))
            await db.commit()
            return True

    async def set_child_class_and_group(self, user_id: int, class_id: str, group_id: str) -> None:
        """Задает класс и группу ребенка (с маркером 'ALL' для всего класса)[cite: 2, 3]."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                UPDATE users SET class_id = ?, group_id = ? WHERE user_id = ?
            ''', (class_id, group_id, user_id))
            await db.commit()

    async def set_child_notifications_lock(self, parent_user_id: int, child_user_id: int, locked: bool) -> bool:
        """Блокировка изменения настроек уведомлений ребенком (родительский контроль)[cite: 2, 7]."""
        async with aiosqlite.connect(self.db_path) as db:
            # Проверка, что родитель и ребенок в одной семье
            cursor = await db.execute('''
                SELECT u1.family_id FROM users u1
                JOIN users u2 ON u1.family_id = u2.family_id
                WHERE u1.user_id = ? AND u2.user_id = ? AND u1.role = 'parent'
            ''', (parent_user_id, child_user_id))
            
            if not await cursor.fetchone():
                return False

            await db.execute('''
                UPDATE users SET parent_control_notifications = ? WHERE user_id = ?
            ''', (int(locked), child_user_id))
            await db.commit()
            return True