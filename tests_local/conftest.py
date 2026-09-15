from __future__ import annotations

import pytest

from core.models.domain import LessonInstance


@pytest.fixture
def lesson_factory():
    def factory(**overrides) -> LessonInstance:
        values = {
            "id": "lesson-1",
            "period_id": "period-1",
            "class_id": "013",
            "class_name": "5а",
            "date": "2026-09-07",
            "weekday": 1,
            "lesson_num": 1,
            "start_time": "08:15",
            "end_time": "09:00",
            "subject_id": "060",
            "subject_name": "Русский язык",
            "teacher_id": "002",
            "teacher_name": "Иванов И.И.",
            "room_id": "027",
            "room_name": "208(Н)",
            "group_id": "ALL",
            "group_name": "Весь класс",
            "is_exchange": False,
            "is_cancelled": False,
            "is_methodological": False,
        }
        values.update(overrides)
        return LessonInstance(**values)

    return factory