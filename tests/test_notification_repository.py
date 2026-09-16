import pytest
from core.models.dto import DeliveredKeyDTO
from core.repository.notification_repository import NotificationRepository

class MockNotificationRepo(NotificationRepository):
    """Изолированный мок для перехвата SQL-запросов и параметров."""
    def __init__(self):
        self.queries = []
        self.mock_db_rows = []

    async def _fetch_all(self, query: str, params: tuple):
        self.queries.append((query, params))
        return self.mock_db_rows


@pytest.fixture
def repo():
    return MockNotificationRepo()


# --- Тесты для сценариев "Family & Students" ---

@pytest.mark.asyncio
async def test_get_recipients_for_pre_lesson_reminder_params(repo: MockNotificationRepo):
    """Сценарий 1: Предурочные напоминания. Проверка базового билдера и параметров."""
    await repo.get_recipients_for_pre_lesson_reminder("10А", "ALL")
    
    query, params = repo.queries[0]
    
    # 6 параметров: (class_id, group_id, group_id) * 2 ветки
    assert params == ("10А", "ALL", "ALL", "10А", "ALL", "ALL")
    assert "UNION ALL" in query
    assert "pre_lesson_offset_minutes" in query


@pytest.mark.asyncio
async def test_get_recipients_for_schedule_change_watch_target(repo: MockNotificationRepo):
    """Сценарий 2: Изменения расписания. Проверка наличия третьей ветки (watch targets)."""
    await repo.get_recipients_for_schedule_change("11Б", "ENG")
    
    query, params = repo.queries[0]
    
    # 9 параметров: child + adult + watch
    assert len(params) == 9
    assert params == ("11Б", "ENG", "ENG", "11Б", "ENG", "ENG", "11Б", "ENG", "ENG")
    assert query.count("UNION ALL") == 2
    assert "schedule_watch_targets AS watch" in query


@pytest.mark.asyncio
async def test_get_morning_summary_tasks(repo: MockNotificationRepo):
    """Сценарий 3: Утренние сводки."""
    await repo.get_morning_summary_tasks("07:00")
    
    query, params = repo.queries[0]
    
    assert params == ("07:00", "07:00")
    assert query.count("UNION ALL") == 1
    assert "morning_summary_time = ?" in query


@pytest.mark.asyncio
async def test_get_todays_extra_classes_join_isolation(repo: MockNotificationRepo):
    """Сценарий 4: Доп. занятия. Проверяет, что extra_classes JOIN изолирован в своих SELECT блоках."""
    await repo.get_todays_extra_classes_for_reminders(2)
    
    query, params = repo.queries[0]
    assert params == (2, 2)
    
    # Убеждаемся, что extra_classes соединяется ДО parent_student_settings
    adult_part = query.split("UNION ALL")[1]
    assert "JOIN extra_classes AS extra" in adult_part
    assert "JOIN parent_student_settings" in adult_part


# --- Тесты для сценариев "Teachers" ---

@pytest.mark.asyncio
async def test_teacher_configs_unification(repo: MockNotificationRepo):
    """Проверяет работу универсального хелпера учителей (_get_teacher_configs)."""
    # Имитируем DatabaseRowProtocol через словарь с .get()
    repo.mock_db_rows = [{"recipient_id": 123, "teacher_id": "T1", "teacher_name": "Иванов И.И."}]
    
    result = await repo.get_teacher_morning_summary_tasks(time_str="07:00")
    
    query, params = repo.queries[0]
    assert params == ("07:00",)
    assert "name AS teacher_name" in query
    assert "WHERE role = 'teacher'" in query
    
    # Проверка маппинга
    assert len(result) == 1
    assert result[0].recipient_id == 123
    assert result[0].teacher_name == "Иванов И.И."


# --- Тесты получения данных расписания ---

@pytest.mark.asyncio
async def test_get_pending_changes_optional_date(repo: MockNotificationRepo):
    """Проверяет корректную обработку опционального end_date_iso."""
    # 1. Без end_date
    await repo.get_pending_changes(start_date_iso="2026-09-16")
    assert repo.queries[0][1] == ("2026-09-16",)
    
    # 2. С end_date
    await repo.get_pending_changes(start_date_iso="2026-09-16", end_date_iso="2026-09-20")
    assert repo.queries[1][1] == ("2026-09-16", "2026-09-20")
    assert "<= ?" in repo.queries[1][0]


# --- Тесты Delivery Dedup (Дедупликация) ---

@pytest.mark.asyncio
async def test_get_delivered_keys_chunk_validation(repo: MockNotificationRepo):
    """Проверка защиты от нулевых и отрицательных чанков."""
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        await repo.get_delivered_keys(
            notification_type="test", 
            candidate_keys=[DeliveredKeyDTO("2026-09-16", "src1", 100)], 
            chunk_size=0
        )

@pytest.mark.asyncio
async def test_get_delivered_keys_max_params_math(repo: MockNotificationRepo):
    """
    Проверяет точную математику генерации SQL-параметров в get_delivered_keys.
    При 250 уникальных ключах должно быть ровно 751 параметр (1 + 250 + 250 + 250).
    """
    candidates = [
        DeliveredKeyDTO(
            notification_date=f"2026-09-{str(i % 30 + 1).zfill(2)}",
            source_id=f"src_{i}",
            recipient_id=i + 1
        ) for i in range(250)
    ]
    
    await repo.get_delivered_keys(
        notification_type="pre_lesson", 
        candidate_keys=candidates, 
        chunk_size=250
    )
    
    _, params = repo.queries[0]
    
    # 1 (type) + 250 (dates) + 250 (sources) + 250 (recipients) = 751
    assert len(params) == 751