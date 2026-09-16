# services/notification/pipeline.py

import logging

from core.repository.notification_repository import NotificationRepository
from core.models.dto import NotificationSendDTO, DeliveredKeyDTO
from .dispatcher import NotificationDispatcher
from .context import NotificationTickContext

logger = logging.getLogger(__name__)

class NotificationPipeline:
    """Оркестратор пайплайна: фильтрация (blocked_ids) -> дедупликация -> отправка -> persist."""

    def __init__(self, notification_repo: NotificationRepository, dispatcher: NotificationDispatcher) -> None:
        self.repo = notification_repo
        self.dispatcher = dispatcher

    async def _drop_already_delivered(self, pending: list[NotificationSendDTO]) -> list[NotificationSendDTO]:
        """
        Отфильтровывает уже отправленные уведомления.
        Строго использует DeliveredKeyDTO для генерации ключей и проверки в set.
        """
        if not pending:
            return []

        result: list[NotificationSendDTO] = []
        types = sorted({item.notification_type for item in pending})

        for notification_type in types:
            type_items = [item for item in pending if item.notification_type == notification_type]
            
            # 1. Генерируем массив DTO-ключей для репозитория
            candidate_keys = [
                DeliveredKeyDTO(
                    notification_date=item.notification_date,
                    source_id=item.source_id,
                    recipient_id=item.recipient_id,
                )
                for item in type_items
            ]
            
            # 2. Получаем set[DeliveredKeyDTO] от репозитория
            delivered: set[DeliveredKeyDTO] = await self.repo.get_delivered_keys(
                notification_type=notification_type,
                candidate_keys=candidate_keys,
            )
            
            # 3. Проверяем вхождение DTO в сет
            for item in type_items:
                key = DeliveredKeyDTO(
                    notification_date=item.notification_date,
                    source_id=item.source_id,
                    recipient_id=item.recipient_id,
                )
                if key not in delivered:
                    result.append(item)

        return result

    async def execute(self, ctx: NotificationTickContext, candidates: list[NotificationSendDTO]) -> None:
        """Единый пайплайн отправки уведомлений с записью метрик в контекст."""
        if not candidates:
            return

        # Инициализируем blocked_ids один раз за весь тик
        if not ctx.blocked_ids_loaded:
            try:
                ctx.blocked_ids = set(await self.repo.get_blocked_user_ids())
            except Exception:
                logger.exception("Failed to load blocked user ids")
                ctx.blocked_ids = set()
            ctx.blocked_ids_loaded = True

        # Фаза 1: Фильтрация blocked_ids
        if ctx.blocked_ids:
            candidates = [c for c in candidates if c.recipient_id not in ctx.blocked_ids]

        if not candidates:
            return

        # Фаза 2: Батчевая дедупликация
        to_send = await self._drop_already_delivered(candidates)

        # Фаза 3: Отправка и запись в лог
        for item in to_send:
            sent = await self.dispatcher.send(
                chat_id=item.recipient_id,
                text=item.text,
                action_type=item.action_type,        # ПРОКИДЫВАЕМ ACTION TYPE
                action_payload=item.action_payload,  # ПРОКИДЫВАЕМ ACTION PAYLOAD
            )
            
            if not sent:
                ctx.failed += 1
                logger.warning(
                    "Send failed: type=%s, source_id=%s, recipient_id=%s",
                    item.notification_type, item.source_id, item.recipient_id,
                )
                continue

            await self.repo.record_notification_delivery(
                notification_type=item.notification_type,
                notification_date=item.notification_date,
                source_id=item.source_id,
                recipient_id=item.recipient_id,
            )
            ctx.sent += 1