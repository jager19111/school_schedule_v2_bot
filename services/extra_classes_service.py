# services/extra_classes_service.py
#
# ШАГ 3 плана рефакторинга: полный DTO, без dict и **kwargs: Any.
#
# ИЗМЕНЕНИЯ против предыдущей версии:
# 1. Удалены _row_to_extra_class_dto / _row_to_extra_item_dto —
#    маппинг делегирован ExtraClassMapper (repo уже возвращает DTO).
# 2. Удалён build_view_model(s) + _DAYS_RU — перенесены в маппер.
# 3. update_extra_class: вместо **kwargs: Any — явная сигнатура
#    с сентинелом UNSET (репозиторий принимает тот же объект).
#    current["field"] -> current.field (ExtraClassDTO из репозитория).
# 4. Устранён двойной запрос профиля/ученика: _resolve_access
#    возвращает (student, access) одним проходом. Раньше
#    get_access и _get_managed_student выполняли одни и те же
#    SELECT'ы: 4 SQL на операцию вместо 2.
# 5. add_extra_class больше не возвращает dict в data
#    (хендлер extra_id не читал).
#
# Контракт get_extra_classes_for_student(student_id, day_of_week)
# -> list[ExtraClassItemDTO] сохранён: на него завязаны
# ScheduleService._fetch_extra_items и утренние сводки коллектора.

from __future__ import annotations

import logging
from typing import Optional


from core.models.dto import (
    ActionResponseDTO,
    ExtraClassesAccessDTO,
    ExtraClassDTO,
    ExtraClassListDTO,
    StudentProfileDTO,
)
from core.repository.extra_classes_repository import UNSET
from core.repository.extra_classes_repository import ExtraClassesRepository
from services.profiles_service import ProfileService
from services.students_service import StudentsService
from services.time_service import TimeService

logger = logging.getLogger(__name__)


class ExtraClassesService:
    """
    Сервис управления дополнительными занятиями.

    Владелец каждого занятия — student_profiles.id.

    Доступ:
    - child: только собственный student profile;
    - parent/observer: student profiles, доступные через
      parent_student_settings;
    - управление взрослыми регулируется can_manage_extra_classes;
    - управление ребёнком регулируется can_manage_own_extra_classes.
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

    # ==========================================================
    # Access resolution (одним проходом, без дублей SQL)
    # ==========================================================

    async def _resolve_access(
        self,
        *,
        actor_user_id: int,
        target_student_id: int,
    ) -> tuple[Optional[StudentProfileDTO], ExtraClassesAccessDTO]:
        """
        Возвращает (student profile, access) одним проходом.

        Раньше get_access + _get_managed_student выполняли
        одинаковые SELECT'ы профиля и ученика дважды.
        Student=None означает «профиль недоступен».
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
            access = ExtraClassesAccessDTO(
                actor_user_id=actor_user_id,
                target_student_id=target_student_id,
                can_view=is_own_student,
                can_manage=(
                    is_own_student
                    and actor.can_manage_own_extra_classes
                ),
            )
            return (student if is_own_student else None), access

        if actor.role not in ("parent", "observer"):
            denied = ExtraClassesAccessDTO(
                actor_user_id=actor_user_id,
                target_student_id=target_student_id,
                can_view=False,
                can_manage=False,
            )
            return None, denied

        result = await self.students_service.get_student_for_adult(
            adult_user_id=actor_user_id,
            student_id=target_student_id,
        )

        if result is None:
            denied = ExtraClassesAccessDTO(
                actor_user_id=actor_user_id,
                target_student_id=target_student_id,
                can_view=False,
                can_manage=False,
            )
            return None, denied

        student, student_access = result

        access = ExtraClassesAccessDTO(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
            can_view=student.is_active and student_access.can_view,
            can_manage=(
                student.is_active
                and student_access.can_view
                and student_access.can_manage_extra_classes
            ),
        )
        # can_view=False при неактивном студенте: профиль не выдаём.
        return (student if access.can_view else None), access

    async def get_access(
        self,
        *,
        actor_user_id: int,
        target_student_id: int,
    ) -> ExtraClassesAccessDTO:
        """Права actor_user_id на занятия student profile."""
        _student, access = await self._resolve_access(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
        )
        return access

    async def resolve_student_access(
        self, *, actor_user_id: int, target_student_id: int
    ) -> tuple[Optional[StudentProfileDTO], ExtraClassesAccessDTO]:
        """student + access одним проходом (для хендлеров меню)."""
        return await self._resolve_access(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
        )
    # ==========================================================
    # Чтение
    # ==========================================================

    async def get_extra_classes_for_student(
        self,
        *,
        student_id: int,
        day_of_week: int | None = None,
    ) -> list:
        """
        Занятия ученика (сырые items, без проверки прав).

        Горячий путь: ScheduleService._fetch_extra_items и
        утренние сводки. Права НЕ проверяются — вызывающий слой
        отвечает за access; student_id — владелец из student profile.
        """
        return await self.repo.get_extra_classes_for_student(
            student_id=student_id,
            day_of_week=day_of_week,
        )

    async def get_student_extra_classes(
        self,
        *,
        actor_user_id: int,
        target_student_id: int,
    ) -> ActionResponseDTO:
        """Список занятий ученика при наличии view-права."""
        access = await self.get_access(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
        )

        if not access.can_view:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        items = await self.repo.get_extra_classes_for_student(
            student_id=target_student_id,
        )

        return ActionResponseDTO(
            success=True,
            data=ExtraClassListDTO(items=items),
        )

    async def get_extra_class(
        self,
        *,
        actor_user_id: int,
        target_student_id: int,
        extra_id: int,
    ) -> ActionResponseDTO:
        """Получает одно занятие (для проверки перед редактированием)."""
        _student, access = await self._resolve_access(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
        )

        if not access.can_view:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        item = await self.repo.get_extra_class(
            extra_id=extra_id,
            student_id=target_student_id,
        )

        if item is None:
            return ActionResponseDTO(
                success=False,
                error_code="not_found",
            )

        return ActionResponseDTO(success=True, data=item)
    
    # ==========================================================
    # Мутации (единый guard: _resolve_access -> валидация -> repo)
    # ==========================================================

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
        """Создаёт занятие выбранному student profile."""
        student, access = await self._resolve_access(
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

        try:
            await self.repo.create_extra_class(
                family_id=student.family_id,
                student_id=student.id,
                day_of_week=day_of_week,
                time_start=time_start,
                time_end=time_end,
                title=title.strip(),
                location=self._normalize_location(location),
                reminder_minutes=reminder_minutes,
            )

            return ActionResponseDTO(success=True)

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
        day_of_week: Optional[int] = None,
        time_start: Optional[str] = None,
        time_end: Optional[str] = None,
        title: Optional[str] = None,
        location: Optional[str] | object = UNSET,
        reminder_minutes: Optional[int] = None,
    ) -> ActionResponseDTO:
        """
        Частично обновляет занятие после проверки actor access.

        Перед обновлением считывается текущее ExtraClassDTO, чтобы
        проверить итоговые start/end даже при изменении одного поля.
        Все поля опциональны; location различает None (очистить)
        и UNSET (не трогать).
        """
        _student, access = await self._resolve_access(
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
        )

        if not access.can_manage:
            return ActionResponseDTO(
                success=False,
                error_code="access_denied",
            )

        current: Optional[ExtraClassDTO] = await self.repo.get_extra_class(
            extra_id=extra_id,
            student_id=target_student_id,
        )

        if current is None:
            return ActionResponseDTO(
                success=False,
                error_code="not_found",
            )

        # Итоговые значения полей после merge с текущим состоянием.
        effective_day = (
            day_of_week
            if day_of_week is not None
            else current.day_of_week
        )
        effective_start = (
            time_start
            if time_start is not None
            else current.time_start
        )
        effective_end = (
            time_end
            if time_end is not None
            else current.time_end
        )
        effective_title = (
            title
            if title is not None
            else current.title
        )
        effective_reminder = (
            reminder_minutes
            if reminder_minutes is not None
            else current.reminder_minutes
        )

        validation_error = self._validate_extra_class_data(
            day_of_week=effective_day,
            time_start=effective_start,
            time_end=effective_end,
            title=effective_title,
            reminder_minutes=effective_reminder,
        )

        if validation_error is not None:
            return ActionResponseDTO(
                success=False,
                error_code=validation_error,
            )

        normalized_title = (
            effective_title.strip()
            if title is not None
            else None
        )
        normalized_location = (
            self._normalize_location(location)
            if location is not UNSET
            else UNSET
        )

        updated = await self.repo.update_extra_class(
            extra_id=extra_id,
            student_id=target_student_id,
            day_of_week=day_of_week,
            time_start=time_start,
            time_end=time_end,
            title=normalized_title,
            location=normalized_location,
            reminder_minutes=reminder_minutes,
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
        """Удаляет занятие только при наличии manage-права."""
        _student, access = await self._resolve_access(
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

    # ==========================================================
    # Валидация и нормализация (чистые, без I/O)
    # ==========================================================

    def _validate_extra_class_data(
        self,
        *,
        day_of_week: int,
        time_start: str,
        time_end: str,
        title: str,
        reminder_minutes: int,
    ) -> Optional[str]:
        """Возвращает error_code или None, если данные валидны."""
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

    @staticmethod
    def _normalize_location(
        location: Optional[str] | object,
    ) -> Optional[str]:
        """strip + пустая строка -> None (пустое место не храним)."""
        if isinstance(location, str):
            stripped = location.strip()
            return stripped if stripped else None
        return None
