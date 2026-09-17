# core/repository/extra_classes_repository.py
#
# ШАГ 2 плана рефакторинга: строгий контракт репозитория.
#
# ИЗМЕНЕНИЯ против предыдущей версии:
# 1. get_extra_classes_for_student -> list[ExtraClassItemDTO],
#    get_extra_class -> ExtraClassDTO | None: dict больше не покидает
#    контекст SQL-запроса. Маппинг — через ExtraClassMapper.
# 2. Список из 11 колонок, дублировавшийся в трёх SELECT,
#    вынесен в единую константу _EXTRA_CLASS_COLUMNS.
# 3. Сентинел location переименован в публичный UNSET — сервис
#    использует тот же объект, чтобы различать «не передано»
#    и «очистить поле».
#
# Сохранено (проверено, не требует правок):
# - Strict Time Governance: now_utc из TimeService, не из СУБД;
# - create_extra_class обёрнут в write-lock на shared-соединении;
# - DELETE/UPDATE защищены условием student_id (владение занятием).

from __future__ import annotations

from typing import Optional

from core.mappers.extra_class_mapper import ExtraClassMapper
from core.models.dto import ExtraClassDTO, ExtraClassItemDTO
from core.repository.base_repository import BaseRepository
from services.time_service import TimeService

# Сентинел «поле не передано».
# location=None -> очистить место занятия; location=UNSET -> не трогать.
UNSET = object()

_EXTRA_CLASS_COLUMNS = """
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
"""


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
        """Создаёт дополнительное занятие student profile. Возвращает id."""
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
    ) -> list[ExtraClassItemDTO]:
        """
        Занятия одного student profile.

        С day_of_week — занятия одного дня (горячий путь расписания
        и утренних сводок); без — весь список для экрана кружков.
        Возвращает строго list[ExtraClassItemDTO].
        """
        if day_of_week is None:
            query = f"""
            SELECT {_EXTRA_CLASS_COLUMNS}
            FROM extra_classes
            WHERE student_id = ?
            ORDER BY
                day_of_week,
                time_start,
                id
            """
            rows = await self._fetch_all(query, (student_id,))
        else:
            query = f"""
            SELECT {_EXTRA_CLASS_COLUMNS}
            FROM extra_classes
            WHERE student_id = ?
              AND day_of_week = ?
            ORDER BY
                time_start,
                id
            """
            rows = await self._fetch_all(query, (student_id, day_of_week))

        return ExtraClassMapper.to_item_list(rows)

    async def get_extra_class(
        self,
        *,
        extra_id: int,
        student_id: int,
    ) -> Optional[ExtraClassDTO]:
        """
        Одно занятие, только если оно принадлежит student_id.

        Нужен сервису для безопасной partial update и проверки
        итогового временного интервала. Возвращает ExtraClassDTO | None.
        """
        query = f"""
        SELECT {_EXTRA_CLASS_COLUMNS}
        FROM extra_classes
        WHERE id = ?
          AND student_id = ?
        """
        row = await self._fetch_one(query, (extra_id, student_id))
        return ExtraClassMapper.to_dto(row) if row is not None else None

    async def delete_extra_class(
        self,
        *,
        extra_id: int,
        student_id: int,
    ) -> bool:
        """Удаляет занятие только при совпадении extra id и student id."""
        rowcount = await self._execute(
            """
            DELETE FROM extra_classes
            WHERE id = ?
              AND student_id = ?
            """,
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
        location: Optional[str] | object = UNSET,
        reminder_minutes: Optional[int] = None,
    ) -> bool:
        """
        Частично обновляет занятие конкретного ученика.

        None = «поле не передано, не изменять».
        location дополнительно различает None (очистить) и UNSET
        (не трогать) — сервис передаёт тот же сентинел-объект.
        """
        fields: list[str] = []
        params: list[object] = []

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
        if location is not UNSET:
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
        params.extend([extra_id, student_id])

        query = f"""
        UPDATE extra_classes
        SET {", ".join(fields)}
        WHERE id = ?
          AND student_id = ?
        """
        rowcount = await self._execute(query, tuple(params))
        return rowcount > 0
