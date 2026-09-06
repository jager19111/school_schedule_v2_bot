from __future__ import annotations

from typing import List, Optional

from core.models.dto import (
    ActionResponseDTO,
    StudentAccessDTO,
    StudentProfileDTO, StudentClaimInviteDTO,
)
from core.repository.student_repository import StudentRepository
from services.profiles_service import ProfileService


class StudentsService:
    """
    Бизнес-логика учеников, независимых от Telegram.
    """

    def __init__(
        self,
        student_repo: StudentRepository,
        profile_service: ProfileService,
    ):
        self.repo = student_repo
        self.profile_service = profile_service

    @staticmethod
    def _student_dto_from_row(
        row: dict,
    ) -> StudentProfileDTO:
        return StudentProfileDTO(
            id=row["id"],
            family_id=row["family_id"],
            telegram_user_id=row.get("telegram_user_id"),
            name=row["name"],
            class_id=row["class_id"],
            group_id=row["group_id"],
            is_active=bool(row["is_active"]),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    @staticmethod
    def _claim_invite_dto_from_row(
        row: dict,
    ) -> StudentClaimInviteDTO:
        return StudentClaimInviteDTO(
            id=row["id"],
            token=row["token"],

            student_id=row["student_id"],
            family_id=row["family_id"],

            created_by_user_id=row["created_by_user_id"],

            expires_at=row["expires_at"],

            is_revoked=bool(row["is_revoked"]),

            used_by_user_id=row.get("used_by_user_id"),
            created_at=row.get("created_at"),
            used_at=row.get("used_at"),

            student_name=row.get("student_name"),
            student_class_id=row.get("student_class_id"),
            student_group_id=row.get("student_group_id"),
        )
        
    @staticmethod
    def _access_dto_from_row(
        *,
        adult_user_id: int,
        row: dict,
    ) -> StudentAccessDTO:
        return StudentAccessDTO(
            adult_user_id=adult_user_id,
            student_id=row["id"],
            can_view=bool(row["can_view"]),
            can_manage_extra_classes=bool(
                row["can_manage_extra_classes"]
            ),
            is_family_admin=bool(row["is_family_admin"]),
        )

    async def get_students_for_adult(
        self,
        *,
        adult_user_id: int,
    ) -> List[StudentProfileDTO]:
        rows = await self.repo.get_students_for_adult(
            adult_user_id=adult_user_id,
        )

        return [
            self._student_dto_from_row(row)
            for row in rows
        ]

    async def get_student_for_adult(
        self,
        *,
        adult_user_id: int,
        student_id: int,
    ) -> Optional[tuple[StudentProfileDTO, StudentAccessDTO]]:
        row = await self.repo.get_student_for_adult(
            adult_user_id=adult_user_id,
            student_id=student_id,
        )

        if row is None or not bool(row["can_view"]):
            return None

        return (
            self._student_dto_from_row(row),
            self._access_dto_from_row(
                adult_user_id=adult_user_id,
                row=row,
            ),
        )

    async def create_virtual_student(
        self,
        *,
        admin_user_id: int,
        family_id: int,
        name: str,
        class_id: str,
        group_id: str,
    ) -> ActionResponseDTO:
        name = name.strip()
        class_id = class_id.strip()
        group_id = group_id.strip() or "ALL"

        if not name:
            return ActionResponseDTO(
                success=False,
                error_code="invalid_name",
            )

        if len(name) > 64:
            return ActionResponseDTO(
                success=False,
                error_code="name_too_long",
            )

        if not class_id:
            return ActionResponseDTO(
                success=False,
                error_code="invalid_class",
            )

        row = await self.repo.create_virtual_student(
            admin_user_id=admin_user_id,
            family_id=family_id,
            name=name,
            class_id=class_id,
            group_id=group_id,
        )

        if row is None:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        return ActionResponseDTO(
            success=True,
            data=self._student_dto_from_row(row),
        )

    async def update_student_profile(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        name: Optional[str] = None,
        class_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> ActionResponseDTO:
        if name is not None:
            name = name.strip()

            if not name:
                return ActionResponseDTO(
                    success=False,
                    error_code="invalid_name",
                )

        if group_id is not None:
            group_id = group_id.strip() or "ALL"

        updated = await self.repo.update_student_profile(
            admin_user_id=admin_user_id,
            student_id=student_id,
            name=name,
            class_id=class_id,
            group_id=group_id,
        )

        if not updated:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied_or_not_found",
            )

        return ActionResponseDTO(success=True)

    async def delete_virtual_student(
        self,
        *,
        admin_user_id: int,
        student_id: int,
    ) -> ActionResponseDTO:
        deleted = await self.repo.delete_virtual_student(
            admin_user_id=admin_user_id,
            student_id=student_id,
        )

        if not deleted:
            return ActionResponseDTO(
                success=False,
                error_code="linked_or_not_found",
            )

        return ActionResponseDTO(success=True)
    
    async def get_student_by_telegram_user_id(
        self,
        *,
        telegram_user_id: int,
    ) -> Optional[StudentProfileDTO]:
        """
        Возвращает student_profile Telegram-ребёнка.
        """
        row = await self.repo.get_student_by_telegram_user_id(
            telegram_user_id=telegram_user_id,
        )

        if row is None:
            return None

        return self._student_dto_from_row(row)
    
    
                
    async def ensure_telegram_student_profile(
        self,
        *,
        telegram_user_id: int,
    ) -> Optional[StudentProfileDTO]:
        """
        Создаёт или синхронизирует student profile Telegram-ребёнка.

        Поддерживает:
        - ребёнка в семье;
        - самостоятельного ребёнка без семьи.

        Для ребёнка в семье repository дополнительно создаёт
        parent_student_settings взрослым этой семьи.
        """
        user = await self.profile_service.get_user_profile_dto(
            telegram_user_id,
        )

        if user.role != "child":
            return None

        if user.class_id is None:
            return None

        # 3. Делегируем единый запрос репозиторию
        row = await self.repo.upsert_telegram_student(
            telegram_user_id=telegram_user_id,
            family_id=user.family_id,
            name=user.name or "Ученик",
            class_id=user.class_id,
            group_id=user.group_id or "ALL",
        )

        if row is None:
            return None

        return self._student_dto_from_row(row)
    
    async def create_student_claim_invite(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        expires_in_hours: int = 24,
    ) -> Optional[StudentClaimInviteDTO]:
        """
        Выпускает одноразовый claim invite virtual student.

        Только family admin может создать ссылку.
        """
        row = await self.repo.create_student_claim_invite(
            admin_user_id=admin_user_id,
            student_id=student_id,
            expires_in_hours=expires_in_hours,
        )

        if row is None:
            return None

        return self._claim_invite_dto_from_row(row)

    async def get_valid_student_claim_invite(
        self,
        *,
        token: str,
    ) -> Optional[StudentClaimInviteDTO]:
        """
        Возвращает валидный claim invite для deep-link flow.
        """
        row = await self.repo.get_valid_student_claim_invite(
            token=token,
        )

        if row is None:
            return None

        return self._claim_invite_dto_from_row(row)

    async def consume_student_claim_invite(
        self,
        *,
        token: str,
        telegram_user_id: int,
        name: str,
        class_id: str,
        group_id: str,
    ) -> ActionResponseDTO:
        """
        Привязывает Telegram account к virtual student profile.

        Имя, класс и группа берутся из claim registration flow.
        """
        normalized_name = name.strip()
        normalized_class_id = class_id.strip()
        normalized_group_id = group_id.strip() or "ALL"

        if not normalized_name:
            return ActionResponseDTO(
                success=False,
                error_code="invalid_name",
            )

        if len(normalized_name) > 64:
            return ActionResponseDTO(
                success=False,
                error_code="name_too_long",
            )

        if not normalized_class_id:
            return ActionResponseDTO(
                success=False,
                error_code="invalid_class",
            )

        row = await self.repo.consume_student_claim_invite(
            token=token,
            telegram_user_id=telegram_user_id,
            name=normalized_name,
            class_id=normalized_class_id,
            group_id=normalized_group_id,
        )

        if row is None:
            return ActionResponseDTO(
                success=False,
                error_code="claim_unavailable",
            )

        return ActionResponseDTO(
            success=True,
            data=self._student_dto_from_row(row),
        )