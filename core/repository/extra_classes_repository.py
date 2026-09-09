# core/repository/extra_classes_repository.py
#
# РЕШЁННЫЕ ПРОБЛЕМЫ:
#
# 1. Strict Time Governance: CURRENT_TIMESTAMP в update_extra_class
#    заменён на параметр now_utc из TimeService.
#
# 2. create_extra_class явно передаёт created_at/updated_at —
#    дефолтов в схеме больше нет.
#
# 3. INSERT обёрнут в self._write_lock(): на shared-соединении
#    запись сериализуется с транзакциями других репозиториев.

from __future__ import annotations

from typing import Any, Optional

from core.repository.base_repository import BaseRepository
from services.time_service import TimeService

_UNSET = object()


class ExtraClassesRepository(BaseRepository):
    """
    Репозиторий дополнительных занятий.

    Владелец занятия — student_profiles.id.
    Репозиторий не проверяет Telegram-права и семейные разрешения:
    это обязанность ExtraClassesService.
    """

    def __init__(
        self,
        db_path,
        time_service: TimeService,
    ) -> None:
        # db_path: aiosqlite.Connection (основной режим) или str (тесты).
        super().__init__(db_path, time_service)

    async def create_extra_class(
        self,
        *,
        family_id: int | None,
        student_id: int,
        day_of_week: int,
        time_start: str,
        time_end: str,
        title: str,
        location: Optional[str] = None,
        reminder_minutes: int = 30,
    ) -> int:
        """
        Создаёт дополнительное занятие конкретному student profile.
        """
        now_utc = self._now_utc_str()
        query = """
        INSERT INTO extra_classes (
            family_id,
            student_id,
            day_of_week,
            time_start,
            time_end,
            title,
            location,
            reminder_minutes,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            family_id,
            student_id,
            day_of_week,
            time_start,
            time_end,
            title,
            location,
            reminder_minutes,
            now_utc,
            now_utc,
        )
        async with self._write_lock():
            async with self._connection() as db:
                cursor = await db.execute(query, params)
                await db.commit()
                return cursor.lastrowid

    async def get_extra_classes_for_student(
        self,
        *,
        student_id: int,
        day_of_week: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Возвращает занятия одного student profile.
        Если указан day_of_week, возвращает занятия только на этот день.
        """
        if day_of_week is None:
            query = """
            SELECT
                id,
                family_id,
                student_id,
                day_of_week,
                time_start,
                time_end,
                title,
                location,
                reminder_minutes,
                created_at,
                updated_at
            FROM extra_classes
            WHERE student_id = ?
            ORDER BY
                day_of_week,
                time_start,
                id
            """
            return await self._fetch_all(
                query,
                (student_id,),
            )
        query = """
        SELECT
            id,
            family_id,
            student_id,
            day_of_week,
            time_start,
            time_end,
            title,
            location,
            reminder_minutes,
            created_at,
            updated_at
        FROM extra_classes
        WHERE student_id = ?
          AND day_of_week = ?
        ORDER BY
            time_start,
            id
        """
        return await self._fetch_all(
            query,
            (student_id, day_of_week),
        )

    async def get_extra_class(
        self,
        *,
        extra_id: int,
        student_id: int,
    ) -> Optional[dict[str, Any]]:
        """
        Возвращает одно занятие, только если оно принадлежит student_id.
        Метод нужен сервису для безопасной partial update и проверки
        итогового временного интервала.
        """
        query = """
        SELECT
            id,
            family_id,
            student_id,
            day_of_week,
            time_start,
            time_end,
            title,
            location,
            reminder_minutes,
            created_at,
            updated_at
        FROM extra_classes
        WHERE id = ?
          AND student_id = ?
        """
        return await self._fetch_one(
            query,
            (extra_id, student_id),
        )

    async def delete_extra_class(
        self,
        *,
        extra_id: int,
        student_id: int,
    ) -> bool:
        """
        Удаляет занятие только при совпадении extra id и student id.
        """
        query = """
        DELETE FROM extra_classes
        WHERE id = ?
          AND student_id = ?
        """
        rowcount = await self._execute(
            query,
            (extra_id, student_id),
        )
        return rowcount > 0

    async def update_extra_class(
        self,
        *,
        extra_id: int,
        student_id: int,
        day_of_week: Optional[int] = None,
        time_start: Optional[str] = None,
        time_end: Optional[str] = None,
        title: Optional[str] = None,
        location: Optional[str] | object = _UNSET,
        reminder_minutes: Optional[int] = None,
    ) -> bool:
        """
        Частично обновляет занятие конкретного ученика.

        location использует _UNSET, чтобы различать:
        - location не передан: не изменять поле;
        - location=None: очистить место занятия.
        """
        fields: list[str] = []
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
        if location is not _UNSET:
            fields.append("location = ?")
            params.append(location)
        if reminder_minutes is not None:
            fields.append("reminder_minutes = ?")
            params.append(reminder_minutes)

        if not fields:
            return False

        # Time Governance: updated_at из приложения.
        fields.append("updated_at = ?")
        params.append(self._now_utc_str())
        params.extend(
            [
                extra_id,
                student_id,
            ]
        )
        query = f"""
        UPDATE extra_classes
        SET {", ".join(fields)}
        WHERE id = ?
          AND student_id = ?
        """
        rowcount = await self._execute(
            query,
            tuple(params),
        )
        return rowcount > 0
