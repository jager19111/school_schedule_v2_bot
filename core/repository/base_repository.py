# core/repository/base_repository.py
#
# РЕШЁННЫЕ ПРОБЛЕМЫ:
#
# 1. I/O (Задача 1.1): репозиторий теперь работает через ЕДИНОЕ
#    shared-соединение, созданное в main.py и переданное через конструктор.
#    Раньше каждый _fetch_one/_execute открывал и закрывал собственный
#    aiosqlite.connect() — при сотнях пользователей и 4 фоновых джобах
#    это тысячи лишних открытий файлов, PRAGMA-вызовов и рисков
#    SQLITE_BUSY. Legacy-режим (строка пути) сохранён только для тестов.
#
# 2. Конкурентность: добавлен transaction() с общим asyncio.Lock на
#    физическое соединение. Все репозитории делят одно соединение,
#    поэтому BEGIN/COMMIT двух корутин обязаны быть сериализованы,
#    иначе транзакции "перехлёстываются" (вторая BEGIN упадёт с
#    "cannot start a transaction within a transaction" или молча
#    закоммитит чужую половину работы).
#
# 3. Strict Time Governance (Задача 1.3): добавлен хелпер _now_utc_str()
#    — все репозитории берут "сейчас" только отсюда, а не из СУБД.
#
# 4. Массовые операции (Задача 1.2): _execute_many использует
#    executemany + опциональный чанкинг, чтобы не держать в RAM
#    гигантский список и не растягивать транзакцию.
#
# ВАЖНО (правило использования):
# - внутри блока `async with self.transaction() as db:` работать ТОЛЬКО
#   с локальной переменной db (db.execute / db.executemany);
# - НЕ вызывать внутри transaction() методы _execute/_execute_many —
#   они сами захватывают общий lock и это приведёт к дедлоку.

from __future__ import annotations

import asyncio
import logging
import weakref
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Sequence

import aiosqlite

from services.time_service import TimeService

logger = logging.getLogger(__name__)

# Единый lock на каждое физическое соединение.
# WeakKeyDictionary: когда соединение закрывается и собирается GC,
# lock удаляется автоматически — утечек нет.
_TX_LOCKS: "weakref.WeakKeyDictionary[aiosqlite.Connection, asyncio.Lock]" = (
    weakref.WeakKeyDictionary()
)


def _get_tx_lock(db: aiosqlite.Connection) -> asyncio.Lock:
    """Возвращает (или создаёт) общий lock для конкретного соединения."""
    lock = _TX_LOCKS.get(db)
    if lock is None:
        lock = asyncio.Lock()
        _TX_LOCKS[db] = lock
    return lock


class BaseRepository:
    """
    Базовый репозиторий для aiosqlite.

    - Хранит shared-соединение (или db_path для legacy/тестов).
    - Даёт вспомогательные методы _fetch_one/_fetch_all/_execute/_execute_many.
    - Даёт transaction() — безопасная явная транзакция с блокировкой.
    - Автоматически конвертирует поля *_at и явные DATETIME_FIELDS
      в aware UTC datetime с помощью TimeService.make_aware_utc().
    """

    # Явные datetime-поля, не оканчивающиеся на "_at" (если появятся)
    DATETIME_FIELDS: Set[str] = set()

    def __init__(self, db_path, time_service: TimeService):
        """
        db_path может быть:
        - aiosqlite.Connection — основной режим (shared-соединение из main.py);
        - str — legacy-режим для тестов (открытие соединения на вызов).

        Имя параметра db_path сохранено ради обратной совместимости
        с конструкторами дочерних репозиториев, которые делают
        super().__init__(db_path=db_path, time_service=time_service).
        """
        self.time_service = time_service

        if isinstance(db_path, aiosqlite.Connection):
            # Основной режим: одно соединение на весь процесс (Задача 1.1).
            self.db: Optional[aiosqlite.Connection] = db_path
            self.db_path: Optional[str] = None
        else:
            # Legacy-режим: строка пути (тесты, утилиты).
            self.db = None
            self.db_path = db_path

    # ================== ВРЕМЯ (Задача 1.3) ==================

    def _now_utc_str(self) -> str:
        """
        Единственная точка получения "сейчас" для SQL.
        Полная замена CURRENT_TIMESTAMP: время генерирует приложение.
        Формат совпадает со старыми СУБД-строками, миграция не нужна.
        """
        return self.time_service.now_utc_str()

    # ================== ВНУТРЕННЯЯ ОБРАБОТКА ==================

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """
        Возвращает соединение для выполнения запроса.

        Shared-режим: соединение уже открыто в main.py (PRAGMA foreign_keys,
        busy_timeout, WAL, row_factory настроены там же) — просто отдаём его.
        Никаких open/close на каждый запрос: именно это было главным
        источником лишнего I/O.

        Legacy-режим: открываем на вызов (только для тестов).
        """
        if self.db is not None:
            yield self.db
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("PRAGMA busy_timeout = 5000")
            db.row_factory = aiosqlite.Row
            yield db

    def _write_lock(self) -> asyncio.Lock:
        """
        Lock для write-операций.

        Shared-режим: общий lock на соединение — сериализует write-ы
        всех репозиторов, работающих через это соединение.
        Legacy-режим: соединение создаётся на вызов, реальная
        конкурентность невозможна внутри одного вызова.
        """
        if self.db is not None:
            return _get_tx_lock(self.db)
        return asyncio.Lock()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """
        Явная транзакция с блокировкой (best practice для shared-соединения).

        Гарантии:
        - BEGIN -> (ваши запросы) -> COMMIT, либо ROLLBACK при любом исключении;
        - другие корутины не могут вклиниться в вашу транзакцию:
          lock держится на весь блок.

        Внутри блока работайте только с полученным db:
            async with self.transaction() as db:
                await db.execute(...)
                await db.executemany(...)
        """
        lock = self._write_lock()
        async with lock:
            async with self._connection() as db:
                await db.execute("BEGIN")
                try:
                    yield db
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

    def _process_row(self, row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Преобразует datetime-поля из БД в aware UTC datetime.

        Обрабатываются:
        - все поля, оканчивающиеся на '_at';
        - поля из DATETIME_FIELDS.

        Строгий парсинг (Задача 1.5): ValueError И TypeError ловятся
        явно; неожидаемый тип значения логируется, но не роняет запрос.
        Логика не опирается на комментарии — поведение описано кодом.
        """
        if row is None:
            return None

        processed = dict(row)

        for key, value in processed.items():
            is_dt_field = key.endswith("_at") or key in self.DATETIME_FIELDS
            if not is_dt_field or value is None:
                continue

            # Уже datetime (aiosqlite умеет парсить колонки с
            # declared type TIMESTAMP) — просто делаем aware UTC.
            if isinstance(value, datetime):
                processed[key] = self.time_service.make_aware_utc(value)
                continue

            if isinstance(value, str):
                raw = value.strip()
                # Ожидаем ISO/SQLite формат "YYYY-MM-DD HH:MM:SS"
                # (так пишет и CURRENT_TIMESTAMP, и now_utc_str()).
                try:
                    dt = datetime.fromisoformat(raw)
                except (ValueError, TypeError):
                    logger.warning(
                        "Failed to parse datetime field %s=%r",
                        key,
                        value,
                    )
                    continue
                processed[key] = self.time_service.make_aware_utc(dt)
                continue

            # Не строка и не datetime — битые данные, не роняем запрос.
            logger.warning(
                "Unexpected type for datetime field %s: %r",
                key,
                type(value),
            )

        return processed

    # ================== CRUD HELPERS ==================

    async def _fetch_one(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """SELECT ... LIMIT 1 -> dict с обработанными datetime."""
        async with self._connection() as db:
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            return self._process_row(dict(row)) if row else None

    async def _fetch_all(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """SELECT -> список dict с обработанными datetime."""
        async with self._connection() as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            if not rows:
                return []
            return [self._process_row(dict(r)) for r in rows]

    async def _fetch_value(self, query: str, params: tuple = ()) -> Any:
        """Одно скалярное значение (COUNT, SUM и т.п.)."""
        async with self._connection() as db:
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            return row[0] if row is not None and len(row) > 0 else None

    async def _execute(self, query: str, params: tuple = ()) -> int:
        """
        INSERT/UPDATE/DELETE -> количество затронутых строк.

        Write-операция захватывает общий lock: на shared-соединении
        нельзя допустить, чтобы чужой ROLLBACK отменил наш INSERT.
        """
        async with self._write_lock():
            async with self._connection() as db:
                cursor = await db.execute(query, params)
                await db.commit()
                return cursor.rowcount

    async def _execute_many(
        self,
        query: str,
        params_list: Sequence[tuple],
        chunk_size: int = 1000,
    ) -> None:
        """
        Массовый INSERT/UPSERT через executemany (Задача 1.2).

        - Один подготовленный запрос, тысячи строк — вместо тысяч
          отдельных round-trip'ов к SQLite-потоку.
        - Чанкинг (по умолчанию 1000 строк) ограничивает пик
          потребления RAM и размер журнала WAL между коммитами,
          при этом весь батч остаётся единой транзакцией.
        - НЕ вызывать внутри transaction(): будет дедлок по lock.
        """
        rows = list(params_list)
        if not rows:
            return

        async with self._write_lock():
            async with self._connection() as db:
                for offset in range(0, len(rows), chunk_size):
                    await db.executemany(
                        query,
                        rows[offset:offset + chunk_size],
                    )
                await db.commit()
