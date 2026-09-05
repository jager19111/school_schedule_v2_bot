import logging
from typing import Optional
from core.models.dto import ActionResponseDTO, ExtraClassItemDTO, ExtraClassListDTO, ExtraClassesAccessDTO
from core.repository.extra_classes_repository import ExtraClassesRepository
from services.time_service import TimeService
from core.repository.profile_repository import ProfileRepository


logger = logging.getLogger(__name__)

class ExtraClassesService:
    """Сервис бизнес-логики для управления дополнительными занятиями[cite: 2]."""
    
    def __init__(
        self,
        extra_classes_repo: ExtraClassesRepository,
        profile_repo: ProfileRepository,
        time_service: TimeService,
    ):
        self.repo = extra_classes_repo
        self.profile_repo = profile_repo
        self.time_service = time_service
        
    async def get_access(
        self,
        actor_user_id: int,
        target_child_id: int,
    ) -> ExtraClassesAccessDTO:
        """
        Возвращает права доступа через единый ProfileRepository policy.
        """
        row = await self.profile_repo.get_extra_classes_access(
            actor_user_id=actor_user_id,
            target_child_id=target_child_id,
        )

        if row is None:
            return ExtraClassesAccessDTO(
                actor_user_id=actor_user_id,
                target_child_id=target_child_id,
                can_view=False,
                can_manage=False,
            )

        return ExtraClassesAccessDTO(
            actor_user_id=actor_user_id,
            target_child_id=target_child_id,
            can_view=bool(row["can_view"]),
            can_manage=bool(row["can_manage"]),
        )

    async def _can_manage(
        self,
        actor_user_id: int,
        target_child_id: int,
    ) -> bool:
        access = await self.get_access(
            actor_user_id=actor_user_id,
            target_child_id=target_child_id,
        )
        return access.can_manage
    
    async def add_extra_class(
        self,
        *,
        actor_user_id: int,
        target_child_id: int,
        day_of_week: int,
        time_start: str,
        time_end: str,
        title: str,
        location: Optional[str],
        reminder_minutes: int,
    ) -> ActionResponseDTO:
        """
        Создаёт занятие ребёнку только при наличии manage-права у инициатора.
        """
        can_manage = await self._can_manage(
            actor_user_id=actor_user_id,
            target_child_id=target_child_id,
        )

        if not can_manage:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        if not 1 <= day_of_week <= 7:
            return ActionResponseDTO(
                success=False,
                error_code="invalid_day",
            )

        if not 0 <= reminder_minutes <= 180:
            return ActionResponseDTO(
                success=False,
                error_code="invalid_reminder",
            )

        if not self.time_service.validate_time_format(time_start):
            return ActionResponseDTO(
                success=False,
                error_code="invalid_time",
            )

        if not self.time_service.validate_time_format(time_end):
            return ActionResponseDTO(
                success=False,
                error_code="invalid_time",
            )

        if not self.time_service.validate_time_range(
            time_start,
            time_end,
        ):
            return ActionResponseDTO(
                success=False,
                error_code="invalid_time_range",
            )

        normalized_title = title.strip()

        if not normalized_title:
            return ActionResponseDTO(
                success=False,
                error_code="empty_title",
            )

        try:
            extra_id = await self.repo.create_extra_class(
                user_id=target_child_id,
                day_of_week=day_of_week,
                time_start=time_start,
                time_end=time_end,
                title=normalized_title,
                location=location.strip() if location else None,
                reminder_minutes=reminder_minutes,
            )

            return ActionResponseDTO(
                success=True,
                data={"extra_id": extra_id},
            )

        except ValueError as exc:
            logger.warning(
                "Extra class create rejected: actor_id=%s, target_id=%s, error=%s",
                actor_user_id,
                target_child_id,
                exc,
            )
            return ActionResponseDTO(
                success=False,
                error_code="invalid_target",
            )

        except Exception:
            logger.exception(
                "Extra class create failed: actor_id=%s, target_id=%s",
                actor_user_id,
                target_child_id,
            )
            return ActionResponseDTO(
                success=False,
                error_code="db_error",
            )
        
    async def get_user_extra_classes(
        self,
        *,
        actor_user_id: int,
        target_child_id: int,
    ) -> ActionResponseDTO:
        """
        Возвращает список занятий ребёнка только при наличии view-права.
        """
        access = await self.get_access(
            actor_user_id=actor_user_id,
            target_child_id=target_child_id,
        )

        if not access.can_view:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        rows = await self.repo.get_extra_classes_for_user(
            user_id=target_child_id,
        )

        items = [
            ExtraClassItemDTO(
                id=row["id"],
                day_of_week=row["day_of_week"],
                time_start=row["time_start"],
                time_end=row["time_end"],
                title=row["title"],
                location=row.get("location"),
                reminder_minutes=row["reminder_minutes"],
            )
            for row in rows
        ]

        return ActionResponseDTO(
            success=True,
            data=ExtraClassListDTO(items=items),
        )

    async def update_extra_class(
        self,
        *,
        actor_user_id: int,
        target_child_id: int,
        extra_id: int,
        **kwargs,
    ) -> ActionResponseDTO:
        """
        Изменяет занятие ребёнка только при manage-правах инициатора.
        """
        can_manage = await self._can_manage(
            actor_user_id=actor_user_id,
            target_child_id=target_child_id,
        )

        if not can_manage:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        if "day_of_week" in kwargs:
            day_of_week = kwargs["day_of_week"]

            if not 1 <= day_of_week <= 7:
                return ActionResponseDTO(
                    success=False,
                    error_code="invalid_day",
                )

        if "reminder_minutes" in kwargs:
            reminder_minutes = kwargs["reminder_minutes"]

            if not 0 <= reminder_minutes <= 180:
                return ActionResponseDTO(
                    success=False,
                    error_code="invalid_reminder",
                )

        if "time_start" in kwargs and not self.time_service.validate_time_format(
            kwargs["time_start"]
        ):
            return ActionResponseDTO(
                success=False,
                error_code="invalid_time",
            )

        if "time_end" in kwargs and not self.time_service.validate_time_format(
            kwargs["time_end"]
        ):
            return ActionResponseDTO(
                success=False,
                error_code="invalid_time",
            )

        updated = await self.repo.update_extra_class(
            extra_id=extra_id,
            user_id=target_child_id,
            **kwargs,
        )

        if updated:
            return ActionResponseDTO(success=True)

        return ActionResponseDTO(
            success=False,
            error_code="not_found",
        )

    async def delete_extra_class(
        self,
        *,
        actor_user_id: int,
        target_child_id: int,
        extra_id: int,
    ) -> ActionResponseDTO:
        """
        Удаляет занятие ребёнка только при manage-правах инициатора.
        """
        can_manage = await self._can_manage(
            actor_user_id=actor_user_id,
            target_child_id=target_child_id,
        )

        if not can_manage:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        deleted = await self.repo.delete_extra_class(
            extra_id=extra_id,
            user_id=target_child_id,
        )

        if deleted:
            return ActionResponseDTO(success=True)

        return ActionResponseDTO(
            success=False,
            error_code="not_found",
        )