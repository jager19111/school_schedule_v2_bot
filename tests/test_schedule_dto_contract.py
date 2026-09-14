from dataclasses import fields

from core.models.dto import LessonDTO


def test_lesson_dto_contains_original_class_fields():
    names = {field.name for field in fields(LessonDTO)}

    assert "original_class_id" in names
    assert "original_class_name" in names


def test_lesson_dto_contains_change_fields():
    names = {field.name for field in fields(LessonDTO)}

    expected = {
        "original_subject_id",
        "original_subject_name",
        "original_teacher_id",
        "original_teacher_name",
        "original_room_id",
        "original_room_name",
        "original_group_id",
        "original_group_name",
        "group_changed",
        "day_permutation",
    }

    assert expected <= names