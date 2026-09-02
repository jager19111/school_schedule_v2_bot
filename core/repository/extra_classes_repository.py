# core/repository/extra_classes_repository.py
from __future__ import annotations

from typing import List, Dict, Any, Optional

import aiosqlite


class ExtraClassesRepository:
    """
    Репозиторий для работы с доп. занятиями (extra_classes).

    Только работа с БД: INSERT/SELECT/UPDATE/DELETE.
    Вся бизнес-логика (валидация времени, выбор дня и т.п.) — в сервисах/хендлерах.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    # ---------- CREATE ----------

    async def create_extra_class(
        self,
        *,
        user_id: int,
        family_id: Optional[int],
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
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO extra_classes
                    (family_id, user_id, day_of_week,
                     time_start, time_end, title, location, reminder_minutes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    family_id,
                    user_id,
                    day_of_week,
                    time_start,
                    time_end,
                    title,
                    location,
                    reminder_minutes,
                ),
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
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            if day_of_week is None:
                cursor = await db.execute(
                    """
                    SELECT id, family_id, user_id, day_of_week,
                           time_start, time_end, title, location, reminder_minutes
                    FROM extra_classes
                    WHERE user_id = ?
                    ORDER BY day_of_week, time_start
                    """,
                    (user_id,),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT id, family_id, user_id, day_of_week,
                           time_start, time_end, title, location, reminder_minutes
                    FROM extra_classes
                    WHERE user_id = ? AND day_of_week = ?
                    ORDER BY time_start
                    """,
                    (user_id, day_of_week),
                )

            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

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
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                DELETE FROM extra_classes
                WHERE id = ? AND user_id = ?
                """,
                (extra_id, user_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    # ---------- UPDATE (опционально) ----------

    async def update_extra_class(
        self,
        *,
        extra_id: int,
        user_id: int,
        day_of_week: Optional[int] = None, # <-- ДОБАВЛЕНО
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
        if location is not None:
            fields.append("location = ?")
            params.append(location)
        if reminder_minutes is not None:
            fields.append("reminder_minutes = ?")
            params.append(reminder_minutes)

        if not fields:
            return False

        params.extend([extra_id, user_id])

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"""
                UPDATE extra_classes
                SET {", ".join(fields)}
                WHERE id = ? AND user_id = ?
                """,
                params,
            )
            await db.commit()
            return cursor.rowcount > 0