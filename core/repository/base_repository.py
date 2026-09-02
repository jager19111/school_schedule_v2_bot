# core/repository/base_repository.py
from __future__ import annotations

import aiosqlite
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from services.time_service import TimeService

logger = logging.getLogger(__name__)


class BaseRepository:
    """
    Базовый репозиторий для aiosqlite.

    - Хранит общий db_path.
    - Даёт вспомогательные методы _fetch_one/_fetch_all/_execute.
    - Автоматически конвертирует поля *_at и явные DATETIME_FIELDS
      в aware UTC datetime с помощью TimeService.make_aware_utc().
    """

    # Явные datetime-поля, не оканчивающиеся на "_at" (если появятся)
    DATETIME_FIELDS: Set[str] = set()

    def __init__(self, db_path: str, time_service: TimeService):
        self.db_path = db_path
        self.time_service = time_service

    # ================== ВНУТРЕННЯЯ ОБРАБОТКА ==================

    def _process_row(self, row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Преобразует datetime-поля из БД в aware UTC datetime.

        Обрабатываются:
        - все поля, оканчивающиеся на '_at'
        - поля из DATETIME_FIELDS
        """
        if row is None:
            return None

        processed = dict(row)

        for key, value in processed.items():
            is_dt_field = key.endswith("_at") or key in self.DATETIME_FIELDS
            if not is_dt_field or value is None:
                continue

            # Если уже datetime — просто делаем aware UTC при необходимости
            if isinstance(value, datetime):
                processed[key] = self.time_service.make_aware_utc(value)
                continue

            # Если строка — пробуем разобрать ISO/SQLite формат
            if isinstance(value, str):
                try:
                    dt = datetime.fromisoformat(value)
                except ValueError:
                    logger.warning("Failed to parse datetime field %s=%r", key, value)
                    continue

                processed[key] = self.time_service.make_aware_utc(dt)

        return processed

    # ================== CRUD HELPERS ==================

    async def _fetch_one(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """
        Выполнить SELECT ... LIMIT 1 и вернуть dict с обработанными datetime.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            return self._process_row(dict(row)) if row else None

    async def _fetch_all(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """
        Выполнить SELECT и вернуть список dict с обработанными datetime.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            if not rows:
                return []
            return [self._process_row(dict(r)) for r in rows]

    async def _fetch_value(self, query: str, params: tuple = ()) -> Any:
        """
        Получить одно скалярное значение (COUNT, SUM и т.п.).
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            return row[0] if row is not None and len(row) > 0 else None

    async def _execute(self, query: str, params: tuple = ()) -> int:
        """
        Выполнить INSERT/UPDATE/DELETE и вернуть количество затронутых строк.
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(query, params)
            await db.commit()
            return cursor.rowcount

    async def _execute_many(self, query: str, params_list: List[tuple]) -> None:
        """
        Выполнить executemany для массовых операций.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany(query, params_list)
            await db.commit()