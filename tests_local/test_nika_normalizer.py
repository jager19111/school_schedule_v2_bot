# test_nika_normalizer.py
from __future__ import annotations

import datetime as dt

import pytest

from core.nika.exceptions import ScheduleDataError
from core.nika.normalizer import NikaNormalizer
from tests.factories import make_nika
import datetime

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

    # ИСПРАВЛЕНО: теперь не исключение, а предупреждение в лог + урок пропускается
    lessons = NikaNormalizer(nika).build_class_lessons([MONDAY])
    assert lessons == []  # Урок без времени не создаётся
        
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
    
    




@pytest.fixture
def base_nika():
    """Базовая структура NIKA для тестов."""
    return {
        "CLASSES": {"c1": "5А", "c2": "5Б"},
        "SUBJECTS": {"s1": "Математика", "s2": "Русский язык", "s3": "История"},
        "TEACHERS": {"t1": "Иванов И.И.", "t2": "Петров П.П."},
        "ROOMS": {"r1": "101", "r2": "102", "r3": "103"},
        "CLASSGROUPS": {"g1": "Группа 1", "g2": "Группа 2"},
        "LESSON_TIMES": {"1": ["08:15", "09:00"], "2": ["09:10", "09:55"]},
        "PERIODS": {"p1": {"b": "01.09.2026", "e": "31.12.2026"}},
        "CLASS_SCHEDULE": {},
        "CLASS_EXCHANGE": {},
        "TEACH_SCHEDULE": {},
        "TEACH_EXCHANGE": {}
    }

# 1. Обычный урок всего класса
def test_normal_whole_class_lesson(base_nika):
    base_nika["CLASS_SCHEDULE"] = {
        "p1": {"c1": {"101": {"s": ["s1"], "t": ["t1"], "r": ["r1"]}}}
    }
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    assert len(lessons) == 1
    assert lessons[0].subject_name == "Математика"
    assert lessons[0].group_id == "ALL"
    assert lessons[0].is_exchange is False

# 2. Урок с двумя группами
# 17. Одинаковый lesson_num у нескольких групп
def test_two_groups_lesson(base_nika):
    base_nika["CLASS_SCHEDULE"] = {
        "p1": {"c1": {"101": {"s": ["s1", "s2"], "t": ["t1", "t2"], "r": ["r1", "r2"], "g": ["g1", "g2"]}}}
    }
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    assert len(lessons) == 2
    assert {l.group_name for l in lessons} == {"Группа 1", "Группа 2"}
    assert lessons[0].subject_name == "Математика"
    assert lessons[1].subject_name == "Русский язык"

# 3. Отмена урока всего класса
def test_cancel_whole_class(base_nika):
    base_nika["CLASS_SCHEDULE"] = {"p1": {"c1": {"101": {"s": ["s1"], "t": ["t1"], "r": ["r1"]}}}}
    base_nika["CLASS_EXCHANGE"] = {"c1": {"07.09.2026": {"1": {"s": "F"}}}}
    
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    assert len(lessons) == 1
    assert lessons[0].is_cancelled is True
    assert lessons[0].subject_name == "ОТМЕНА"
    assert lessons[0].original_subject_name == "Математика"
    assert lessons[0].original_teacher_name == "Иванов И.И."

# 4. Отмена урока одной группы
def test_cancel_one_group(base_nika):
    base_nika["CLASS_SCHEDULE"] = {
        "p1": {"c1": {"101": {"s": ["s1", "s2"], "t": ["t1", "t2"], "r": ["r1", "r2"], "g": ["g1", "g2"]}}}
    }
    base_nika["CLASS_EXCHANGE"] = {
        "c1": {"07.09.2026": {"1": {"s": ["s1", "F"], "t": ["t1", ""], "r": ["r1", ""], "g": ["g1", "g2"]}}}
    }
    
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    assert len(lessons) == 2
    active = next(l for l in lessons if l.group_id == "g1")
    cancelled = next(l for l in lessons if l.group_id == "g2")
    
    assert active.is_cancelled is False
    assert cancelled.is_cancelled is True
    assert cancelled.subject_name == "ОТМЕНА"
    assert cancelled.original_subject_name == "Русский язык"

# 5. Замена предмета
def test_subject_replacement(base_nika):
    base_nika["CLASS_SCHEDULE"] = {"p1": {"c1": {"101": {"s": ["s1"], "t": ["t1"], "r": ["r1"]}}}}
    base_nika["CLASS_EXCHANGE"] = {"c1": {"07.09.2026": {"1": {"s": ["s3"], "t": ["t1"], "r": ["r1"]}}}}
    
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    assert lessons[0].is_exchange is True
    assert lessons[0].subject_name == "История"
    assert lessons[0].original_subject_name == "Математика"

# 6. Замена кабинета
def test_room_replacement(base_nika):
    base_nika["CLASS_SCHEDULE"] = {"p1": {"c1": {"101": {"s": ["s1"], "t": ["t1"], "r": ["r1"]}}}}
    base_nika["CLASS_EXCHANGE"] = {"c1": {"07.09.2026": {"1": {"s": ["s1"], "t": ["t1"], "r": ["r2"]}}}}
    
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    assert lessons[0].room_name == "102"
    assert lessons[0].original_room_name == "101"

# 7. Замена учителя
def test_teacher_replacement(base_nika):
    base_nika["CLASS_SCHEDULE"] = {"p1": {"c1": {"101": {"s": ["s1"], "t": ["t1"], "r": ["r1"]}}}}
    base_nika["CLASS_EXCHANGE"] = {"c1": {"07.09.2026": {"1": {"s": ["s1"], "t": ["t2"], "r": ["r1"]}}}}
    
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    assert lessons[0].teacher_name == "Петров П.П."
    assert lessons[0].original_teacher_name == "Иванов И.И."

# 8. Замена группы
def test_group_replacement(base_nika):
    base_nika["CLASS_SCHEDULE"] = {"p1": {"c1": {"101": {"s": ["s1"], "t": ["t1"], "r": ["r1"], "g": ["g1"]}}}}
    base_nika["CLASS_EXCHANGE"] = {"c1": {"07.09.2026": {"1": {"s": ["s1"], "t": ["t1"], "r": ["r1"], "g": ["g2"]}}}}
    
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    assert lessons[0].group_id == "g2"
    assert lessons[0].original_group_id == "g1"

# 9. Перестановка уроков
def test_lesson_permutation(base_nika):
    base_nika["CLASS_SCHEDULE"] = {
        "p1": {
            "c1": {
                "101": {"s": ["s1"], "t": ["t1"], "r": ["r1"]},
                "102": {"s": ["s3"], "t": ["t2"], "r": ["r3"]}
            }
        }
    }
    # Меняем местами Математику (s1) и Историю (s3)
    base_nika["CLASS_EXCHANGE"] = {
        "c1": {
            "07.09.2026": {
                "1": {"s": ["s3"], "t": ["t2"], "r": ["r3"]},
                "2": {"s": ["s1"], "t": ["t1"], "r": ["r1"]}
            }
        }
    }
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    assert lessons[0].subject_name == "История"
    assert lessons[0].original_subject_name == "Математика"
    assert lessons[1].subject_name == "Математика"
    assert lessons[1].original_subject_name == "История"

# 10. Методический час (Учитель)
def test_methodological_hour(base_nika):
    base_nika["TEACH_SCHEDULE"] = {"p1": {"t1": {"101": {"s": ["s1"], "c": ["c1"], "r": ["r1"]}}}}
    base_nika["TEACH_EXCHANGE"] = {"t1": {"07.09.2026": {"1": {"s": ["M"]}}}}
    
    lessons = NikaNormalizer(base_nika).build_teacher_lessons([MONDAY])
    assert len(lessons) == 1
    assert lessons[0].is_methodological is True
    assert lessons[0].subject_name == "Методический час/день"
    assert lessons[0].original_subject_name == "Математика"

# 11. Методический день (Учитель)
def test_methodological_day(base_nika):
    # Метод. день означает, что все слоты в расписании замещены флагом M
    base_nika["TEACH_SCHEDULE"] = {
        "p1": {"t1": {"101": {"s": ["s1"], "c": ["c1"]}, "102": {"s": ["s2"], "c": ["c2"]}}}
    }
    base_nika["TEACH_EXCHANGE"] = {
        "t1": {"07.09.2026": {"1": {"s": ["M"]}, "2": {"s": ["M"]}}}
    }
    lessons = NikaNormalizer(base_nika).build_teacher_lessons([MONDAY])
    assert len(lessons) == 2
    assert all(l.is_methodological for l in lessons)

# 12. Отсутствующий период
def test_missing_period(base_nika):
    # Дата вне рамок 01.09.2026 - 31.12.2026
    lessons = NikaNormalizer(base_nika).build_class_lessons([datetime.date(2027, 1, 10)])
    assert lessons == []

# 13. Отсутствующий LESSON_TIMES
def test_missing_lesson_times(base_nika):
    base_nika["CLASS_SCHEDULE"] = {"p1": {"c1": {"103": {"s": ["s1"], "t": ["t1"]}}}}
    # LESSON_TIMES имеет только 1 и 2
    # ИСПРАВЛЕНО: теперь не исключение, а предупреждение + урок пропускается
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    assert lessons == []  # Урок без времени не создаётся

# 14. Пустой предмет
# 15. Пустой кабинет
def test_empty_subject_and_room(base_nika):
    base_nika["CLASS_SCHEDULE"] = {"p1": {"c1": {"101": {"s": [""], "t": ["t1"], "r": ["  "]}}}}
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    
    # ИСПРАВЛЕНО: пустой предмет теперь → отмена (по ТЗ)
    assert lessons[0].is_cancelled is True
    assert lessons[0].subject_name == "ОТМЕНА"
    assert lessons[0].room_name is None  # Пустой кабинет остаётся None

# 16. Изменение порядка массивов NIKA (защита от IndexError через max_len)
def test_changed_array_order(base_nika):
    base_nika["CLASS_SCHEDULE"] = {
        # Массив групп длиннее, чем массив предметов
        "p1": {"c1": {"101": {"s": ["s1"], "t": ["t1"], "g": ["g1", "g2"]}}}
    }
    lessons = NikaNormalizer(base_nika).build_class_lessons([MONDAY])
    assert len(lessons) == 2
    assert lessons[0].subject_name == "Математика"
    assert lessons[1].subject_name is None # Для второй группы предмета не хватило, но парсер не упал

# 19. Расписание учителя и класса в одном слоте
def test_teacher_and_class_in_one_slot(base_nika):
    base_nika["CLASS_SCHEDULE"] = {"p1": {"c1": {"101": {"s": ["s1"], "t": ["t1"], "r": ["r1"]}}}}
    base_nika["TEACH_SCHEDULE"] = {"p1": {"t1": {"101": {"s": ["s1"], "c": ["c1"], "r": ["r1"]}}}}
    
    normalizer = NikaNormalizer(base_nika)
    class_lessons = normalizer.build_class_lessons([MONDAY])
    teacher_lessons = normalizer.build_teacher_lessons([MONDAY])
    
    assert len(class_lessons) == 1
    assert len(teacher_lessons) == 1
    
    c_lesson = class_lessons[0]
    t_lesson = teacher_lessons[0]
    
    # Убеждаемся, что обе стороны видят друг друга
    assert c_lesson.teacher_name == "Иванов И.И."
    assert t_lesson.class_name == "5А"
    assert c_lesson.subject_name == t_lesson.subject_name