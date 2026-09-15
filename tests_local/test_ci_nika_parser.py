import datetime
import asyncio
from core.nika.normalizer import NikaNormalizer

def test_normalizer():
    # Мок-данные из NIKA
    mock_nika = {
        "CLASSES": {"013": "5а"},
        "SUBJECTS": {"060": "Русский язык", "012": "Ин.яз"},
        "TEACHERS": {"002": "Иванов И.И."},
        "ROOMS": {"027": "208(Н)"},
        "CLASSGROUPS": {"0": "Группа 1", "1": "Группа 2"},
        "LESSON_TIMES": {"1": ["8:15", "9:00"], "2": ["9:10", "9:55"]},
        "PERIODS": {"109": {"b": "01.09.2026", "e": "31.12.2026"}},
        "CLASS_SCHEDULE": {
            "109": {
                "013": {
                    "101": {"s": ["060"], "t": ["002"], "r": ["027"]},  # Весь класс, ПН, 1 урок
                    "102": {"s": ["012", "012"], "t": ["002", "002"], "g": ["0", "1"], "r": ["027", "027"]} # 2 группы
                }
            }
        },
        "CLASS_EXCHANGE": {
            "013": {
                "07.09.2026": { # ПН
                    "1": {"s": "F"} # Отмена первого урока[cite: 1, 8]
                }
            }
        }
    }
    
    target_date = datetime.date(2026, 9, 7) # Понедельник
    normalizer = NikaNormalizer(mock_nika)
    lessons = normalizer.build_class_lessons([target_date])
    
    # Урок 1 должен быть отменен
    lesson_1 = next(l for l in lessons if l.lesson_num == 1)
    assert lesson_1.is_cancelled is True
    assert lesson_1.subject_name == "ОТМЕНА"
    assert lesson_1.group_id == "ALL"
    
    # Урок 2 должен быть развернут на две группы
    lesson_2_groups = [l for l in lessons if l.lesson_num == 2]
    assert len(lesson_2_groups) == 2
    assert lesson_2_groups[0].group_id == "0"
    assert lesson_2_groups[1].group_id == "1"

if __name__ == "__main__":
    test_normalizer()
    print("✅ Тесты парсера пройдены!")