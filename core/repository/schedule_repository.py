import logging
from typing import List, Dict, Any
import datetime

from core.models.domain import LessonInstance
from core.nika.fetcher import ScheduleFetcher
from core.nika.normalizer import NikaNormalizer
from core.repository.base_repository import BaseRepository
from services.time_service import TimeService

logger = logging.getLogger(__name__)


class ScheduleRepository(BaseRepository):
    """
    Репозиторий расписания.

    - Использует BaseRepository для простых SELECT'ов.
    - Для сложного пайплайна refresh_from_remote() открывает транзакцию вручную.
    """

    def __init__(self, db_path: str, time_service: TimeService, proxy: str | None = None):
        super().__init__(db_path=db_path, time_service=time_service)
        self.fetcher = ScheduleFetcher(proxy=proxy)

    async def get_metadata(self) -> Dict[str, Any]:
        """
        Извлекает справочники классов, учителей и групп из последнего кэша NIKA.
        """
        # Берём последнюю запись из raw_nika_cache через обычный SELECT
        row = await self._fetch_one(
            "SELECT content FROM raw_nika_cache ORDER BY id DESC LIMIT 1"
        )
        if not row:
            logger.warning("Кэш NIKA пуст.")
            return {"classes": {}, "groups": {}, "teachers": {}}

        content = row.get("content")
        if not content:
            logger.warning("Последний raw_nika_cache.content пуст.")
            return {"classes": {}, "groups": {}, "teachers": {}}

        try:
            # Используем уже существующий метод ScheduleFetcher для извлечения JSON
            json_dict = self.fetcher._extract_json_from_js(content)
            normalizer = NikaNormalizer(json_dict)
            
            # Извлекаем все 4 справочника
            classes, teachers, rooms, subjects = normalizer.build_metadata()

            return {
                "classes": classes,
                "groups": json_dict.get("CLASSGROUPS", {}),
                "teachers": teachers,
                "class_shift": json_dict.get("CLASS_SHIFT", {}),         # <-- ДОБАВЛЕНО
                "second_relative": json_dict.get("SECOND_RELATIVE", False) # <-- ДОБАВЛЕНО
            }
        except Exception as e:
            logger.error(f"Ошибка получения метаданных: {e}")
            return {"classes": {}, "groups": {}, "teachers": {}}

    async def refresh_from_remote(self, target_dates: List[datetime.date]) -> None:
        """
        Загрузка NIKA, сохранение сырого дампа и UPSERT расписания.

        Здесь используем явную транзакцию, поэтому работаем через aiosqlite напрямую.
        """
        import aiosqlite  # локальный импорт, чтобы не тащить глобально

        try:
            js_content, nika_data = await self.fetcher.fetch()

            async with aiosqlite.connect(self.db_path) as db:
                # 1. Сырой дамп для дебага
                await db.execute(
                    "INSERT INTO raw_nika_cache (content, fetched_at) VALUES (?, CURRENT_TIMESTAMP)",
                    (js_content,),
                )

                # 2. Очистка старых дампов (>7 дней)
                await db.execute(
                    "DELETE FROM raw_nika_cache WHERE fetched_at <= date('now', '-7 days')"
                )

                # 3. Нормализация
                normalizer = NikaNormalizer(nika_data)
                lessons: List[LessonInstance] = normalizer.build_class_lessons(target_dates)

                # 4. UPSERT в schedule_cache с сохранением флагов нотификаций
                for lesson in lessons:
                    await db.execute(
                        """
                        INSERT OR REPLACE INTO schedule_cache 
                        (id, date, period_id, class_id, lesson_num, group_id, group_name,
                         subject_id, subject_name, teacher_id, teacher_name,
                         room_id, room_name, start_time, end_time,
                         is_exchange, is_cancelled,
                         is_notified, is_change_notified, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            COALESCE((SELECT is_notified FROM schedule_cache WHERE id = ?), 0),
                            COALESCE((SELECT is_change_notified FROM schedule_cache WHERE id = ?), 0),
                            CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            lesson.id, lesson.date, lesson.period_id, lesson.class_id,
                            lesson.lesson_num, lesson.group_id, lesson.group_name,  # <-- ДОБАВЛЕНО lesson.group_name
                            lesson.subject_id, lesson.subject_name, lesson.teacher_id, lesson.teacher_name,
                            lesson.room_id, lesson.room_name, lesson.start_time, lesson.end_time,
                            int(lesson.is_exchange), int(lesson.is_cancelled),
                            lesson.id, lesson.id
                        ),
                    )

                await db.commit()
                logger.info("✅ Расписание обновлено. Обработано %d уроков.", len(lessons))
        except Exception as e:
            logger.error("❌ Ошибка обновления расписания из NIKA: %s", e)
            raise

    async def get_lessons_for_class(self, class_id: str, date_iso: str) -> List[Dict[str, Any]]:
        """
        Извлекает расписание класса на конкретную дату.
        """
        return await self._fetch_all(
            """
            SELECT * FROM schedule_cache
            WHERE class_id = ? AND date = ?
            ORDER BY lesson_num
            """,
            (class_id, date_iso),
        )
        
    async def get_lessons_for_teacher(self, teacher_id: str, date_iso: str) -> List[Dict[str, Any]]:
        """Извлекает расписание учителя на конкретную дату."""
        return await self._fetch_all(
            """
            SELECT * FROM schedule_cache
            WHERE teacher_id = ? AND date = ?
            ORDER BY start_time, lesson_num
            """,
            (teacher_id, date_iso),
        )