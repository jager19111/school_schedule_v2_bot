import pytest
from core.models.dto import DeliveredKeyDTO
from core.repository.notification_repository import NotificationRepository

class MockNotificationRepo(NotificationRepository):
    """Мок-репозиторий для изоляции тестов логики генерации и фильтрации."""
    def __init__(self):
        self.queries = []
        self.mock_db_rows = []

    async def _fetch_all(self, query: str, params: tuple):
        self.queries.append((query, params))
        return self.mock_db_rows


@pytest.fixture
def repo():
    return MockNotificationRepo()


@pytest.mark.asyncio
async def test_get_delivered_keys_empty_list(repo: MockNotificationRepo):
    """Проверка раннего выхода при пустом списке кандидатов."""
    result = await repo.get_delivered_keys(
        notification_type="morning_summary", 
        candidate_keys=[]
    )
    assert result == set()
    assert len(repo.queries) == 0


@pytest.mark.asyncio
async def test_get_delivered_keys_duplicates(repo: MockNotificationRepo):
    """Проверка дедупликации одинаковых candidate keys до отправки в БД."""
    key = DeliveredKeyDTO("2026-09-16", "lesson_1", 100)
    
    # Имитируем, что БД вернула этот ключ
    repo.mock_db_rows = [
        {"notification_date": "2026-09-16", "source_id": "lesson_1", "recipient_id": 100}
    ]

    # Передаем список с дублями
    candidates = [key, key, key]
    result = await repo.get_delivered_keys(
        notification_type="pre_lesson", 
        candidate_keys=candidates
    )
    
    assert len(result) == 1
    assert key in result
    
    # Проверяем, что запрос был ровно один и плейсхолдеры сгенерировались без дублей
    _, params = repo.queries[0]
    assert params == ("pre_lesson", "2026-09-16", "lesson_1", 100)


@pytest.mark.asyncio
async def test_get_delivered_keys_chunking(repo: MockNotificationRepo):
    """Проверка корректного разбиения на чанки."""
    candidates = [
        DeliveredKeyDTO("2026-09-16", f"lesson_{i}", 100 + i) 
        for i in range(5)
    ]
    
    repo.mock_db_rows = []
    
    # Ставим размер чанка 2, ожидаем 3 запроса (2 + 2 + 1)
    await repo.get_delivered_keys(
        notification_type="pre_lesson", 
        candidate_keys=candidates, 
        chunk_size=2
    )
    
    assert len(repo.queries) == 3


@pytest.mark.asyncio
async def test_get_delivered_keys_cross_product_filtering(repo: MockNotificationRepo):
    """
    Проверка отсеивания ложных срабатываний (cross-product).
    БД может вернуть комбинацию, которую мы не запрашивали, из-за IN-списков.
    """
    valid_key_1 = DeliveredKeyDTO("2026-09-16", "lesson_A", 100)
    valid_key_2 = DeliveredKeyDTO("2026-09-17", "lesson_B", 200)
    
    # Кросс-продукт, который SQL может вернуть, потому что параметры совпали по разным осям IN (...)
    false_positive_key = DeliveredKeyDTO("2026-09-16", "lesson_B", 100) 
    
    repo.mock_db_rows = [
        {"notification_date": valid_key_1.notification_date, "source_id": valid_key_1.source_id, "recipient_id": valid_key_1.recipient_id},
        {"notification_date": valid_key_2.notification_date, "source_id": valid_key_2.source_id, "recipient_id": valid_key_2.recipient_id},
        # Имитируем, что БД вернула кросс-продукт
        {"notification_date": false_positive_key.notification_date, "source_id": false_positive_key.source_id, "recipient_id": false_positive_key.recipient_id},
    ]

    candidates = [valid_key_1, valid_key_2]
    
    result = await repo.get_delivered_keys(
        notification_type="schedule_change", 
        candidate_keys=candidates
    )
    
    assert len(result) == 2
    assert valid_key_1 in result
    assert valid_key_2 in result
    assert false_positive_key not in result  # Ложное срабатывание должно быть отфильтровано