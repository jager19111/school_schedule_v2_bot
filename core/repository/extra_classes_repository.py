# core/repository/extra_classes_repository.py
from __future__ import annotations

from typing import List, Dict, Any, Optional
import logging

from core.repository.base_repository import BaseRepository
from services.time_service import TimeService

logger = logging.getLogger(__name__)

class ExtraClassesRepository(BaseRepository):
    """
    Репозиторий для работы с доп. занятиями (extra_classes).

    Только работа с БД: INSERT/SELECT/UPDATE/DELETE.
    Вся бизнес-логика (валидация времени, выбор дня и т.п.) — в сервисах/хендлерах.
    """

    def __init__(self, db_path: str, time_service: TimeService):
        super().__init__(db_path, time_service)

    # ---------- CREATE ----------

    async def create_extra_class(
        self,
        *,
        user_id: int,
        day_of_week: int,
        time_start: str,
        time_end: str,
        title: str,
        location: Optional[str] = None,
        reminder_minutes: int = 30,
    ) -> int:
        """
        Создаёт доп. занятие и возвращает его id.
        """
        query = """
            INSERT INTO extra_classes (
                family_id,
                user_id,
                day_of_week,
                time_start,
                time_end,
                title,
                location,
                reminder_minutes
            )
            SELECT
                u.family_id,
                u.user_id,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            FROM users u
            WHERE u.user_id = ?
              AND u.role = 'child'
              AND u.family_id IS NOT NULL
        """
        params = (
            day_of_week,
            time_start,
            time_end,
            title,
            location,
            reminder_minutes,
            user_id,
        )

        async with self._connection() as db:
            cursor = await db.execute(query, params)

            if cursor.rowcount != 1:
                raise ValueError(
                    f"Cannot create extra class for child user_id={user_id}"
                )

            await db.commit()
            return cursor.lastrowid

    # ---------- READ ----------

    async def get_extra_classes_for_user(
        self,
        *,
        user_id: int,
        day_of_week: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает список доп. занятий ребёнка.
        Если day_of_week указан — фильтруем по нему, иначе возвращаем все.
        """
        if day_of_week is None:
            query = """
                SELECT id, family_id, user_id, day_of_week,
                       time_start, time_end, title, location, reminder_minutes
                FROM extra_classes
                WHERE user_id = ?
                ORDER BY day_of_week, time_start
            """
            return await self._fetch_all(query, (user_id,))
        else:
            query = """
                SELECT id, family_id, user_id, day_of_week,
                       time_start, time_end, title, location, reminder_minutes
                FROM extra_classes
                WHERE user_id = ? AND day_of_week = ?
                ORDER BY time_start
            """
            return await self._fetch_all(query, (user_id, day_of_week))

    # ---------- DELETE ----------

    async def delete_extra_class(
        self,
        *,
        extra_id: int,
        user_id: int,
    ) -> bool:
        """
        Удаляет доп. занятие по id, только если оно принадлежит user_id.
        Возвращает True, если что-то удалено.
        """
        query = """
            DELETE FROM extra_classes
            WHERE id = ? AND user_id = ?
        """
        rowcount = await self._execute(query, (extra_id, user_id))
        return rowcount > 0

    # ---------- UPDATE ----------

    async def update_extra_class(
        self,
        *,
        extra_id: int,
        user_id: int,
        day_of_week: Optional[int] = None,
        time_start: Optional[str] = None,
        time_end: Optional[str] = None,
        title: Optional[str] = None,
        location: Optional[str] = None,
        reminder_minutes: Optional[int] = None,
    ) -> bool:
        """
        Частичное обновление доп. занятия.
        Только владелец (user_id) может обновить запись.
        """
        fields = []
        params: list[Any] = []
        
        if day_of_week is not None:
            fields.append("day_of_week = ?")
            params.append(day_of_week)
        if time_start is not None:
            fields.append("time_start = ?")
            params.append(time_start)
        if time_end is not None:
            fields.append("time_end = ?")
            params.append(time_end)
        if title is not None:
            fields.append("title = ?")
            params.append(title)
# стоит использовать специальный sentinel _UNSET = object() и применять его для проверки, чтобы отличать "не передано" от "передано None". Но пока оставим так для добавления location и reminder_minutes, так как они могут быть None.

        if location is not None:
            fields.append("location = ?")
            params.append(location)
        if reminder_minutes is not None:
            fields.append("reminder_minutes = ?")
            params.append(reminder_minutes)

        if not fields:
            return False

        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.extend([extra_id, user_id])
        
        query = f"""
            UPDATE extra_classes
            SET {", ".join(fields)}
            WHERE id = ? AND user_id = ?
        """
        rowcount = await self._execute(query, tuple(params))
        return rowcount > 0