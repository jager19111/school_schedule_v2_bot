# services/notification/pipeline.py

import logging
from typing import Tuple

from core.repository.notification_repository import NotificationRepository
from core.models.dto import NotificationSendDTO, DeliveredKeyDTO
from .dispatcher import NotificationDispatcher

logger = logging.getLogger(__name__)

class NotificationPipeline:
    """
    Оркестратор пайплайна: фильтрация (blocked_ids) -> батчевая дедупликация -> отправка -> persist.
    """

    def __init__(
        self,
        notification_repo: NotificationRepository,
        dispatcher: NotificationDispatcher,
    ) -> None:
        self.repo = notification_repo
        self.dispatcher = dispatcher

    async def _load_blocked_recipient_ids(self) -> set[int]:
        try:
            return set(await self.repo.get_blocked_user_ids())
        except Exception:
            logger.exception("Failed to load blocked user ids")
            return set()

    async def _drop_already_delivered(self, pending: list[NotificationSendDTO]) -> list[NotificationSendDTO]:
        if not pending:
            return []

        result: list[NotificationSendDTO] = []
        types = sorted({item.notification_type for item in pending})

        for notification_type in types:
            type_items = [item for item in pending if item.notification_type == notification_type]
            candidate_keys = [
                DeliveredKeyDTO(
                    notification_date=item.notification_date,
                    source_id=item.source_id,
                    recipient_id=item.recipient_id,
                )
                for item in type_items
            ]
            delivered = await self.repo.get_delivered_keys(
                notification_type=notification_type,
                candidate_keys=candidate_keys,
            )
            for item in type_items:
                key = DeliveredKeyDTO(
                    notification_date=item.notification_date,
                    source_id=item.source_id,
                    recipient_id=item.recipient_id,
                )
                if key not in delivered:
                    result.append(item)

        return result

    async def execute(self, candidates: list[NotificationSendDTO]) -> Tuple[int, int]:
        """Единый пайплайн отправки уведомлений."""
        if not candidates:
            return 0, 0

        # Фаза 1: Фильтрация blocked_ids
        blocked_ids = await self._load_blocked_recipient_ids()
        if blocked_ids:
            candidates = [c for c in candidates if c.recipient_id not in blocked_ids]

        if not candidates:
            return 0, 0

        # Фаза 2: Батчевая дедупликация
        to_send = await self._drop_already_delivered(candidates)

        # Фаза 3: Отправка и запись в лог
        sent_count = 0
        failed_count = 0

        for item in to_send:
            sent = await self.dispatcher.send(
                chat_id=item.recipient_id,
                text=item.text,
                reply_markup=item.reply_markup,
            )
            if not sent:
                failed_count += 1
                logger.warning(
                    "Send failed: type=%s, source_id=%s, recipient_id=%s, context=%s",
                    item.notification_type, item.source_id, item.recipient_id, item.context,
                )
                continue

            await self.repo.record_notification_delivery(
                notification_type=item.notification_type,
                notification_date=item.notification_date,
                source_id=item.source_id,
                recipient_id=item.recipient_id,
            )
            sent_count += 1

        return sent_count, failed_count