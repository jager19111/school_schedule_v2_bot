# services/notifications_service.py

import logging
from typing import Optional

from core.models.dto import NotificationSendDTO, DebugBurstResultDTO
from services.time_service import TimeService

from .notifications.context import NotificationTickContext
from .notifications.collector import NotificationCollector
from .notifications.pipeline import NotificationPipeline
from .notifications.dispatcher import NotificationDispatcher

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Тонкий фасад для управления уведомлениями.
    Связывает Collector (сбор данных) и Pipeline (дедупликация и отправка),
    используя общий NotificationTickContext для разделения кешей.
    """

    def __init__(
        self,
        collector: NotificationCollector,
        pipeline: NotificationPipeline,
        dispatcher: NotificationDispatcher,
        time_service: TimeService,
    ) -> None:
        self.collector = collector
        self.pipeline = pipeline
        self.dispatcher = dispatcher
        self.time_service = time_service

    async def send_morning_reminders(self) -> None:
        """Отправляет утренние сводки (ученикам/родителям и учителям)."""
        ctx = NotificationTickContext()
        
        candidates = await self.collector.collect_morning_summaries(ctx)
        await self.pipeline.execute(ctx, candidates)
        
        t_candidates = await self.collector.collect_teacher_morning_summaries(ctx)
        await self.pipeline.execute(ctx, t_candidates)
        
        logger.info("Morning summary %s", ctx.metrics_summary)

    async def send_upcoming_changes(self) -> None:
        """Отправляет адресные уведомления о заменах и отменах."""
        ctx = NotificationTickContext()
        
        candidates = await self.collector.collect_upcoming_changes(ctx)
        await self.pipeline.execute(ctx, candidates)
        
        logger.info("Schedule changes %s", ctx.metrics_summary)

    async def send_pre_lesson_reminders(self) -> None:
        """Отправляет предурочные напоминания (ученикам, родителям, учителям)."""
        ctx = NotificationTickContext()
        
        candidates = await self.collector.collect_pre_lesson_reminders(ctx)
        await self.pipeline.execute(ctx, candidates)
        
        logger.info("Pre-lesson reminder %s", ctx.metrics_summary)

    async def send_extra_class_reminders(self) -> None:
        """Отправляет напоминания о дополнительных занятиях."""
        ctx = NotificationTickContext()
        
        candidates = await self.collector.collect_extra_class_reminders(ctx)
        await self.pipeline.execute(ctx, candidates)
        
        logger.info("Extra class reminder %s", ctx.metrics_summary)

    async def send_admin_alert(self, alert_key: str, text: str) -> None:
        """Дедуплицированный алерт всем админам."""
        await self.dispatcher.send_admin_alert(alert_key=alert_key, text=text)

    async def debug_send_burst(self, chat_id: int, count: int) -> DebugBurstResultDTO:
        """Стресс-тест уведомлений через полный пайплайн (только для админа)."""
        count = max(1, min(count, 500))
        today_iso = self.time_service.get_now_base().date().isoformat()
        ctx = NotificationTickContext()

        pending = [
            NotificationSendDTO(
                notification_type="debug_test",
                notification_date=today_iso,
                source_id=f"debug_burst:{index}",
                recipient_id=chat_id,
                text=f"🧪 Стресс-тест уведомлений: сообщение {index + 1} из {count}",
                context="stress_test",
            )
            for index in range(count)
        ]

        await self.pipeline.execute(ctx, pending)

        return DebugBurstResultDTO(
            requested=len(pending),
            pending=0,
            sent=ctx.sent,
            failed=ctx.failed,
        )