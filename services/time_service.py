# services/time_service.py
# ЦЕЛЬ ФАЙЛА: единая точка генерации времени для всего приложения.
#
# ИЗМЕНЕНИЕ (Задача 1.3, справочно): добавлен метод now_utc_str() —
# единственный источник "времени из приложения" для всех репозиториев.
# Он полностью замещает CURRENT_TIMESTAMP в SQL: время теперь генерирует
# Python-слой (TimeService), а не внутренние часы СУБД.
#
# Формат "YYYY-MM-DD HH:MM:SS" намеренно совпадает с форматом
# SQLite CURRENT_TIMESTAMP (UTC), поэтому:
# - старые строки, записанные СУБД, и новые строки, записанные из Python,
#   сортируются и сравниваются одинаково (лексикографически корректно);
# - миграция данных не требуется.

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, date
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


@dataclass
class TimeServiceConfig:
    timezone: str  # например "Asia/Novosibirsk"


class TimeService:
    """
    Централизованный сервис времени.

    Правила:
    - Базовое (пользовательское) время — в таймзоне школы, например
      Asia/Novosibirsk, offset UTC+7.
    - Всё, что пишется в БД, — только UTC.
    - Всё, что читается из БД, конвертируется в aware-UTC datetime.
    """

    @property
    def base_tz(self) -> ZoneInfo:
        return self._base_tz

    def __init__(self, cfg: TimeServiceConfig):
        self.cfg = cfg
        self._base_tz = ZoneInfo(cfg.timezone)
        logger.info("TimeService initialized with timezone=%s", cfg.timezone)

    # ===================== СЕРВЕРНОЕ ВРЕМЯ =====================

    def get_now_base(self) -> datetime:
        """
        tz-aware datetime в базовой таймзоне (Asia/Novosibirsk).

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

    # ==============================================================
    # НОВОЕ (Задача 1.3): генерация времени для записи в БД.
    # ==============================================================

    def now_utc_str(self) -> str:
        """
        Текущее UTC-время строкой в формате SQLite:
            "YYYY-MM-DD HH:MM:SS"

        Это полная замена CURRENT_TIMESTAMP. Время всегда берётся
        из одного источника (этого сервиса), что даёт:
        - детерминизм в тестах (можно замокать TimeService целиком);
        - отсутствие расхождений между "временем СУБД" и временем
          приложения (например, при записи связанных событий);
        - единый формат со старыми данными.
        """
        now_utc = TimeService.to_utc(self.get_now_base())
        return now_utc.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def utc_str_from(dt: Optional[datetime]) -> Optional[str]:
        """
        Конвертация произвольного datetime в строку формата SQLite.
        Удобно для репозиториев, которые получают время снаружи
        (например, expires_at для инвайтов), а не генерируют сами.
        """
        if dt is None:
            return None
        utc = TimeService.to_utc(dt)
        return utc.strftime("%Y-%m-%d %H:%M:%S")

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
        try:
            from datetime import datetime
            t_start = datetime.strptime(start_time.strip(), "%H:%M")
            t_end = datetime.strptime(end_time.strip(), "%H:%M")
            return t_start < t_end
        except ValueError:
            return False

    @staticmethod
    def normalize_time(time_str: str) -> Optional[str]:
        """
        Умный валидатор и нормализатор времени.
        Преобразует 21.00, 21-00, 21 00, 2100, 21:5, 2:00, 15 в строгий формат HH:MM.
        """
        if not time_str:
            return None
        time_str = time_str.strip()
        # Разделяем по любым нецифровым символам (точка, запятая, двоеточие, пробел, дефис)
        parts = [p for p in re.split(r'\D+', time_str) if p]
        try:
            if len(parts) == 1:
                digits = parts[0]
                if len(digits) <= 2:
                    hour, minute = int(digits), 0
                elif len(digits) == 3:
                    hour, minute = int(digits[0:1]), int(digits[1:3])
                elif len(digits) == 4:
                    hour, minute = int(digits[0:2]), int(digits[2:4])
                else:
                    return None
            elif len(parts) >= 2:
                hour = int(parts[0])
                min_str = parts[1]
                # Автодополнение: 21:5 -> 21:50, 16:0 -> 16:00
                if len(min_str) == 1:
                    min_str += "0"
                minute = int(min_str[:2])
            else:
                return None
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
            return None
        except ValueError:
            return None

    def format_base(self, dt) -> Optional[str]:
        """aware-UTC datetime -> 'DD.MM.YYYY HH:MM' в таймзоне школы."""
        if dt is None:
            return None
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except (ValueError, TypeError):
                return dt
        local = self.from_utc(dt)
        return local.strftime("%d.%m.%Y %H:%M")