# services/broadcast_service.py
#
# Бизнес-логика admin-рассылок.
#
# ПРАВИЛА ПРОЕКТА:
# - не содержит SQL (всё через BroadcastRepository);
# - аудитория — только через ProfileService (роли/активность);
# - отправка — только через NotificationDispatcher.send_broadcast():
#   общий глобальный троттлинг со всеми уведомлениями бота;
# - идемпотентность: try_start_sending атомарный, повторное
#   подтверждение не отправляет рассылку дважды;
# - аудит: AuditAction.BROADCAST_SENT, payload без текста рассылки;
# - время — TimeService не нужен: все таймстемпы пишет repository.

from __future__ import annotations

import logging
from typing import Optional

from core.models.dto import (
    AuditAction,
    BroadcastAudience,
    BroadcastAudienceDTO,
    BroadcastCreatedDTO,
    BroadcastReportDTO,
)
from core.repository.broadcast_repository import BroadcastRepository
from services.audit_service import AuditService
from services.notifications.dispatcher import NotificationDispatcher
from services.profiles_service import ProfileService

logger = logging.getLogger(__name__)


class BroadcastService:
    """
    Рассылки администратора: черновик -> предпросмотр -> отправка.

    Один broadcast = одно сообщение (текст, опционально фото+caption,
    опциональная URL-кнопка).
    """

    DELIVERY_BATCH_SIZE = 100

    def __init__(
        self,
        repo: BroadcastRepository,
        profile_service: ProfileService,
        dispatcher: NotificationDispatcher,
        audit_service: AuditService,
    ) -> None:
        self._repo = repo
        self._profiles = profile_service
        self._dispatcher = dispatcher
        self._audit = audit_service

    async def cleanup_stale_drafts(self, *, older_than_utc: str) -> int:
        return await self._repo.cleanup_stale_drafts(
            older_than_utc=older_than_utc,
        )
        
    # ==========================================================
    # Аудитория / черновики
    # ==========================================================

    async def get_audience_count(
        self,
        audience: BroadcastAudience,
    ) -> int:
        dto = await self._profiles.get_broadcast_audience(audience)
        return len(dto.recipient_ids)

    async def create_draft(
        self,
        *,
        admin_user_id: int,
        audience: BroadcastAudience,
        text: str,
        photo_file_id: Optional[str] = None,
        button_text: Optional[str] = None,
        button_url: Optional[str] = None,
    ) -> BroadcastCreatedDTO:
        recipient_count = await self.get_audience_count(audience)
        broadcast_id = await self._repo.create_broadcast(
            admin_user_id=admin_user_id,
            audience=audience.value,
            text=text,
            photo_file_id=photo_file_id,
            button_text=button_text,
            button_url=button_url,
        )
        return BroadcastCreatedDTO(
            broadcast_id=broadcast_id,
            audience=audience,
            recipient_count=recipient_count,
        )

        async def update_draft(
            self,
            *,
            broadcast_id: int,
            text: str,
            photo_file_id: Optional[str],
            button_text: Optional[str],
            button_url: Optional[str],
        ) -> None:
            """Перезапись после «Изменить» (аудитория не зависит от контента)."""
            await self._repo.update_draft(
                broadcast_id=broadcast_id,
                text=text,
                photo_file_id=photo_file_id,
                button_text=button_text,
                button_url=button_url,
            )

    async def cancel_draft(
        self,
        *,
        broadcast_id: int,
    ) -> bool:
        return await self._repo.cancel_draft(broadcast_id=broadcast_id)

    # ==========================================================
    # Отправка
    # ==========================================================
    async def run_broadcast(
        self,
        *,
        broadcast_id: int,
        admin_user_id: int,
    ) -> Optional[BroadcastReportDTO]:
        """
        Отправляет рассылку.

        None — рассылка уже выполняется или выполнена
        (идемпотентность: try_start_sending вернул False).
        """
        if not await self._repo.try_start_sending(
            broadcast_id=broadcast_id,
        ):
            return None

        broadcast = await self._repo.get_broadcast(
            broadcast_id=broadcast_id,
        )
        if broadcast is None:
            logger.error(
                "Broadcast row lost after start: broadcast_id=%s",
                broadcast_id,
            )
            await self._repo.finish_broadcast(broadcast_id=broadcast_id)
            return None

        audience = BroadcastAudience(broadcast["audience"])
        audience_dto: BroadcastAudienceDTO = (
            await self._profiles.get_broadcast_audience(audience)
        )

        await self._repo.set_recipient_count(
            broadcast_id=broadcast_id,
            recipient_count=len(audience_dto.recipient_ids),
        )
        await self._repo.create_deliveries(
            broadcast_id=broadcast_id,
            user_ids=list(audience_dto.recipient_ids),
        )

        text = str(broadcast["text"])
        photo_file_id = broadcast.get("photo_file_id")
        button_text = broadcast.get("button_text")
        button_url = broadcast.get("button_url")

        while True:
            batch = await self._repo.get_pending_deliveries(
                broadcast_id=broadcast_id,
                limit=self.DELIVERY_BATCH_SIZE,
            )
            if not batch:
                break

            for row in batch:
                sent = await self._dispatcher.send_broadcast(
                    chat_id=int(row["user_id"]),
                    text=text,
                    photo_file_id=photo_file_id,
                    button_text=button_text,
                    button_url=button_url,
                )
                await self._repo.mark_delivery(
                    delivery_id=int(row["id"]),
                    status="sent" if sent else "failed",
                    error_code=None if sent else "send_failed",
                )

        await self._repo.finish_broadcast(broadcast_id=broadcast_id)

        counts = await self._repo.get_delivery_counts(
            broadcast_id=broadcast_id,
        )
        report = BroadcastReportDTO(
            broadcast_id=broadcast_id,
            audience=audience,
            recipient_count=len(audience_dto.recipient_ids),
            sent=counts.get("sent", 0),
            failed=counts.get("failed", 0),
            skipped=audience_dto.skipped
        )

        # Аудит: только метаданные, текст рассылки не пишется.
        await self._audit.log_action(
            actor_id=admin_user_id,
            target_id=admin_user_id,
            action=AuditAction.BROADCAST_SENT,
            details={
                "broadcast_id": broadcast_id,
                "audience": audience.value,
                "sent": report.sent,
                "failed": report.failed,
                "skipped": report.skipped,
            },
        )

        logger.info(
            "Broadcast finished: id=%s audience=%s sent=%s "
            "failed=%s skipped=%s",
            broadcast_id,
            audience.value,
            report.sent,
            report.failed,
            report.skipped,
        )
        return report
    async def get_owned_draft_audience(
        self,
        *,
        broadcast_id: int,
        admin_user_id: int,
    ) -> Optional[BroadcastAudience]:
        """
        Аудитория черновика, если он существует, ещё draft
        и принадлежит этому админу.

        None — не найден / отправлен / отменён / чужой.
        Callback payload не является источником доверия.
        """
        broadcast = await self._repo.get_broadcast(
            broadcast_id=broadcast_id,
        )
        if broadcast is None or broadcast["status"] != "draft":
            return None
        if int(broadcast["admin_user_id"]) != admin_user_id:
            return None
        return BroadcastAudience(broadcast["audience"])

    
    async def cleanup_stale_drafts(self, *, older_than_utc: str) -> int:
        return await self._repo.cleanup_stale_drafts(
            older_than_utc=older_than_utc,
        )