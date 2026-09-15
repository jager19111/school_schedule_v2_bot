from dataclasses import fields

from core.models.domain import LessonInstance
from core.models.dto import LessonDTO


def test_lesson_instance_has_one_original_group_id_field():
    names = [
        field.name
        for field in fields(LessonInstance)
        if field.name == "original_group_id"
    ]
    assert names == ["original_group_id"]


def test_lesson_instance_has_one_original_group_name_field():
    names = [
        field.name
        for field in fields(LessonInstance)
        if field.name == "original_group_name"
    ]
    assert names == ["original_group_name"]


def test_lesson_dto_contains_original_class_fields():
    names = {field.name for field in fields(LessonDTO)}
    assert {"original_class_id", "original_class_name"} <= names


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