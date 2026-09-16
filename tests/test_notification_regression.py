import pytest
from unittest.mock import AsyncMock, MagicMock
import datetime

from services.notifications.context import NotificationTickContext
from services.notifications.pipeline import NotificationPipeline
from services.notifications.collector import NotificationCollector
from core.models.dto import NotificationSendDTO, ScheduleChangeRecipientDTO, PendingChangeDTO

# --- Фикстуры ---

@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    # По умолчанию никто не заблокирован и ничего не доставлено
    repo.get_blocked_user_ids.return_value = []
    repo.get_delivered_keys.return_value = set()
    return repo

@pytest.fixture
def mock_dispatcher():
    dispatcher = AsyncMock()
    dispatcher.send.return_value = True  # Имитируем успешную отправку
    return dispatcher

@pytest.fixture
def pipeline(mock_repo, mock_dispatcher):
    return NotificationPipeline(notification_repo=mock_repo, dispatcher=mock_dispatcher)

@pytest.fixture
def tick_ctx():
    return NotificationTickContext()

# --- Регрессионные тесты Пайплайна ---

@pytest.mark.asyncio
async def test_pipeline_filters_blocked_users(pipeline, mock_repo, mock_dispatcher, tick_ctx):
    """Регрессия: заблокированные пользователи не должны проходить на отправку."""
    mock_repo.get_blocked_user_ids.return_value = [999]  # Пользователь 999 заблокировал бота
    
    candidates = [
        NotificationSendDTO("test", "2026-09-16", "src1", 123, "Нормальный юзер"),
        NotificationSendDTO("test", "2026-09-16", "src2", 999, "Заблокированный юзер"),
    ]
    
    await pipeline.execute(tick_ctx, candidates)
    
    # Проверяем, что dispatcher.send вызвался только 1 раз (для юзера 123)
    assert mock_dispatcher.send.call_count == 1
    call_args = mock_dispatcher.send.call_args[1]
    assert call_args["chat_id"] == 123
    assert tick_ctx.sent == 1

@pytest.mark.asyncio
async def test_pipeline_prevents_redelivery(pipeline, mock_repo, mock_dispatcher, tick_ctx):
    """Регрессия: защита от повторной отправки (Dedup) работает корректно."""
    from core.models.dto import DeliveredKeyDTO
    
    # Имитируем, что src1 уже был доставлен юзеру 123
    mock_repo.get_delivered_keys.return_value = {DeliveredKeyDTO("2026-09-16", "src1", 123)}
    
    candidates = [
        NotificationSendDTO("test", "2026-09-16", "src1", 123, "Уже отправлено"),
        NotificationSendDTO("test", "2026-09-16", "src2", 123, "Новое уведомление"),
    ]
    
    await pipeline.execute(tick_ctx, candidates)
    
    # Отправлено должно быть только "src2"
    assert mock_dispatcher.send.call_count == 1
    call_args = mock_dispatcher.send.call_args[1]
    assert call_args["text"] == "Новое уведомление"
    assert tick_ctx.sent == 1

@pytest.mark.asyncio
async def test_pipeline_handles_send_failures(pipeline, mock_repo, mock_dispatcher, tick_ctx):
    """Регрессия: ошибка отправки логируется как failed и не пишется в delivery_log."""
    mock_dispatcher.send.return_value = False  # Отправка провалилась
    
    candidates = [NotificationSendDTO("test", "2026-09-16", "src1", 123, "Текст")]
    await pipeline.execute(tick_ctx, candidates)
    
    # Проверяем метрики
    assert tick_ctx.failed == 1
    assert tick_ctx.sent == 0
    # Проверяем, что лог доставки НЕ был записан
    mock_repo.record_notification_delivery.assert_not_called()

# --- Регрессионные тесты Коллектора ---

@pytest.mark.asyncio
async def test_collector_schedule_changes_window(tick_ctx):
    """
    Регрессия: PSN-настройки (changes_window_days). 
    Уведомления за пределами окна подписки должны игнорироваться.
    """
    # Мокаем зависимости коллектора
    time_service = MagicMock()
    # Текущая дата
    now = datetime.datetime(2026, 9, 16, 10, 0)
    time_service.get_now_base.return_value = now
    time_service.date_from_iso = lambda d: datetime.date.fromisoformat(d)
    
    repo = AsyncMock()
    # Замена расписания на 20 сентября (через 4 дня)
    repo.get_pending_changes.return_value = [
        PendingChangeDTO(
            id="change1", date="2026-09-20", period_id="1", class_id="10А", group_id="ALL",
            group_name=None, teacher_id=None, lesson_num=1, subject_id=None, subject_name="Химия",
            room_id=None, room_name="101", teacher_name=None, original_subject_id=None,
            original_subject_name="Биология", original_room_id=None, original_room_name="102",
            original_teacher_id=None, original_teacher_name=None, original_group_id=None,
            original_group_name=None, original_class_id=None, original_class_name=None,
            is_exchange=True, is_cancelled=False
        )
    ]
    
    # Два получателя: у одного окно 3 дня (не должен получить), у другого 7 дней (должен получить)
    repo.get_recipients_for_schedule_change.return_value = [
        ScheduleChangeRecipientDTO(student_id=1, recipient_id=101, changes_window_days=3, recipient_kind="student", child_name=None, watch_target_title=None),
        ScheduleChangeRecipientDTO(student_id=2, recipient_id=102, changes_window_days=7, recipient_kind="adult", child_name="Лиза", watch_target_title=None)
    ]
    
    schedule_service = AsyncMock()
    schedule_service.get_display_numbers_for_class_day.return_value = {1: "1"}
    
    collector = NotificationCollector(
        notification_repo=repo, time_service=time_service, schedule_repo=AsyncMock(),
        extra_classes_service=AsyncMock(), schedule_service=schedule_service
    )
    
    candidates = await collector.collect_upcoming_changes(tick_ctx)
    
    # Только юзер 102 (у кого окно 7 дней) должен стать кандидатом
    assert len(candidates) == 1
    assert candidates[0].recipient_id == 102
    assert tick_ctx.candidates == 1