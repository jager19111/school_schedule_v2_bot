from __future__ import annotations


def make_nika(
    *,
    class_schedule=None,
    class_exchange=None,
    teach_schedule=None,
    teach_exchange=None,
    lesson_times=None,
    periods=None,
):
    return {
        "CLASSES": {"013": "5а", "014": "5б"},
        "SUBJECTS": {"060": "Русский язык", "012": "Ин.яз"},
        "TEACHERS": {"002": "Иванов И.И.", "003": "Петров П.П."},
        "ROOMS": {"027": "208(Н)", "028": "318"},
        "CLASSGROUPS": {"0": "Группа 1", "1": "Группа 2"},
        "LESSON_TIMES": lesson_times or {
            "1": ["8:15", "9:00"],
            "2": ["9:10", "9:55"],
            "15": ["18:00", "18:45"],
        },
        "PERIODS": periods or {
            "109": {"b": "01.09.2026", "e": "31.12.2026"},
        },
        "CLASS_SCHEDULE": class_schedule or {},
        "CLASS_EXCHANGE": class_exchange or {},
        "TEACH_SCHEDULE": teach_schedule or {},
        "TEACH_EXCHANGE": teach_exchange or {},
    }