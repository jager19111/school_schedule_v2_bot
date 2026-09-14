from __future__ import annotations

import datetime as dt

import pytest

from core.nika.exceptions import ScheduleDataError
from core.nika.normalizer import NikaNormalizer
from tests.factories import make_nika


MONDAY = dt.date(2026, 9, 7)


def test_normalizer_expands_group_lesson():
    nika = make_nika(
        class_schedule={
            "109": {
                "013": {
                    "102": {
                        "s": ["012", "012"],
                        "t": ["002", "003"],
                        "r": ["027", "028"],
                        "g": ["0", "1"],
                    }
                }
            }
        }
    )

    lessons = NikaNormalizer(nika).build_class_lessons([MONDAY])
    group_lessons = [item for item in lessons if item.lesson_num == 2]

    assert len(group_lessons) == 2
    assert [item.group_id for item in group_lessons] == ["0", "1"]
    assert [item.teacher_id for item in group_lessons] == ["002", "003"]
    assert [item.room_id for item in group_lessons] == ["027", "028"]


def test_normalizer_handles_cancelled_whole_class_lesson():
    nika = make_nika(
        class_schedule={
            "109": {
                "013": {
                    "101": {
                        "s": ["060"],
                        "t": ["002"],
                        "r": ["027"],
                    }
                }
            }
        },
        class_exchange={
            "013": {
                "07.09.2026": {"1": {"s": "F"}}
            }
        },
    )

    lessons = NikaNormalizer(nika).build_class_lessons([MONDAY])
    lesson = next(item for item in lessons if item.lesson_num == 1)

    assert lesson.is_cancelled is True
    assert lesson.subject_name == "ОТМЕНА"
    assert lesson.original_subject_id == "060"
    assert lesson.original_teacher_id == "002"
    assert lesson.original_room_id == "027"
    assert lesson.group_id == "ALL"


def test_normalizer_reads_lesson_numbers_from_schedule_keys():
    nika = make_nika(
        class_schedule={
            "109": {
                "013": {
                    "115": {
                        "s": ["012"],
                        "t": ["002"],
                        "r": ["027"],
                    }
                }
            }
        }
    )

    lessons = NikaNormalizer(nika).build_class_lessons([MONDAY])

    assert [item.lesson_num for item in lessons] == [15]


def test_normalizer_returns_empty_for_date_without_period():
    nika = make_nika(
        periods={
            "109": {"b": "01.09.2026", "e": "30.09.2026"},
            "110": {"b": "01.10.2026", "e": "31.10.2026"},
        },
        class_schedule={
            "109": {
                "013": {
                    "101": {
                        "s": ["060"],
                        "t": ["002"],
                        "r": ["027"],
                    }
                }
            }
        },
    )

    lessons = NikaNormalizer(nika).build_class_lessons(
        [dt.date(2026, 11, 2)]
    )

    assert lessons == []


def test_normalizer_raises_for_missing_lesson_time():
    nika = make_nika(
        lesson_times={"1": ["8:15", "9:00"]},
        class_schedule={
            "109": {
                "013": {
                    "102": {
                        "s": ["012"],
                        "t": ["002"],
                        "r": ["027"],
                    }
                }
            }
        },
    )

    with pytest.raises(ScheduleDataError):
        NikaNormalizer(nika).build_class_lessons([MONDAY])
        
def test_normalizer_cancelled_subgroup_lesson_keeps_original_group():
    nika = make_nika(
        class_schedule={
            "109": {
                "013": {
                    "102": {
                        "s": ["012", "012"],
                        "t": ["002", "003"],
                        "r": ["027", "028"],
                        "g": ["0", "1"],
                    }
                }
            }
        },
        class_exchange={
            "013": {"07.09.2026": {"2": {"s": "F"}}}
        },
    )

    lessons = NikaNormalizer(nika).build_class_lessons([MONDAY])
    cancelled = [l for l in lessons if l.lesson_num == 2]

    assert len(cancelled) == 2
    assert all(l.is_cancelled for l in cancelled)
    assert all(l.subject_name == "ОТМЕНА" for l in cancelled)
    assert {l.group_id for l in cancelled} == {"0", "1"}
    assert all(l.original_subject_id == "012" for l in cancelled)