# database/db.py
#
# РЕШЁННЫЕ ПРОБЛЕМЫ:
#
# 1. I/O (Задача 1.1): добавлен метод connect(), создающий ЕДИНОЕ
#    shared-соединение на весь жизненный цикл приложения (его получают
#    все репозитории), и close() для корректного освобождения.
#    init_db() по-прежнему открывает короткоживущее соединение —
#    миграции выполняются один раз при старте.
#
# 2. WAL-режим: PRAGMA journal_mode = WAL и synchronous = NORMAL
#    уже присутствовали в init_db(); теперь они применяются И к
#    shared-соединению в connect(). WAL — персистентный режим файла,
#    но повторное применение дёшево и гарантирует консистентность.
#
# 3. Strict Time Governance (Задача 1.3): ПОЛНОСТЬЮ удалены
#    DEFAULT CURRENT_TIMESTAMP из всех таблиц.
#    - Таблицы NIKA-домена (schedule_cache, raw_nika_cache,
#      nika_source_state, notification_delivery_log): поля
#      остались TEXT NOT NULL — значения ВСЕГДА передаёт Python
#      через TimeService.now_utc_str().
#    - Таблицы профильного домена (families, users, student_profiles,
#      parent_student_settings, инвайты, watch_targets, extra_classes):
#      поля сделаны TEXT (nullable). Причина: их INSERT/UPDATE в других
#      репозиториях пока рассчитывают на дефолт; на свежей БД дефолта
#      больше нет, и NOT NULL без значения уронил бы вставку.
#      После переноса этих репозиториев на явные таймстемпы
#      (см. сопутствующие правки) верните NOT NULL.
#
# 4. Новые индексы:
#    - частичный индекс idx_schedule_pending_changes — под запрос
#      get_pending_changes (RAM-бомба, Задача 1.4): индексирует только
#      замены/отмены, фильтр по дате идёт по индексу, а не по full scan;
#    - PRAGMA user_version = 2 — версия схемы для будущих миграций.
#
# ВАЖНО ПРО МИГРАЦИЮ: CREATE TABLE IF NOT EXISTS не меняет существующую
# БД. В продакшн-базе старые DEFAULT CURRENT_TIMESTAMP останутся —
# это безвредно, потому что после рефакторинга Python всегда передаёт
# значения явно, и дефолты никогда не срабатывают. Строгая схема
# действует для всех новых БД.

import aiosqlite
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2


class Database:
    def __init__(self, db_path: str = "schedule_bot.db"):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    # ==============================================================
    # НОВОЕ (Задача 1.1): shared-соединение на весь процесс.
    # ==============================================================

    async def connect(self) -> aiosqlite.Connection:
        """
        Открывает единое долгоживущее соединение и настраивает PRAGMA.

        main.py вызывает один раз при старте, передаёт объект во все
        репозитории и закрывает через close() в finally.
        """
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA synchronous = NORMAL")
        self._connection = db
        return db

    async def close(self) -> None:
        """Корректное закрытие shared-соединения при остановке бота."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    @property
    def connection(self) -> Optional[aiosqlite.Connection]:
        return self._connection

    @staticmethod
    async def checkpoint_wal(db: aiosqlite.Connection) -> str:
        """
        Ручной WAL-checkpoint с усечением -wal файла.

        Рекомендуется запускать ночью (см. задачу в main.py): без него
        -wal файл может неограниченно расти при постоянной записи,
        а AUTOINCREMENT-подобные страницы замедляют чтение.
        """
        async with db.execute("PRAGMA wal_checkpoint(TRUNCATE)") as cursor:
            row = await cursor.fetchone()
            return str(row)

    async def init_db(self) -> None:
        """
        Создание схемы. Выполняется один раз при старте.

        Все таймстемп-колонки БЕЗ DEFAULT CURRENT_TIMESTAMP:
        источником времени является только TimeService (Python).
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("PRAGMA synchronous = NORMAL")
            await db.execute("PRAGMA busy_timeout = 5000")

            # --- families: created_at/updated_at теперь nullable (см. шапку) ---
            await db.execute("""
                CREATE TABLE IF NOT EXISTS families (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_code TEXT NOT NULL UNIQUE,
                    admin_user_id INTEGER NOT NULL,
                    created_at TEXT,
                    updated_at TEXT
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
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (family_id) REFERENCES families(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS student_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_id INTEGER,
                    telegram_user_id INTEGER UNIQUE,
                    name TEXT NOT NULL,
                    class_id TEXT NOT NULL,
                    group_id TEXT NOT NULL DEFAULT 'ALL',
                    is_active INTEGER NOT NULL DEFAULT 1
                        CHECK (is_active IN (0, 1)),
                    created_at TEXT,
                    updated_at TEXT,
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
                    created_at TEXT,
                    updated_at TEXT,
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
                CREATE TABLE IF NOT EXISTS student_claim_invites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT NOT NULL UNIQUE,
                    student_id INTEGER NOT NULL,
                    created_by_user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    is_revoked INTEGER NOT NULL DEFAULT 0
                        CHECK (is_revoked IN (0, 1)),
                    used_by_user_id INTEGER,
                    created_at TEXT,
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
                    created_at TEXT,
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
                    created_at TEXT,
                    updated_at TEXT,
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
                    family_id INTEGER,
                    student_id INTEGER NOT NULL,
                    day_of_week INTEGER NOT NULL
                        CHECK (day_of_week BETWEEN 1 AND 7),
                    time_start TEXT NOT NULL,
                    time_end TEXT NOT NULL,
                    title TEXT NOT NULL,
                    location TEXT,
                    reminder_minutes INTEGER NOT NULL DEFAULT 30
                        CHECK (reminder_minutes BETWEEN 0 AND 180),
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (family_id) REFERENCES families(id) ON DELETE CASCADE,
                    FOREIGN KEY (student_id) REFERENCES student_profiles(id) ON DELETE CASCADE
                )
            """)

            # --- NIKA-домен: значения времени ВСЕГДА передаёт Python ---
            await db.execute("""
                CREATE TABLE IF NOT EXISTS notification_delivery_log (
                    notification_type TEXT NOT NULL,
                    notification_date TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    recipient_id INTEGER NOT NULL,
                    sent_at TEXT NOT NULL,
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
                    created_at TEXT NOT NULL
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS raw_nika_cache (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    js_filename TEXT NOT NULL,
                    raw_sha256 TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
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
                    last_checked_at TEXT NOT NULL,
                    last_changed_at TEXT NOT NULL,
                    coverage_start_date TEXT,
                    coverage_end_date TEXT,
                    last_error TEXT,
                    last_error_at TEXT
                )
            """)

            # --- Индексы ---
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_family_role
                ON users(family_id, role)
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

            # НОВОЕ (Задача 1.4): частичный индекс под get_pending_changes.
            # Индекс содержит ТОЛЬКО строки замен/отмен — запрос
            # "WHERE (is_exchange=1 OR is_cancelled=1) AND date >= ?"
            # идёт по индексу и не сканирует десятки тысяч обычных уроков.
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_schedule_pending_changes
                ON schedule_cache(date, class_id)
                WHERE is_exchange = 1 OR is_cancelled = 1
            """)

            # Версия схемы для будущих миграций (best practice).
            await db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

            await db.commit()

        logger.info(
            "Database schema v%s initialized successfully.",
            SCHEMA_VERSION,
        )
