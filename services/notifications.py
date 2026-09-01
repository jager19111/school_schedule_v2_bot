import logging
import datetime
from zoneinfo import ZoneInfo
import aiosqlite
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self, bot: Bot, db_path: str, timezone: str = "Asia/Novosibirsk"):
        self.bot = bot
        self.db_path = db_path
        self.tz = ZoneInfo(timezone)

    async def send_pre_lesson_reminders(self) -> None:
        """
        Предурочные оповещения. Проверяет дельту времени до начала урока.
        Запускается каждые 5 минут. Защита от дублей через is_notified[cite: 1, 4].
        """
        now = datetime.datetime.now(self.tz)
        today_iso = now.date().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Получаем активные уроки на сегодня[cite: 4]
            cursor = await db.execute('''
                SELECT id, class_id, group_id, start_time, subject_name, room_name 
                FROM schedule_cache 
                WHERE date = ? AND is_cancelled = 0 AND is_notified = 0
            ''', (today_iso,))
            lessons = await cursor.fetchall()

            for lesson in lessons:
                # Преобразуем строковое время "08:15" в timezone-aware datetime[cite: 4, 7]
                start_time_str = lesson['start_time']
                lesson_dt = datetime.datetime.strptime(f"{today_iso} {start_time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=self.tz)
                
                delta_minutes = (lesson_dt - now).total_seconds() / 60.0

                # Находим пользователей этого класса и группы, чье окно <= delta_minutes
                # и кто включил уведомления[cite: 2, 4]
                user_cursor = await db.execute('''
                    SELECT user_id, pre_lesson_offset_minutes 
                    FROM users 
                    WHERE class_id = ? AND (group_id = ? OR group_id = 'ALL' OR ? = 'ALL')
                      AND is_notifications_enabled = 1
                ''', (lesson['class_id'], lesson['group_id'], lesson['group_id']))
                
                users = await user_cursor.fetchall()
                notified_any = False

                for user in users:
                    # Проверяем попадание в динамическое окно (0 < delta <= N)[cite: 4, 5]
                    if 0 < delta_minutes <= user['pre_lesson_offset_minutes']:
                        msg = f"🔔 Урок {lesson['subject_name']} начнется в {start_time_str} (каб. {lesson['room_name']})"
                        try:
                            await self.bot.send_message(user['user_id'], msg)
                            notified_any = True
                        except Exception as e:
                            logger.error(f"Ошибка отправки пользователю {user['user_id']}: {e}")

                if notified_any:
                    # Флаг предотвращает повторную отправку при следующем тике планировщика[cite: 4, 7]
                    await db.execute("UPDATE schedule_cache SET is_notified = 1 WHERE id = ?", (lesson['id'],))
                    
            await db.commit()

    async def send_upcoming_changes(self) -> None:
        """
        Рассылка замен и отмен. Отправляется только если дата урока попадает 
        в окно changes_window_days пользователя[cite: 1, 5].
        """
        now = datetime.datetime.now(self.tz)
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Ищем отложенные уведомления о заменах и отменах[cite: 5]
            cursor = await db.execute('''
                SELECT id, date, class_id, group_id, lesson_num, subject_name, is_cancelled 
                FROM schedule_cache 
                WHERE (is_exchange = 1 OR is_cancelled = 1) AND is_change_notified = 0
            ''')
            changes = await cursor.fetchall()

            for change in changes:
                change_date = datetime.datetime.strptime(change['date'], "%Y-%m-%d").date()
                
                # Ищем пользователей, в чье окно (N дней) попадает это изменение[cite: 3, 5]
                user_cursor = await db.execute('''
                    SELECT user_id, changes_window_days 
                    FROM users 
                    WHERE class_id = ? AND (group_id = ? OR group_id = 'ALL' OR ? = 'ALL')
                      AND is_notifications_enabled = 1
                ''', (change['class_id'], change['group_id'], change['group_id']))
                
                users = await user_cursor.fetchall()
                notified_any = False

                for user in users:
                    max_date = now.date() + datetime.timedelta(days=user['changes_window_days'])
                    
                    # Окно фильтрации: от сегодня до today + changes_window_days[cite: 1, 5]
                    if now.date() <= change_date <= max_date:
                        status = "🚫 ОТМЕНЕН" if change['is_cancelled'] else "🔄 ИЗМЕНЕН"
                        msg = f"❗️ Внимание! {change['date']} урок №{change['lesson_num']} ({change['subject_name']}) {status}."
                        try:
                            await self.bot.send_message(user['user_id'], msg)
                            notified_any = True
                        except Exception:
                            pass
                
                if notified_any:
                    # Обновляем флаг, чтобы исключить дубли при следующем тике (через 45 минут)[cite: 5, 7]
                    await db.execute("UPDATE schedule_cache SET is_change_notified = 1 WHERE id = ?", (change['id'],))
            
            await db.commit()