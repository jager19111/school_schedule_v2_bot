from __future__ import annotations

from typing import List, Optional

from core.models.dto import (
    ActionResponseDTO,
    StudentAccessDTO,
    StudentProfileDTO,
)
from core.repository.student_repository import StudentRepository


class StudentsService:
    """
    Бизнес-логика учеников, независимых от Telegram.
    """

    def __init__(
        self,
        repository: StudentRepository,
    ):
        self.repo = repository

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