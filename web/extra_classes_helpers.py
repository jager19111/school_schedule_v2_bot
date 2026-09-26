# web/extra_classes_helpers.py
#
# Phase 5: Web-схема и маппер доп. занятий (ТЗ 44: отдельные web-модели;
# добавлены отдельным аддитивным модулем, чтобы не трогать уже
# применённые web/schemas.py / web/mappers.py).
# Домен -> WebExtraClass; никакой бизнес-логики.

from __future__ import annotations
from typing import Dict, List, Any
from pydantic import BaseModel

WEEKDAYS_RU = {
    1: "Понедельник", 2: "Вторник", 3: "Среда", 4: "Четверг",
    5: "Пятница", 6: "Суббота", 7: "Воскресенье",
}

class WebExtraClass(BaseModel):
    """Доп. занятие в web-представлении (ТЗ 25)."""

    id: int
    day_of_week: int
    weekday_display: str
    time_start: str
    time_end: str
    title: str
    location: str
    reminder_minutes: int

def _get_val(obj: Any, key: str, default: Any = None) -> Any:
    """Универсальный геттер: читает как словари, так и DTO-объекты."""
    if hasattr(obj, "model_dump"): obj = obj.model_dump()
    elif hasattr(obj, "dict"): obj = obj.dict()
    if isinstance(obj, dict): return obj.get(key, default)
    return getattr(obj, key, default)

def extra_class_to_web(row: Any) -> WebExtraClass:
    day = int(_get_val(row, "day_of_week") or 1)
    return WebExtraClass(
        id=int(_get_val(row, "id") or 0),
        day_of_week=day,
        weekday_display=WEEKDAYS_RU.get(day, "—"),
        time_start=str(_get_val(row, "time_start") or "—"),
        time_end=str(_get_val(row, "time_end") or "—"),
        title=str(_get_val(row, "title") or "Занятие"),
        location=str(_get_val(row, "location") or "—"),
        reminder_minutes=int(_get_val(row, "reminder_minutes") or 30),
    )

def group_by_weekday(items: List[WebExtraClass]) -> List[Dict]:
    """Группировка для списка: [{weekday_display, items: [...]}, ...]."""
    groups: Dict[int, List[WebExtraClass]] = {}
    for item in items:
        groups.setdefault(item.day_of_week, []).append(item)
    result = []
    for day in sorted(groups):
        result.append(
            {
                "weekday_display": WEEKDAYS_RU.get(day, "—"),
                "lessons": sorted(groups[day], key=lambda i: i.time_start), # <-- ИСПРАВЛЕНО
            }
        )
    return result