# services/notifications_service.py

import logging
from typing import Optional

from core.models.dto import NotificationSendDTO, DebugBurstResultDTO
from services.time_service import TimeService

from .notifications.collector import NotificationCollector
from .notifications.pipeline import NotificationPipeline
from .notifications.dispatcher import NotificationDispatcher

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Тонкий фасад для управления уведомлениями.
    Связывает Collector (сбор данных) и Pipeline (дедупликация и отправка).
    API полностью совместим с текущими хендлерами и задачами APScheduler.
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
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()
        current_time_str = now.strftime("%H:%M")

        # 1. Сводки учеников и родителей
        logger.info("Morning summary tick: date=%s, time=%s", today_iso, current_time_str)
        candidates, tasks_count = await self.collector.collect_morning_summaries()
        if tasks_count > 0:
            sent, failed = await self.pipeline.execute(candidates)
            logger.info("Morning summary tick done: tasks=%d, sent=%d, failed=%d", tasks_count, sent, failed)

        # 2. Учительские сводки
        t_candidates, t_tasks_count = await self.collector.collect_teacher_morning_summaries()
        if t_tasks_count > 0:
            t_sent, t_failed = await self.pipeline.execute(t_candidates)
            logger.info("Teacher morning summary tick done: tasks=%d, sent=%d, failed=%d", t_tasks_count, t_sent, t_failed)

    async def send_upcoming_changes(self) -> None:
        """Отправляет адресные уведомления о заменах и отменах."""
        now = self.time_service.get_now_base()
        logger.info("Schedule changes tick: date=%s", now.date().isoformat())
        
        candidates, changes_len, rec_queries, teach_queries = await self.collector.collect_upcoming_changes()
        sent, failed = await self.pipeline.execute(candidates)
        
        logger.info(
            "Schedule changes tick done: changes=%d, candidates=%d, sent=%d, failed=%d, recipient_queries=%d, teacher_queries=%d",
            changes_len, len(candidates), sent, failed, rec_queries, teach_queries,
        )

    async def send_pre_lesson_reminders(self) -> None:
        """Отправляет предурочные напоминания (ученикам, родителям, учителям)."""
        now = self.time_service.get_now_base()
        logger.info("Pre-lesson reminder tick: date=%s", now.date().isoformat())
        
        candidates, lessons_len, rec_queries, teach_queries = await self.collector.collect_pre_lesson_reminders()
        sent, failed = await self.pipeline.execute(candidates)
        
        logger.info(
            "Pre-lesson tick done: lessons=%d, candidates=%d, sent=%d, failed=%d, recipient_queries=%d, teacher_queries=%d",
            lessons_len, len(candidates), sent, failed, rec_queries, teach_queries,
        )

    async def send_extra_class_reminders(self) -> None:
        """Отправляет напоминания о дополнительных занятиях."""
        now = self.time_service.get_now_base()
        logger.info("Extra reminder tick: date=%s", now.date().isoformat())

        candidates = await self.collector.collect_extra_class_reminders()
        sent, failed = await self.pipeline.execute(candidates)
        
        logger.info(
            "Extra reminder tick done: candidates=%d, sent=%d, failed=%d",
            len(candidates), sent, failed,
        )

    async def send_admin_alert(self, alert_key: str, text: str) -> None:
        """Дедуплицированный алерт всем админам."""
        await self.dispatcher.send_admin_alert(alert_key=alert_key, text=text)

    async def debug_send_burst(self, chat_id: int, count: int) -> DebugBurstResultDTO:
        """Стресс-тест уведомлений через полный пайплайн (только для админа)."""
        count = max(1, min(count, 500))
        today_iso = self.time_service.get_now_base().date().isoformat()

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

        sent, failed = await self.pipeline.execute(pending)

        return DebugBurstResultDTO(
            requested=len(pending),
            pending=0,
            sent=sent,
            failed=failed,
        )