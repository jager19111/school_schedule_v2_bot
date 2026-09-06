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

            await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("PRAGMA synchronous = NORMAL")
            await db.execute("PRAGMA busy_timeout = 5000")
            
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

                    receive_schedule_changes INTEGER NOT NULL DEFAULT 1
                        CHECK (receive_schedule_changes IN (0, 1)),

                    receive_extra_class_reminders INTEGER NOT NULL DEFAULT 1
                        CHECK (receive_extra_class_reminders IN (0, 1)),

                    changes_window_days INTEGER NOT NULL DEFAULT 3
                        CHECK (changes_window_days BETWEEN 0 AND 31),

                    global_extra_reminder INTEGER NOT NULL DEFAULT 30
                        CHECK (global_extra_reminder BETWEEN 0 AND 180),

                    can_manage_own_extra_classes INTEGER NOT NULL DEFAULT 1
                        CHECK (can_manage_own_extra_classes IN (0, 1)),

                    last_active_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (family_id) REFERENCES families(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS student_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    family_id INTEGER NOT NULL,

                    telegram_user_id INTEGER UNIQUE,

                    name TEXT NOT NULL,

                    class_id TEXT NOT NULL,
                    group_id TEXT NOT NULL DEFAULT 'ALL',

                    is_active INTEGER NOT NULL DEFAULT 1
                        CHECK (is_active IN (0, 1)),

                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (family_id)
                        REFERENCES families(id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (telegram_user_id)
                        REFERENCES users(user_id)
                        ON DELETE SET NULL
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_student_profiles_family
                ON student_profiles(
                    family_id,
                    is_active
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_student_profiles_telegram
                ON student_profiles(telegram_user_id)
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS parent_student_settings (
                    parent_user_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,

                    receive_morning_summary INTEGER NOT NULL DEFAULT 1
                        CHECK (receive_morning_summary IN (0, 1)),

                    receive_pre_lesson_reminders INTEGER NOT NULL DEFAULT 1
                        CHECK (receive_pre_lesson_reminders IN (0, 1)),

                    receive_schedule_changes INTEGER NOT NULL DEFAULT 1
                        CHECK (receive_schedule_changes IN (0, 1)),

                    receive_extra_class_reminders INTEGER NOT NULL DEFAULT 1
                        CHECK (receive_extra_class_reminders IN (0, 1)),

                    child_notification_settings_locked INTEGER NOT NULL DEFAULT 0
                        CHECK (
                            child_notification_settings_locked IN (0, 1)
                        ),

                    can_manage_extra_classes INTEGER NOT NULL DEFAULT 0
                        CHECK (can_manage_extra_classes IN (0, 1)),

                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    PRIMARY KEY (
                        parent_user_id,
                        student_id
                    ),

                    FOREIGN KEY (parent_user_id)
                        REFERENCES users(user_id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (student_id)
                        REFERENCES student_profiles(id)
                        ON DELETE CASCADE
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_parent_student_parent
                ON parent_student_settings(parent_user_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_parent_student_student
                ON parent_student_settings(student_id)
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
                    can_manage_extra_classes INTEGER NOT NULL DEFAULT 0
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
                CREATE TABLE IF NOT EXISTS student_claim_invites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    token TEXT NOT NULL UNIQUE,

                    student_id INTEGER NOT NULL,
                    created_by_user_id INTEGER NOT NULL,

                    expires_at TEXT NOT NULL,

                    is_revoked INTEGER NOT NULL DEFAULT 0
                        CHECK (is_revoked IN (0, 1)),

                    used_by_user_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    used_at TEXT,

                    FOREIGN KEY (student_id)
                        REFERENCES student_profiles(id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (created_by_user_id)
                        REFERENCES users(user_id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (used_by_user_id)
                        REFERENCES users(user_id)
                        ON DELETE SET NULL
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_student_claim_invites_student
                ON student_claim_invites(
                    student_id,
                    is_revoked,
                    expires_at
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS family_invites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    token TEXT NOT NULL UNIQUE,

                    family_id INTEGER NOT NULL,
                    created_by_user_id INTEGER NOT NULL,

                    intended_role TEXT NOT NULL
                        CHECK (
                            intended_role IN (
                                'child',
                                'parent',
                                'observer'
                            )
                        ),

                    expires_at TEXT NOT NULL,

                    max_uses INTEGER NOT NULL DEFAULT 1
                        CHECK (max_uses BETWEEN 1 AND 10),

                    uses_count INTEGER NOT NULL DEFAULT 0
                        CHECK (uses_count >= 0),

                    is_revoked INTEGER NOT NULL DEFAULT 0
                        CHECK (is_revoked IN (0, 1)),

                    used_by_user_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    used_at TEXT,

                    FOREIGN KEY (family_id)
                        REFERENCES families(id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (created_by_user_id)
                        REFERENCES users(user_id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (used_by_user_id)
                        REFERENCES users(user_id)
                        ON DELETE SET NULL
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_family_invites_token
                ON family_invites(token)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_family_invites_family_active
                ON family_invites(
                    family_id,
                    is_revoked,
                    expires_at
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS schedule_watch_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    owner_user_id INTEGER NOT NULL,

                    class_id TEXT NOT NULL,
                    group_id TEXT NOT NULL DEFAULT 'ALL',

                    title TEXT,

                    is_enabled INTEGER NOT NULL DEFAULT 1
                        CHECK (is_enabled IN (0, 1)),
                    receive_schedule_changes INTEGER NOT NULL DEFAULT 1
                        CHECK (receive_schedule_changes IN (0, 1)),
                        
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (owner_user_id)
                        REFERENCES users(user_id)
                        ON DELETE CASCADE,

                    UNIQUE (
                        owner_user_id,
                        class_id,
                        group_id
                    )
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_watch_targets_owner
                ON schedule_watch_targets(
                    owner_user_id,
                    is_enabled
                )
            """)
                        
            await db.execute("""
                CREATE TABLE IF NOT EXISTS extra_classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    
                    family_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,

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
                    FOREIGN KEY (student_id) REFERENCES student_profiles(id) ON DELETE CASCADE
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
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS raw_nika_cache (
                    id INTEGER PRIMARY KEY CHECK (id = 1),

                    js_filename TEXT NOT NULL,
                    raw_sha256 TEXT NOT NULL,

                    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    content TEXT NOT NULL
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS nika_source_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),

                    js_filename TEXT NOT NULL,
                    export_date TEXT,
                    export_time TEXT,

                    raw_sha256 TEXT NOT NULL,
                    semantic_sha256 TEXT NOT NULL,

                    last_checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    coverage_start_date TEXT,
                    coverage_end_date TEXT,

                    last_error TEXT,
                    last_error_at TEXT
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
                CREATE INDEX IF NOT EXISTS idx_extra_classes_student_day
                ON extra_classes(student_id, day_of_week, time_start);
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_notification_delivery_log_date
                ON notification_delivery_log(notification_date)
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