import aiosqlite
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "schedule_bot.db"):
        self.db_path = db_path

    async def init_db(self):
        """Инициализация денормализованных таблиц БД согласно ТЗ v2[cite: 1, 2]."""
        async with aiosqlite.connect(self.db_path) as db:
            # Таблица пользователей с полями настроек окон уведомлений[cite: 1, 4]
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL DEFAULT 'child',
                    family_id INTEGER,
                    class_id TEXT,
                    group_id TEXT,
                    teacher_id TEXT,
                    pre_lesson_offset_minutes INTEGER NOT NULL DEFAULT 15,
                    changes_window_days INTEGER NOT NULL DEFAULT 3,
                    parent_control_notifications INTEGER NOT NULL DEFAULT 0,
                    last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_notifications_enabled INTEGER NOT NULL DEFAULT 1,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица семей[cite: 1, 3]
            await db.execute('''
                CREATE TABLE IF NOT EXISTS families (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_code TEXT UNIQUE NOT NULL,
                    admin_user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Денормализованный кеш расписания. Первичный ключ 'id' формируется 
            # как period_id + class_id + date + lesson_num + group_id (с маркером "ALL")[cite: 2, 4].
            await db.execute('''
                CREATE TABLE IF NOT EXISTS schedule_cache (
                    id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    period_id TEXT NOT NULL,
                    class_id TEXT NOT NULL,
                    lesson_num INTEGER NOT NULL,
                    group_id TEXT NOT NULL,
                    subject_id TEXT,
                    subject_name TEXT, 
                    teacher_id TEXT,
                    teacher_name TEXT,
                    room_id TEXT,
                    room_name TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    is_exchange INTEGER NOT NULL DEFAULT 0,
                    is_cancelled INTEGER NOT NULL DEFAULT 0,
                    is_notified INTEGER NOT NULL DEFAULT 0,
                    is_change_notified INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Краткосрочный сырой кэш JS дампов[cite: 1, 3]
            await db.execute('''
                CREATE TABLE IF NOT EXISTS raw_nika_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    content TEXT NOT NULL
                )
            ''')
            
            # Таблица дополнительных занятий[cite: 1, 3]
            await db.execute('''
                CREATE TABLE IF NOT EXISTS extra_classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_id INTEGER,
                    user_id INTEGER,
                    day_of_week INTEGER NOT NULL,
                    time_start TEXT NOT NULL,
                    time_end TEXT NOT NULL,
                    title TEXT NOT NULL,
                    location TEXT,
                    reminder_minutes INTEGER NOT NULL DEFAULT 30
                )
            ''')

            # Индексы для ускорения выборок по датам и сущностям[cite: 2]
            await db.execute('CREATE INDEX IF NOT EXISTS idx_schedule_date_class ON schedule_cache(date, class_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_schedule_date_teacher ON schedule_cache(date, teacher_id)')
            
            await db.commit()
            logger.info("✅ Схема БД (v2) успешно инициализирована.")