import pytest
from core.models.dto import (
    NotificationSendDTO, 
    PreLessonRecipientDTO, 
    DeliveredKeyDTO,
    ScheduleChangeRecipientDTO
)
from core.mappers.notification_mapper import NotificationMapper

class MockDBRow:
    """Простой мок для имитации DatabaseRowProtocol."""
    def __init__(self, data: dict):
        self._data = data
    def get(self, key, default=None):
        return self._data.get(key, default)
    def __getitem__(self, key):
        return self._data[key]

# --- Тесты валидации DTO ---

def test_notification_send_dto_validation():
    """Контракт: кандидат на отправку не может быть пустым или иметь кривой ID."""
    with pytest.raises(ValueError, match="Notification text cannot be empty"):
        NotificationSendDTO("type", "2026-09-16", "src1", 123, "")
        
    with pytest.raises(ValueError, match="recipient_id must be strictly positive"):
        NotificationSendDTO("type", "2026-09-16", "src1", -5, "Урок отменен")
        
    with pytest.raises(ValueError, match="notification_type cannot be empty"):
        NotificationSendDTO("", "2026-09-16", "src1", 123, "Текст")

def test_recipient_dto_validation():
    """Контракт: параметры получателей не могут быть отрицательными."""
    with pytest.raises(ValueError, match="offset_minutes cannot be negative"):
        PreLessonRecipientDTO(student_id=1, recipient_id=123, offset_minutes=-10, recipient_kind="adult", child_name="Лиза")
        
    with pytest.raises(ValueError, match="changes_window_days cannot be negative"):
        ScheduleChangeRecipientDTO(student_id=1, recipient_id=123, changes_window_days=-1, recipient_kind="adult", child_name=None, watch_target_title=None)

def test_delivered_key_dto_validation():
    """Контракт: ключ дедупликации обязан быть полным."""
    with pytest.raises(ValueError, match="notification_date and source_id cannot be empty"):
        DeliveredKeyDTO("", "src1", 123)

# --- Тесты Маппера ---

def test_mapper_to_delivered_key_dto():
    """Контракт: маппер корректно приводит типы из строки БД."""
    row = MockDBRow({"notification_date": "2026-09-16", "source_id": "lesson_1", "recipient_id": "123"})
    dto = NotificationMapper.to_delivered_key_dto(row)
    
    assert dto.notification_date == "2026-09-16"
    assert dto.source_id == "lesson_1"
    assert dto.recipient_id == 123  # Строка преобразована в int