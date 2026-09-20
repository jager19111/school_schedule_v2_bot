"""Настройки формата расписания: картинка или текст.

Схема users.prefer_image_schedule создаётся штатной миграцией
(database.migrations). ensure_schema оставлен как безопасный compatibility
check для БД, обновлённых старым этапом 3: он НЕ выполняет ALTER TABLE.
"""

from __future__ import annotations

import logging

import aiosqlite

logger = logging.getLogger(__name__)


class ImagePreferencesService:
    """Чтение/переключение флага prefer_image_schedule в users."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def ensure_schema(self) -> None:
        """Проверяет наличие колонки; миграции выполняются до DI-сборки."""
        async with self._db.execute("PRAGMA table_info(users)") as cursor:
            rows = await cursor.fetchall()
        if not rows:
            logger.warning("Таблица users не найдена при проверке image preferences")
            return
        columns = {row[1] for row in rows}
        if "prefer_image_schedule" not in columns:
            raise RuntimeError(
                "users.prefer_image_schedule отсутствует: "
                "запустите database.apply_migrations до сборки сервисов"
            )

    async def prefers_image(self, user_id: int) -> bool:
        """True = постер-картинка. Неизвестный пользователь — дефолт True."""
        async with self._db.execute(
            "SELECT prefer_image_schedule FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return True
        return bool(row[0])

    async def toggle(self, user_id: int) -> bool:
        """Переключает формат и возвращает НОВОЕ значение (True = картинка)."""
        current = await self.prefers_image(user_id)
        new_value = 0 if current else 1
        await self._db.execute(
            "UPDATE users SET prefer_image_schedule = ? WHERE user_id = ?",
            (new_value, user_id),
        )
        await self._db.commit()
        return not current
