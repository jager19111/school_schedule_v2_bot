from __future__ import annotations

import logging
from typing import Any, Optional, List

from core.models.dto import (
    ActionResponseDTO,
    ExtraClassItemDTO, ExtraClassViewModel,
    ExtraClassListDTO, ExtraClassesAccessDTO
)
from core.repository.extra_classes_repository import (
    ExtraClassesRepository,
)
from services.profiles_service import ProfileService
from services.students_service import StudentsService
from services.time_service import TimeService


logger = logging.getLogger(__name__)


class ExtraClassesService:
    """
    Сервис управления дополнительными занятиями.

    Владелец каждого занятия — student_profiles.id.

    Доступ:
    - child: только собственный student profile, если Telegram user
      связан с этим student profile;
    - parent/observer: только student profiles, доступные через
      parent_student_settings;
    - управление взрослыми регулируется
      can_manage_extra_classes;
    - управление ребёнком регулируется
      can_manage_own_extra_classes.
    """

    def __init__(
        self,
        extra_classes_repo: ExtraClassesRepository,
        profile_service: ProfileService,
        students_service: StudentsService,
        time_service: TimeService,
    ) -> None:
        self.repo = extra_classes_repo
        self.profile_service = profile_service
        self.students_service = students_service
        self.time_service = time_service

    async def get_access(
        self,
        *,
        actor_user_id: int,
        target_student_id: int,
    ) -> ExtraClassesAccessDTO:
        """
        Возвращает права actor_user_id на занятия student profile.

        Этот метод должен вызываться перед чтением и перед каждой
        изменяющей операцией. FSM и callback_data доверять нельзя.
        """
        actor = await self.profile_service.get_user_profile_dto(
            actor_user_id,
        )

        if actor.role == "child":
            student = (
                await self.students_service.get_student_by_telegram_user_id(
                    telegram_user_id=actor_user_id,
                )
            )

            is_own_student = (
                student is not None
                and student.id == target_student_id
                and student.is_active
            )

            return ExtraClassesAccessDTO(
                actor_user_id=actor_user_id,
                target_student_id=target_student_id,
                can_view=is_own_student,
                can_manage=(
                    is_own_student
                    and actor.can_manage_own_extra_classes
                ),
            )

        if actor.role not in ("parent", "observer"):
            return ExtraClassesAccessDTO(
                actor_user_id=actor_user_id,
                target_student_id=target_student_id,
                can_view=False,
                can_manage=False,
            )

        result = await self.students_service.get_student_for_adult(
            adult_user_id=actor_user_id,
            student_id=target_student_id,
        )

        if result is None:
            return ExtraClassesAccessDTO(
                actor_user_id=actor_user_id,
                target_student_id=target_student_id,
                can_view=False,
                can_manage=False,
            )

        student, access = result

        return ExtraClassesAccessDTO(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
            can_view=student.is_active and access.can_view,
            can_manage=(
                student.is_active
                and access.can_view
                and access.can_manage_extra_classes
            ),
        )

    async def _get_managed_student(
        self,
        *,
        actor_user_id: int,
        target_student_id: int,
    ) -> tuple[Optional[Any], ExtraClassesAccessDTO]:
        """
        Возвращает student profile и актуальный доступ.

        Family_id берётся только из student profile, а не из callback,
        FSM или пользовательского ввода.
        """
        access = await self.get_access(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
        )

        if not access.can_view:
            return None, access

        actor = await self.profile_service.get_user_profile_dto(
            actor_user_id,
        )

        if actor.role == "child":
            student = (
                await self.students_service.get_student_by_telegram_user_id(
                    telegram_user_id=actor_user_id,
                )
            )

            return student, access

        result = await self.students_service.get_student_for_adult(
            adult_user_id=actor_user_id,
            student_id=target_student_id,
        )

        if result is None:
            return None, access

        student, _student_access = result

        return student, access

    async def get_student_extra_classes(
        self,
        *,
        actor_user_id: int,
        target_student_id: int,
    ) -> ActionResponseDTO:
        """
        Получает список занятий ученика при наличии view-права.
        """
        access = await self.get_access(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
        )

        if not access.can_view:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        rows = await self.repo.get_extra_classes_for_student(
            student_id=target_student_id,
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

    async def add_extra_class(
        self,
        *,
        actor_user_id: int,
        target_student_id: int,
        day_of_week: int,
        time_start: str,
        time_end: str,
        title: str,
        location: Optional[str],
        reminder_minutes: int,
    ) -> ActionResponseDTO:
        """
        Создаёт занятие выбранному student profile.
        """
        student, access = await self._get_managed_student(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
        )

        if student is None or not access.can_manage:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        validation_error = self._validate_extra_class_data(
            day_of_week=day_of_week,
            time_start=time_start,
            time_end=time_end,
            title=title,
            reminder_minutes=reminder_minutes,
        )

        if validation_error is not None:
            return ActionResponseDTO(
                success=False,
                error_code=validation_error,
            )

        normalized_title = title.strip()
        normalized_location = (
            location.strip()
            if location and location.strip()
            else None
        )

        try:
            extra_id = await self.repo.create_extra_class(
                family_id=student.family_id,
                student_id=student.id,
                day_of_week=day_of_week,
                time_start=time_start,
                time_end=time_end,
                title=normalized_title,
                location=normalized_location,
                reminder_minutes=reminder_minutes,
            )

            return ActionResponseDTO(
                success=True,
                data={"extra_id": extra_id},
            )

        except Exception:
            logger.exception(
                "Extra class creation failed: actor_id=%s, student_id=%s",
                actor_user_id,
                target_student_id,
            )

            return ActionResponseDTO(
                success=False,
                error_code="db_error",
            )

    async def update_extra_class(
        self,
        *,
        actor_user_id: int,
        target_student_id: int,
        extra_id: int,
        **kwargs: Any,
    ) -> ActionResponseDTO:
        """
        Частично обновляет занятие после проверки actor access.

        Перед обновлением считывается текущее занятие, чтобы проверить
        итоговые start/end даже при изменении только одного поля.
        """
        student, access = await self._get_managed_student(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
        )

        if student is None or not access.can_manage:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        current = await self.repo.get_extra_class(
            extra_id=extra_id,
            student_id=target_student_id,
        )

        if current is None:
            return ActionResponseDTO(
                success=False,
                error_code="not_found",
            )

        validation_error = self._validate_extra_class_data(
            day_of_week=kwargs.get(
                "day_of_week",
                current["day_of_week"],
            ),
            time_start=kwargs.get(
                "time_start",
                current["time_start"],
            ),
            time_end=kwargs.get(
                "time_end",
                current["time_end"],
            ),
            title=kwargs.get(
                "title",
                current["title"],
            ),
            reminder_minutes=kwargs.get(
                "reminder_minutes",
                current["reminder_minutes"],
            ),
        )

        if validation_error is not None:
            return ActionResponseDTO(
                success=False,
                error_code=validation_error,
            )

        if "title" in kwargs:
            kwargs["title"] = kwargs["title"].strip()

        if "location" in kwargs:
            location = kwargs["location"]

            kwargs["location"] = (
                location.strip()
                if location and location.strip()
                else None
            )

        updated = await self.repo.update_extra_class(
            extra_id=extra_id,
            student_id=target_student_id,
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
        target_student_id: int,
        extra_id: int,
    ) -> ActionResponseDTO:
        """
        Удаляет занятие только при наличии manage-права.
        """
        _student, access = await self._get_managed_student(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
        )

        if not access.can_manage:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        deleted = await self.repo.delete_extra_class(
            extra_id=extra_id,
            student_id=target_student_id,
        )

        if deleted:
            return ActionResponseDTO(success=True)

        return ActionResponseDTO(
            success=False,
            error_code="not_found",
        )

    def _validate_extra_class_data(
        self,
        *,
        day_of_week: int,
        time_start: str,
        time_end: str,
        title: str,
        reminder_minutes: int,
    ) -> Optional[str]:
        """
        Возвращает error_code или None, если данные валидны.
        """
        if not 1 <= day_of_week <= 7:
            return "invalid_day"

        if not 0 <= reminder_minutes <= 180:
            return "invalid_reminder"

        if not self.time_service.validate_time_format(time_start):
            return "invalid_time"

        if not self.time_service.validate_time_format(time_end):
            return "invalid_time"

        if not self.time_service.validate_time_range(
            time_start,
            time_end,
        ):
            return "invalid_time_range"

        if not title or not title.strip():
            return "empty_title"

        return None
    
    
# ==============================================================
# БИЛДЕР 
# ==============================================================

    # Названия дней недели для ViewModel.
    # НЕ импортируем из UIRenderer — сервисный слой
    # не должен зависеть от UI-слоя.
    _DAYS_RU = {
        1: "Понедельник",
        2: "Вторник",
        3: "Среда",
        4: "Четверг",
        5: "Пятница",
        6: "Суббота",
        7: "Воскресенье",
    }

    @staticmethod
    def build_view_model(
        item: ExtraClassItemDTO,
    ) -> ExtraClassViewModel:
        """
        Строит ViewModel одного доп. занятия.

        Day-of-week int → текст, location fallback.
        """
        return ExtraClassViewModel(
            id=item.id,
            day_of_week=item.day_of_week,
            day_of_week_text=ExtraClassesService._DAYS_RU.get(
                item.day_of_week,
                "Неизвестно",
            ),
            time_start=item.time_start,
            time_end=item.time_end,
            title=item.title,
            location=(
                item.location
                if item.location
                else "Не указано"
            ),
            reminder_minutes=item.reminder_minutes,
        )

    @staticmethod
    def build_view_models(
        items: List[ExtraClassItemDTO],
    ) -> List[ExtraClassViewModel]:
        """
        Строит ViewModel для списка доп. занятий.

        Сортирует по (day_of_week, time_start) —
        как это раньше делал renderer.
        """
        view_models = [
            ExtraClassesService.build_view_model(item)
            for item in items
        ]
        view_models.sort(
            key=lambda vm: (vm.day_of_week, vm.time_start),
        )
        return view_models
