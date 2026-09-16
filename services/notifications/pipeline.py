# services/notification/pipeline.py

import logging

from core.repository.notification_repository import NotificationRepository
from core.models.dto import NotificationSendDTO, DeliveredKeyDTO
from .dispatcher import NotificationDispatcher
from .context import NotificationTickContext

logger = logging.getLogger(__name__)

class NotificationPipeline:
    """
    Универсальный оркестратор пайплайна.
    Не содержит бизнес-логики и не знает о конкретных сценариях.
    Опирается только на атрибуты NotificationSendDTO.
    """

    def __init__(self, notification_repo: NotificationRepository, dispatcher: NotificationDispatcher) -> None:
        self.repo = notification_repo
        self.dispatcher = dispatcher

    async def _drop_already_delivered(self, ctx: NotificationTickContext, pending: list[NotificationSendDTO]) -> list[NotificationSendDTO]:
        """
        Отфильтровывает уже отправленные уведомления.
        Строго использует DeliveredKeyDTO для генерации ключей и проверки в set.
        """
        if not pending:
            return []

        result: list[NotificationSendDTO] = []
        
        # ДИНАМИЧЕСКАЯ ГРУППИРОВКА: пайплайн не знает, что именно он отправляет.
        # Он просто собирает уникальные типы из DTO кандидатов.
        types = sorted({item.notification_type for item in pending})

        for notification_type in types:
            type_items = [item for item in pending if item.notification_type == notification_type]
            
            # Собираем все ключи из вложенных списков source_ids
            candidate_keys = []
            for item in type_items:
                for sid in item.source_ids:
                    candidate_keys.append(DeliveredKeyDTO(item.notification_date, sid, item.recipient_id))
            
            try:
                delivered = await self.repo.get_delivered_keys(
                    notification_type=notification_type,
                    candidate_keys=candidate_keys,
                )
                ctx.queries += 1
            except Exception as e:
                logger.error("Infrastructure error: Failed to fetch delivered keys: %s", e)
                # Fallback: Если БД недоступна, считаем, что ничего не доставлено, чтобы не подавлять отправку
                delivered = set()
                
            for item in type_items:
                # Если хотя бы один ID из склеенного сообщения еще не доставлялся — отправляем всё сообщение
                is_new = False
                for sid in item.source_ids:
                    key = DeliveredKeyDTO(item.notification_date, sid, item.recipient_id)
                    if key not in delivered:
                        is_new = True
                        delivered.add(key)  # Защита от дублей внутри одного тика
                        
                if is_new:
                    result.append(item)

        return result

    async def execute(self, ctx: NotificationTickContext, candidates: list[NotificationSendDTO]) -> None:
        """Единый пайплайн отправки уведомлений с записью метрик в контекст."""
        if not candidates:
            return

        # Фаза 1: Фильтрация blocked_ids
        if not ctx.blocked_ids_loaded:
            try:
                ctx.blocked_ids = set(await self.repo.get_blocked_user_ids())
                ctx.queries += 1
            except Exception as e:
                logger.error("Access error: Failed to load blocked user ids: %s", e)
                ctx.blocked_ids = set()
            ctx.blocked_ids_loaded = True

        # Фаза 1: Фильтрация blocked_ids
        if ctx.blocked_ids:
            candidates = [c for c in candidates if c.recipient_id not in ctx.blocked_ids]

        if not candidates:
            return

        to_send = await self._drop_already_delivered(ctx, candidates)
        ctx.pending += len(to_send)

        # Фаза 3: Отправка и запись в лог
        for item in to_send:
            sent = await self.dispatcher.send(
                chat_id=item.recipient_id,
                text=item.text,
                action_type=item.action_type,
                action_payload=item.action_payload,
            )
            
            if not sent:
                ctx.failed += 1
                # Ошибки отправки (Send error) уже залогированы внутри диспетчера с полным контекстом Telegram
                logger.debug(
                    "Pipeline send failed: type=%s, sources=%s, recipient_id=%s",
                    item.notification_type, len(item.source_ids), item.recipient_id,
                )
                continue

            try:
                # Записываем в базу каждый отправленный урок по отдельности
                for sid in item.source_ids:
                    await self.repo.record_notification_delivery(
                        notification_type=item.notification_type,
                        notification_date=item.notification_date,
                        source_id=sid,
                        recipient_id=item.recipient_id,
                    )
                ctx.queries += len(item.source_ids)
            except Exception as e:
                logger.error("Infrastructure error: Failed to record delivery: %s", e)

            ctx.sent += 1