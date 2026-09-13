-- Миграция Этапа 3: полная поддержка original_*, origin, weekday,
-- is_methodological и расписания учителей в schedule_cache.
--
-- ВАЖНО: после применения миграции требуется полная пересборка кэша,
-- чтобы teacher-уроки попали в БД. Старые строки получат
-- origin='class' (DEFAULT), но останутся без original_* / class_name,
-- пока NIKA semantic hash не изменится ИЛИ coverage не сдвинется.
-- Для немедленной пересборки выполните в конце:
--  DELETE FROM schedule_cache;
--  DELETE FROM raw_nika_cache;
--  DELETE FROM nika_source_state;
-- (следующий refresh_if_changed пересоберёт кэш из raw_nika_cache
--  по причине coverage mismatch / schedule rebuild).

-- 1. Origin: разделение class/teacher уроков в одной таблице
ALTER TABLE schedule_cache ADD COLUMN origin TEXT NOT NULL DEFAULT 'class';

-- 2. День недели (1-7, ISO): нужен рендереру без пересчёта из даты
ALTER TABLE schedule_cache ADD COLUMN weekday INTEGER;

-- 3. Имя класса (для расписания учителей: какой класс ведёт учитель)
ALTER TABLE schedule_cache ADD COLUMN class_name TEXT;

-- 4. Поля «было → стало» при заменах и отменах
ALTER TABLE schedule_cache ADD COLUMN original_subject_id TEXT;
ALTER TABLE schedule_cache ADD COLUMN original_subject_name TEXT;
ALTER TABLE schedule_cache ADD COLUMN original_teacher_id TEXT;
ALTER TABLE schedule_cache ADD COLUMN original_teacher_name TEXT;
ALTER TABLE schedule_cache ADD COLUMN original_room_id TEXT;
ALTER TABLE schedule_cache ADD COLUMN original_room_name TEXT;

-- 5. Оригинальный класс (перестановка учителя на другой класс)
ALTER TABLE schedule_cache ADD COLUMN original_class_id TEXT;
ALTER TABLE schedule_cache ADD COLUMN original_class_name TEXT;

-- 6. Оригинальная группа (замена состава групп)
ALTER TABLE schedule_cache ADD COLUMN original_group_id TEXT;
ALTER TABLE schedule_cache ADD COLUMN original_group_name TEXT;

-- 7. Методический час/день (только teacher-origin)
ALTER TABLE schedule_cache ADD COLUMN is_methodological INTEGER NOT NULL DEFAULT 0
    CHECK (is_methodological IN (0, 1));

-- 8. Backfill weekday для существующих строк (SQLite %w: 0=вс..6=сб → ISO 1..7)
UPDATE schedule_cache
SET weekday = (CAST(strftime('%w', date) AS INTEGER) + 6) % 7 + 1
WHERE weekday IS NULL;

-- 9. Индексы с учётом origin (заменяют собой idx_schedule_date_class
--    и idx_schedule_date_teacher, которые можно удалить)
DROP INDEX IF EXISTS idx_schedule_date_class;
DROP INDEX IF EXISTS idx_schedule_date_teacher;

CREATE INDEX IF NOT EXISTS idx_schedule_class_day_origin
ON schedule_cache(date, class_id, origin);

CREATE INDEX IF NOT EXISTS idx_schedule_teacher_day_origin
ON schedule_cache(date, teacher_id, origin);

-- 10. Обновлённый частичный индекс под pending changes (RAM-бомба):
--     не должен тянуть teacher-методические строки в выдачу классов
DROP INDEX IF EXISTS idx_schedule_pending_changes;
CREATE INDEX IF NOT EXISTS idx_schedule_pending_changes
ON schedule_cache(date, class_id)
WHERE (is_exchange = 1 OR is_cancelled = 1) AND origin = 'class';

-- 11. Поднимаем версию схемы (подставьте актуальную SCHEMA_VERSION + 1)
-- PRAGMA user_version = <N>;

-- 12. ОПЦИОНАЛЬНО (см. комментарий в шапке): форсировать полную
--     пересборку кэша немедленно.
-- DELETE FROM schedule_cache;
