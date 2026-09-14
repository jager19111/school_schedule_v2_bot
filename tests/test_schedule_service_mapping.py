from types import SimpleNamespace

from services.schedule_service import ScheduleService


def make_service():
    return ScheduleService(
        schedule_repo=SimpleNamespace(),
        extra_classes_repo=SimpleNamespace(),
        time_service=SimpleNamespace(),
    )


def test_lesson_to_dto_copies_original_class(lesson_factory):
    lesson = lesson_factory(
        is_exchange=True,
        original_class_id="014",
        original_class_name="5б",
    )

    dto = make_service()._lesson_to_dto(lesson)

    assert dto.original_class_id == "014"
    assert dto.original_class_name == "5б"


def test_lesson_to_dto_sets_group_changed(lesson_factory):
    lesson = lesson_factory(
        is_exchange=True,
        group_id="1",
        group_name="Группа 2",
        original_group_id="0",
        original_group_name="Группа 1",
    )

    dto = make_service()._lesson_to_dto(lesson)

    assert dto.group_changed is True


def test_lesson_to_dto_does_not_mark_unchanged_group(lesson_factory):
    lesson = lesson_factory(
        is_exchange=True,
        group_id="0",
        original_group_id="0",
    )

    dto = make_service()._lesson_to_dto(lesson)

    assert dto.group_changed is False


def test_lesson_to_dto_preserves_permutation_flag(lesson_factory):
    lesson = lesson_factory(is_exchange=True)

    dto = make_service()._lesson_to_dto(
        lesson,
        day_permutation=True,
    )

    assert dto.day_permutation is True
    
def test_map_extra_to_lesson_returns_dto():
    service = make_service()

    dto = service._map_extra_to_lesson(
        {
            "id": 5,
            "time_start": "16:00",
            "time_end": "17:00",
            "title": "Плавание",
            "location": "Бассейн",
            "student_id": 1,
        },
        "2026-09-07",
    )

    assert dto.is_extra is True
    assert dto.id == "extra-5"
    assert dto.display_num == "•"
    assert dto.lesson_num is None
    assert dto.subject_name == "Плавание"