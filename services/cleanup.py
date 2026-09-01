import logging
import aiosqlite

logger = logging.getLogger(__name__)

class UserCleanupJob:
    def __init__(self, db_path: str, dormant_days: int = 60):
        self.db_path = db_path
        self.dormant_days = dormant_days

    async def deactivate_dormant_users(self) -> None:
        """
        Отключает уведомления у пользователей, неактивных более N дней (soft deactivate).
        При отправке команды /start или любом взаимодействии подписка возобновляется автоматически (через last_active_at)[cite: 4, 5].
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(f'''
                    UPDATE users 
                    SET is_notifications_enabled = 0 
                    WHERE last_active_at <= date('now', '-{self.dormant_days} days')
                      AND is_notifications_enabled = 1
                ''')
                deactivated_count = cursor.rowcount
                await db.commit()
                
                if deactivated_count > 0:
                    logger.info(f"💤 Переведено в спящий режим неактивных пользователей: {deactivated_count}")
        except Exception as e:
            logger.error(f"Ошибка при очистке неактивных пользователей: {e}")