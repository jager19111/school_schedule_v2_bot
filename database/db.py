import aiosqlite
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "schedule_bot.db"):
        self.db_path = db_path

    async def init_db(self) -> None:
        """
        Создаёт чистую схему v2.

        Внимание: CREATE TABLE IF NOT EXISTS не меняет существующую таблицу.
        Для перехода на эту схему в тестовой среде удалите старый SQLite-файл
        до первого запуска.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS families (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_code TEXT NOT NULL UNIQUE,
                    admin_user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    name TEXT,
                    role TEXT NOT NULL DEFAULT 'child'
                        CHECK (role IN ('child', 'parent', 'observer', 'teacher')),
                    family_id INTEGER,
                    class_id TEXT,
                    group_id TEXT,
                    teacher_id TEXT,

                    is_notifications_enabled INTEGER NOT NULL DEFAULT 1
                        CHECK (is_notifications_enabled IN (0, 1)),
                    morning_summary_time TEXT,
                    pre_lesson_offset_minutes INTEGER NOT NULL DEFAULT 10
                        CHECK (pre_lesson_offset_minutes BETWEEN 0 AND 180),
                    changes_window_days INTEGER NOT NULL DEFAULT 3
                        CHECK (changes_window_days BETWEEN 0 AND 31),
                    global_extra_reminder INTEGER NOT NULL DEFAULT 30
                        CHECK (global_extra_reminder BETWEEN 0 AND 180),

                    last_active_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (family_id) REFERENCES families(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS parent_child_settings (
                    parent_id INTEGER NOT NULL,
                    child_id INTEGER NOT NULL,

                    receive_morning_summary INTEGER NOT NULL DEFAULT 1
                        CHECK (receive_morning_summary IN (0, 1)),
                    receive_pre_lesson_reminders INTEGER NOT NULL DEFAULT 1
                        CHECK (receive_pre_lesson_reminders IN (0, 1)),
                    receive_schedule_changes INTEGER NOT NULL DEFAULT 1
                        CHECK (receive_schedule_changes IN (0, 1)),
                    receive_extra_class_reminders INTEGER NOT NULL DEFAULT 1
                        CHECK (receive_extra_class_reminders IN (0, 1)),

                    child_notification_settings_locked INTEGER NOT NULL DEFAULT 0
                        CHECK (child_notification_settings_locked IN (0, 1)),
                    can_manage_extra_classes INTEGER NOT NULL DEFAULT 1
                        CHECK (can_manage_extra_classes IN (0, 1)),

                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    PRIMARY KEY (parent_id, child_id),
                    CHECK (parent_id <> child_id),

                    FOREIGN KEY (parent_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (child_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS extra_classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,

                    day_of_week INTEGER NOT NULL
                        CHECK (day_of_week BETWEEN 1 AND 7),
                    time_start TEXT NOT NULL,
                    time_end TEXT NOT NULL,
                    title TEXT NOT NULL,
                    location TEXT,
                    reminder_minutes INTEGER NOT NULL DEFAULT 30
                        CHECK (reminder_minutes BETWEEN 0 AND 180),

                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (family_id) REFERENCES families(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS notification_delivery_log (
                    notification_type TEXT NOT NULL,
                    notification_date TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    recipient_id INTEGER NOT NULL,

                    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    PRIMARY KEY (
                        notification_type,
                        notification_date,
                        source_id,
                        recipient_id
                    ),

                    FOREIGN KEY (recipient_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS schedule_cache (
                    id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    period_id TEXT NOT NULL,
                    class_id TEXT NOT NULL,
                    lesson_num INTEGER NOT NULL,
                    group_id TEXT NOT NULL,
                    group_name TEXT,
                    subject_id TEXT,
                    subject_name TEXT,
                    teacher_id TEXT,
                    teacher_name TEXT,
                    room_id TEXT,
                    room_name TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    is_exchange INTEGER NOT NULL DEFAULT 0
                        CHECK (is_exchange IN (0, 1)),
                    is_cancelled INTEGER NOT NULL DEFAULT 0
                        CHECK (is_cancelled IN (0, 1)),
                    is_notified INTEGER NOT NULL DEFAULT 0
                        CHECK (is_notified IN (0, 1)),
                    is_change_notified INTEGER NOT NULL DEFAULT 0
                        CHECK (is_change_notified IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS raw_nika_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    content TEXT NOT NULL
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_family_role
                ON users(family_id, role)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_parent_child_settings_parent
                ON parent_child_settings(parent_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_parent_child_settings_child
                ON parent_child_settings(child_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_extra_classes_day_user
                ON extra_classes(day_of_week, user_id, time_start)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_schedule_date_class
                ON schedule_cache(date, class_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_schedule_date_teacher
                ON schedule_cache(date, teacher_id)
            """)

            await db.commit()

        logger.info("Database schema v2 initialized successfully.")