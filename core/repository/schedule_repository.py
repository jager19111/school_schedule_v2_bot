import aiosqlite
import logging
from typing import List, Dict, Any
import datetime
from core.models.domain import LessonInstance
from core.nika.fetcher import ScheduleFetcher
from core.nika.normalizer import NikaNormalizer

logger = logging.getLogger(__name__)

class ScheduleRepository:
    def __init__(self, db_path: str, proxy: str = None):
        self.db_path = db_path
        self.fetcher = ScheduleFetcher(proxy=proxy)

    async def get_metadata(self) -> Dict[str, Any]:
            """Извлекает справочники классов и групп из последнего кэша NIKA."""
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("SELECT content FROM raw_nika_cache ORDER BY id DESC LIMIT 1")
                row = await cursor.fetchone()
                if not row:
                    logger.warning("Кэш NIKA пуст.")
                    return {"classes": {}, "groups": {}}
                    
                try:
                    # Используем встроенный метод fetcher'а для извлечения JSON
                    json_dict = self.fetcher._extract_json_from_js(row[0])
                    normalizer = NikaNormalizer(json_dict)
                    classes, teachers, rooms, subjects = normalizer.build_metadata()
                    
                    return {
                        "classes": classes,
                        "groups": json_dict.get("CLASSGROUPS", {})
                    }
                except Exception as e:
                    logger.error(f"Ошибка получения метаданных: {e}")
                    return {"classes": {}, "groups": {}}
                
    async def refresh_from_remote(self, target_dates: List[datetime.date]) -> None:
        """Загружает NIKA, сохраняет сырой дамп и выполняет UPSERT расписания[cite: 1, 2]."""
        try:
            js_content, nika_data = await self.fetcher.fetch()
            
            async with aiosqlite.connect(self.db_path) as db:
                # 1. Сохранение сырого дампа для дебага[cite: 2, 4]
                await db.execute("INSERT INTO raw_nika_cache (content) VALUES (?)", (js_content,))
                
                # 2. Очистка старых дампов (защита от переполнения БД)[cite: 2, 4]
                await db.execute("DELETE FROM raw_nika_cache WHERE fetched_at <= date('now', '-7 days')")
                
                # 3. Нормализация данных
                normalizer = NikaNormalizer(nika_data)
                lessons = normalizer.build_class_lessons(target_dates)
                
                # 4. UPSERT расписания. Используем COALESCE для сохранения статуса 
                # флагов уведомлений, если запись уже существует[cite: 1, 4].
                for lesson in lessons:
                    await db.execute('''
                        INSERT OR REPLACE INTO schedule_cache 
                        (id, date, period_id, class_id, lesson_num, group_id, 
                         subject_id, subject_name, teacher_id, teacher_name, 
                         room_id, room_name, start_time, end_time, 
                         is_exchange, is_cancelled, is_notified, is_change_notified, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 
                            COALESCE((SELECT is_notified FROM schedule_cache WHERE id = ?), 0),
                            COALESCE((SELECT is_change_notified FROM schedule_cache WHERE id = ?), 0),
                            CURRENT_TIMESTAMP
                        )
                    ''', (
                        lesson.id, lesson.date, lesson.period_id, lesson.class_id, lesson.lesson_num, 
                        lesson.group_id, lesson.subject_id, lesson.subject_name, lesson.teacher_id, 
                        lesson.teacher_name, lesson.room_id, lesson.room_name, lesson.start_time, 
                        lesson.end_time, int(lesson.is_exchange), int(lesson.is_cancelled), 
                        lesson.id, lesson.id
                    ))
                await db.commit()
                logger.info(f"✅ Расписание обновлено. Обработано {len(lessons)} уроков.")
        except Exception as e:
            logger.error(f"❌ Ошибка обновления расписания из NIKA: {e}")
            raise

    async def get_lessons_for_class(self, class_id: str, date_iso: str) -> List[Dict[str, Any]]:
        """Извлекает расписание класса на конкретную дату без десериализации JSON[cite: 2, 4]."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('''
                SELECT * FROM schedule_cache 
                WHERE class_id = ? AND date = ? 
                ORDER BY lesson_num
            ''', (class_id, date_iso))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]