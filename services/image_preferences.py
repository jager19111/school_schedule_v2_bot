"""Формат расписания пользователя: картинка или текст (ТЗ v2.2, раздел 2.2).

Колонка users.prefer_image_schedule добавляется лениво через ALTER TABLE
(ensure_schema): это позволяет врезать фичу без правки database/migrations.py.
TECH DEBT: после финального мерджа перенести миграцию в migrations.py
и оставить здесь только чтение/запись.

Пользователи со слабым интернетом экономят трафик на текстовом формате;
дефолт — картинка (image-first, раздел 1 ТЗ).
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
        """Добавляет колонку prefer_image_schedule, если её ещё нет. Идемпотентно."""
        async with self._db.execute("PRAGMA table_info(users)") as cursor:
            rows = await cursor.fetchall()
        columns = {row[1] for row in rows} if rows else set()
        if "prefer_image_schedule" in columns:
            return
        await self._db.execute(
            "ALTER TABLE users ADD COLUMN prefer_image_schedule INTEGER NOT NULL DEFAULT 1"
        )
        await self._db.commit()
        logger.info("Колонка users.prefer_image_schedule добавлена (ленивая миграция)")

    async def prefers_image(self, user_id: int) -> bool:
        """True = постер-картинка. Неизвестный пользователь — дефолт (True)."""
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
