# services/time_service.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, date
from typing import Optional

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


@dataclass
class TimeServiceConfig:
    """Конфиг для сервиса времени."""
    timezone: str  # "Asia/Novosibirsk"


class TimeService:
    """
    Централизованное управление временем для школьного бота.

    Принципы:
    - БД хранит UTC (offset 0).
    - Сервер/школа работает в одном timezone из конфига (например, Asia/Novosibirsk).
    - Нет пользовательских сдвигов; все пользователи считаются в одной зоне.
    """
    
    @property
    def base_tz(self) -> ZoneInfo:
        """Публичный доступ к базовой таймзоне школы."""
        return self._base_tz
    
    def __init__(self, cfg: TimeServiceConfig):
        self.cfg = cfg
        self._base_tz = ZoneInfo(cfg.timezone)
        logger.info("TimeService initialized with timezone=%s", cfg.timezone)

    # ===================== СЕРВЕРНОЕ ВРЕМЯ =====================

    def get_now_base(self) -> datetime:
        """
        Текущее время в таймзоне школы (tz-aware datetime).

        Использовать в:
        - NotificationService (pre-lesson, changes).
        - ScheduleRepository.refresh_from_remote (логика окон, retention).
        - CleanupJob (неактивные пользователи).
        """
        now = datetime.now(self._base_tz)
        logger.debug("get_now_base(): %s", now.isoformat())
        return now

    # ===================== UTC / БД =====================

    @staticmethod
    def to_utc(dt: Optional[datetime]) -> Optional[datetime]:
        """
        Переводит datetime в UTC для записи в БД.

        - Если dt naive → считается, что уже UTC, просто помечаем tz=UTC.
        - Если dt aware → пересчитываем в UTC через astimezone().
        """
        if dt is None:
            return None

        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    def from_utc(self, dt: Optional[datetime]) -> Optional[datetime]:
        """
        Переводит UTC datetime (из БД) в время школы (base tz).

        - Если dt naive → считаем, что это UTC, и навешиваем tz=UTC.
        - Затем пересчитываем в базовый timezone.
        """
        if dt is None:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(self._base_tz)

    @staticmethod
    def make_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
        """
        Помечает naive datetime как UTC без пересчёта (для чтения из SQLite).

        Используется, если в БД хранится UTC как TEXT/naive datetime.
        """
        if dt is None:
            return None

        if dt.tzinfo is not None:
            return dt

        return dt.replace(tzinfo=timezone.utc)

    # ===================== УТИЛИТЫ ДЛЯ ДАТ =====================

    @staticmethod
    def parse_iso_date(value: str | date | None) -> Optional[date]:
        """
        Парсит дату вида 'YYYY-MM-DD' или возвращает date как есть.
        """
        if not value:
            return None

        if isinstance(value, date):
            return value

        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                logger.warning("Failed to parse date: %s", value)
                return None

        logger.warning("Unexpected type for date: %s", type(value))
        return None

    def get_date_window(self, now: datetime, days: int) -> tuple[date, date]:
        """
        Возвращает (start_date, end_date) для окна изменений/уведомлений.

        Пример:
        - now = get_now_base()
        - start, end = get_date_window(now, 3)
        - использовать в WHERE date BETWEEN start AND end
        """
        start = now.date()
        end = (now + timedelta(days=days)).date()
        return start, end
    
    @staticmethod
    def validate_time_format(time_str: str) -> bool:
        """
        Строгая валидация ввода времени в формате ЧЧ:ММ.
        Используется для проверки ввода при добавлении доп. занятий
        """
        if not time_str:
            return False
            
        try:
            datetime.strptime(time_str.strip(), "%H:%M")
            return True
        except ValueError:
            return False

    @staticmethod
    def date_from_iso(iso_date: str) -> datetime.date:
        """
        Преобразует строку YYYY-MM-DD в datetime.date.

        Пример:
            "2026-09-02" -> datetime.date(2026, 9, 2)
        """
        return datetime.fromisoformat(iso_date).date()
    
    @staticmethod
    def validate_time_range(start_time: str, end_time: str) -> bool:
        """Проверяет, что время окончания строго позже времени начала."""
        try:
            from datetime import datetime
            t_start = datetime.strptime(start_time.strip(), "%H:%M")
            t_end = datetime.strptime(end_time.strip(), "%H:%M")
            return t_start < t_end
        except ValueError:
            return False