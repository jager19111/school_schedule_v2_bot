import pytest
from types import SimpleNamespace
from services.schedule_service import ScheduleService
from core.models.dto import ExtraClassItemDTO

# 18. Дополнительное занятие
def test_map_extra_to_lesson_returns_dto():
    service = ScheduleService(
        schedule_repo=SimpleNamespace(),
        extra_classes_repo=SimpleNamespace(),
        time_service=SimpleNamespace(),
    )

    # Используем DTO вместо словаря (исправление техдолга P1)
    extra_dto = ExtraClassItemDTO(
        id=5,
        day_of_week=1,
        time_start="16:00",
        time_end="17:00",
        title="Плавание",
        location="Бассейн",
        reminder_minutes=30
    )

    lesson_dto = service._map_extra_to_lesson(
        row=extra_dto,
        date_iso="2026-09-07"
    )

    assert lesson_dto.is_extra is True
    assert lesson_dto.id == "extra-5"
    assert lesson_dto.display_num == "•"
    assert lesson_dto.lesson_num is None
    assert lesson_dto.subject_name == "Плавание"
    assert lesson_dto.room_name == "Бассейн"
    assert lesson_dto.date_iso == "2026-09-07"