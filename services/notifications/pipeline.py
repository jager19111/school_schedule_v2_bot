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
            
            # 1. Генерируем массив DTO-ключей для репозитория
            candidate_keys = [
                DeliveredKeyDTO(
                    notification_date=item.notification_date,
                    source_id=item.source_id,
                    recipient_id=item.recipient_id,
                )
                for item in type_items
            ]
            
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
                key = DeliveredKeyDTO(
                    notification_date=item.notification_date,
                    source_id=item.source_id,
                    recipient_id=item.recipient_id,
                )
                if key not in delivered:
                    # ВАЖНО: Добавляем в сет прямо сейчас, чтобы предотвратить 
                    # дубли source_id внутри одного тика
                    delivered.add(key)
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

        # ВАЖНО: Семантическая дедупликация (Защита от дублей подгрупп NIKA)
        # Если в расписании NIKA 2 записи об отмене для разных групп, а ученик подписан
        # на "Весь класс", он соберет 2 кандидата. Так как текст у них 100% идентичный,
        # мы оставляем только один, чтобы не спамить.
        unique_candidates = []
        seen_texts = set()
        for c in candidates:
            sig = (c.recipient_id, c.text)
            if sig not in seen_texts:
                seen_texts.add(sig)
                unique_candidates.append(c)

        # Фаза 2: Батчевая дедупликация базы данных
        to_send = await self._drop_already_delivered(ctx, unique_candidates)
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
                    "Pipeline send failed: type=%s, source_id=%s, recipient_id=%s",
                    item.notification_type, item.source_id, item.recipient_id,
                )
                continue

            try:
                await self.repo.record_notification_delivery(
                    notification_type=item.notification_type,
                    notification_date=item.notification_date,
                    source_id=item.source_id,
                    recipient_id=item.recipient_id,
                )
                ctx.queries += 1
            except Exception as e:
                # Ошибка записи не должна ломать статистику sent, но о ней нужно знать
                logger.error("Infrastructure error: Failed to record delivery for %s: %s", item.source_id, e)

            ctx.sent += 1