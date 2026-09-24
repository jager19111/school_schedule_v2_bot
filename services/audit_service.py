import logging
from typing import Optional
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.models.dto import (
    AuditAction, AuditLogDTO, FamilyAuditDTO, 
    ExtraClassAuditDTO, SettingsAuditDTO
)
from core.repository.audit_repository import AuditRepository
from core.repository.profile_repository import ProfileRepository
from services.time_service import TimeService
from bot.utils.ui_renderer import UIRenderer

file_logger = logging.getLogger("business_audit")

class AuditService:
    def __init__(
        self,
        audit_repo: AuditRepository,
        profile_repo: ProfileRepository,
        time_service: TimeService,
        log_dir: str = "logs"
    ):
        self.repo = audit_repo
        self.profile_repo = profile_repo
        self.time_service = time_service
        
        # Настройка файлового логгера
        file_logger.setLevel(logging.INFO)
        file_logger.propagate = False
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        if not file_logger.handlers:
            handler = RotatingFileHandler(
                filename=log_path / "audit.log",
                maxBytes=10485760, backupCount=10, encoding="utf8"
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            file_logger.addHandler(handler)

    async def log_action(
        self, 
        actor_id: int, 
        target_id: int, 
        action: AuditAction, 
        details: dict | None = None
    ) -> None:
        details = details or {}
        now = self.time_service.get_now_base()
        
        # 1. Транзакция в БД
        await self.repo.log(actor_id, target_id, action.value, now, details)
        
        # 2. Получение имен для человекочитаемого лога
        actor_row = await self.profile_repo.get_user_row(actor_id)
        target_row = await self.profile_repo.get_user_row(target_id)
        
        actor_name = actor_row["name"] if actor_row and actor_row["name"] else "Неизвестно"
        target_name = target_row["name"] if target_row and target_row["name"] else "Неизвестно"
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # 3. Фабрика DTO
        audit_dto = self._create_audit_dto(
            actor_id=actor_id,
            actor_name=actor_name,
            target_id=target_id,
            target_name=target_name,
            action=action,
            ts=timestamp_str,
            details=details
        )
        
        # 4. Рендеринг и запись в файл
        log_message = UIRenderer.render_audit_log(audit_dto)
        file_logger.info(log_message)

    def _create_audit_dto(
        self, 
        actor_id: int, actor_name: str, 
        target_id: int, target_name: str, 
        action: AuditAction, ts: str, details: dict
    ) -> AuditLogDTO:
        
        if action in (AuditAction.EXTRA_CLASS_ADDED, AuditAction.EXTRA_CLASS_DELETED):
            return ExtraClassAuditDTO(
                actor_id=actor_id, actor_name=actor_name, 
                target_id=target_id, target_name=target_name, 
                action=action.value, timestamp=ts,
                title=details.get("title", "?"), 
                student_name=details.get("student_name", "?")
            )
            
        if action in (AuditAction.FAMILY_CREATED, AuditAction.INVITE_CREATED, AuditAction.INVITE_USED):
            return FamilyAuditDTO(
                actor_id=actor_id, actor_name=actor_name, 
                target_id=target_id, target_name=target_name, 
                action=action.value, timestamp=ts,
                role=details.get("role"), 
                code=details.get("code")
            )
            
        if action in (AuditAction.SETTINGS_CHANGED, AuditAction.SETTINGS_LOCKED, AuditAction.EXTRA_CLASS_PERMISSION_CHANGED):
            return SettingsAuditDTO(
                actor_id=actor_id, actor_name=actor_name, 
                target_id=target_id, target_name=target_name, 
                action=action.value, timestamp=ts,
                setting_name=details.get("setting_name", "?"), 
                new_value=str(details.get("new_value", "?"))
            )
            
        return AuditLogDTO(
            actor_id=actor_id, actor_name=actor_name, 
            target_id=target_id, target_name=target_name, 
            action=action.value, timestamp=ts
        )