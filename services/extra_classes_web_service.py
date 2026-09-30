# services/extra_classes_web_service.py
#
# Тонкий web-адаптер для доп. занятий (Phase 5, ТЗ 25/59/60).
#
# Что переиспользуется без изменений:
# - ExtraClassesRepository (create/get/update/delete с проверкой
#   владельца student_id в SQL — верифицировано, коммит 8ec6219);
# - StudentsService.get_student_for_adult (права взрослых:
#   can_manage_extra_classes / is_family_admin);
# - StudentRepository.get_student_by_telegram_user_id (child -> профиль);
# - ProfileService.get_user_profile (users.can_manage_own_extra_classes);
# - TimeService (валидация форматов и диапазона времени).
#
# Существующий service layer не меняется; здесь только композиция
# доступа и валидации для web-слоя. SQL здесь нет.

from __future__ import annotations

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional

from core.models.dto import ExtraClassDTO, ExtraClassItemDTO
from core.repository.extra_classes_repository import ExtraClassesRepository
from core.repository.student_repository import StudentRepository
from services.profiles_service import ProfileService
from services.students_service import StudentsService
from services.time_service import TimeService

logger = logging.getLogger(__name__)

WEEKDAYS_RU = {
    1: "Понедельник", 2: "Вторник", 3: "Среда", 4: "Четверг",
    5: "Пятница", 6: "Суббота", 7: "Воскресенье",
}

class ExtraClassesUnavailableReason(str, Enum):
    """
    Причины, по которым authenticated user не может открыть раздел «Допы».

    Это НЕ security violation: user успешно вошёл в web version,
    но у него нет применимой student target для extra classes.
    """

    NO_CHILDREN = "no_children"
    TEACHER = "teacher"
    CHILD_NO_PROFILE = "child_no_profile"
    UNSUPPORTED_PROFILE = "unsupported_profile"
    
@dataclass(frozen=True, slots=True)
class ExtraClassesAccess:
    """Разрешённый actor -> target-student доступ для доп. занятий."""

    student_id: int
    family_id: Optional[int]
    student_name: str
    can_manage: bool

@dataclass(frozen=True, slots=True)
class ExtraClassOperationResult:
    success: bool
    error_code: str = ""   # forbidden | not_found | conflict | invalid
    detail: str = ""

class ExtraClassesWebService:
    def __init__(
        self,
        extra_classes_repo: ExtraClassesRepository,
        students_service: StudentsService,
        profile_service: ProfileService,
        student_repo: StudentRepository,
        time_service: TimeService,
    ) -> None:
        self.repo = extra_classes_repo
        self.students_service = students_service
        self.profile_service = profile_service
        self.student_repo = student_repo
        self.time_service = time_service

    async def get_unavailable_reason(
        self,
        *,
        actor_user_id: int,
    ) -> ExtraClassesUnavailableReason:
        """
        Возвращает friendly reason только для UI empty state.

        Этот method НЕ выдаёт доступ к student data и НЕ заменяет
        resolve_access(). Любая явная подстановка чужого student_id
        по-прежнему валидируется через resolve_access() и приводит к 403.
        """
        dto = await self.profile_service.get_user_profile_dto(
            actor_user_id,
        )
        role = getattr(dto, "role", None) if dto is not None else None

        if role == "teacher":
            return ExtraClassesUnavailableReason.TEACHER

        if role in ("parent", "observer"):
            return ExtraClassesUnavailableReason.NO_CHILDREN

        if role == "child":
            return ExtraClassesUnavailableReason.CHILD_NO_PROFILE

        return ExtraClassesUnavailableReason.UNSUPPORTED_PROFILE
    
    async def resolve_access(
        self,
        *,
        actor_user_id: int,
        student_id: Optional[int],
    ) -> Optional[ExtraClassesAccess]:
        """
        Право actor'а на доп. занятия student profile.

        - parent/observer: get_student_for_adult (can_manage_extra_classes
          или family admin); студент обязан принадлежать семье actor'а;
        - child: собственный student profile + users.can_manage_own_extra_classes;
        - teacher: нет (доп. занятия — домен учеников).
        """
        dto = await self.profile_service.get_user_profile_dto(actor_user_id)
        if dto is None:
            return None
        role = getattr(dto, "role", None)

        if role in ("parent", "observer"):
            result = await self.students_service.get_student_for_adult(
                adult_user_id=actor_user_id,
                student_id=int(student_id),
            )
            if result is None:
                return None

            student, access = result

            can_view = bool(
                getattr(student, "is_active", True)
                and getattr(access, "can_view", True)
            )

            if not can_view:
                return None

            # Observer is intentionally view-only.
            # Parent can manage only with explicit permission or family-admin role.
            can_manage = (
                role == "parent"
                and bool(
                    getattr(
                        access,
                        "can_manage_extra_classes",
                        False,
                    )
                    or getattr(
                        access,
                        "is_family_admin",
                        False,
                    )
                )
            )

            return ExtraClassesAccess(
                student_id=int(student.id),
                family_id=getattr(student, "family_id", None),
                student_name=str(
                    getattr(student, "name", "") or "Ученик"
                ),
                can_manage=can_manage,
            )

        if role == "child":
            row = await self.student_repo.get_student_by_telegram_user_id(
                telegram_user_id=actor_user_id
            )
            if not row or not row.get("id"):
                return None

            if (
                student_id is not None
                and int(row["id"]) != int(student_id)
            ):
                return None

            user_dto = await self.profile_service.get_user_profile_dto(
                actor_user_id
            )

            can_manage = bool(
                getattr(
                    user_dto,
                    "can_manage_own_extra_classes",
                    False,
                )
            )

            return ExtraClassesAccess(
                student_id=int(row["id"]),
                family_id=row.get("family_id"),
                student_name=str(
                    row.get("name") or "Моё расписание"
                ),
                can_manage=can_manage,
            )

        return None

    # ==========================================================
    # Чтение
    # ==========================================================

    async def list_items(
        self,
        access: ExtraClassesAccess,
    ) -> list[ExtraClassItemDTO]:
        return await self.repo.get_extra_classes_for_student(
            student_id=access.student_id,
        )

    async def get_item(
        self,
        access: ExtraClassesAccess,
        extra_id: int,
    ) -> Optional[ExtraClassDTO]:
        return await self.repo.get_extra_class(
            extra_id=extra_id,
            student_id=access.student_id,
        )

    # ==========================================================
    # Валидация и конфликты (ТЗ Phase 5: conflict warnings)
    # ==========================================================
    def _validate(
        self, *, day_of_week: int, time_start: str, time_end: str, title: str
    ) -> Optional[str]:
        if day_of_week not in WEEKDAYS_RU:
            return "Некорректный день недели."
        title = (title or "").strip()
        if not title or len(title) > 128:
            return "Название: 1-128 символов."

        if not self.time_service.validate_time_format(time_start):
            return "Время начала: формат ЧЧ:ММ."
        if not self.time_service.validate_time_format(time_end):
            return "Время окончания: формат ЧЧ:ММ."

        # ИСПРАВЛЕНО: Жёсткая локальная проверка диапазона (17:00 < 16:00 -> блок)
        try:
            if self._parse(time_start) >= self._parse(time_end):
                return "Время окончания должно быть позже начала."
        except Exception:
            return "Некорректный формат времени."

        return None

    async def find_conflict(
        self,
        access: ExtraClassesAccess,
        *,
        day_of_week: int,
        time_start: str,
        time_end: str,
        exclude_id: Optional[int] = None,
    ) -> Optional[str]:
        """Пересечение по времени с другим занятием того же ученика."""
        s = self._parse(time_start)
        e = self._parse(time_end)
        items = await self.repo.get_extra_classes_for_student(
            student_id=access.student_id, day_of_week=day_of_week
        )
        for item in items:
            if exclude_id is not None and item.id == exclude_id:
                continue

            other_start = self._parse(item.time_start)
            other_end = self._parse(item.time_end)

            if s < other_end and other_start < e:
                return item.title
        return None

    @staticmethod
    def _parse(hhmm: str) -> int:
        parts = str(hhmm).split(":")
        return int(parts[0]) * 60 + int(parts[1])

    # ==========================================================
    # Мутации (SQL и владелец — в репозитории)
    # ==========================================================

    async def create(
        self,
        access: ExtraClassesAccess,
        *,
        day_of_week: int,
        time_start: str,
        time_end: str,
        title: str,
        location: Optional[str],
        reminder_minutes: int = 30,
    ) -> ExtraClassOperationResult:
        # ИСПРАВЛЕНО: Принудительная замена запятых/точек на двоеточия
        time_start = (time_start or "").strip().replace(".", ":").replace(",", ":")
        time_end = (time_end or "").strip().replace(".", ":").replace(",", ":")
        title = (title or "").strip()

        error = self._validate(
            day_of_week=day_of_week, time_start=time_start, time_end=time_end, title=title
        )
        if error:
            return ExtraClassOperationResult(False, "invalid", error)

        conflict = await self.find_conflict(
            access, day_of_week=day_of_week, time_start=time_start, time_end=time_end
        )
        if conflict:
            return ExtraClassOperationResult(
                False, "conflict",
                f"Пересекается по времени с «{conflict}» в этот же день.",
            )

        await self.repo.create_extra_class(
            family_id=access.family_id,
            student_id=access.student_id,
            day_of_week=day_of_week,
            time_start=time_start,
            time_end=time_end,
            title=title,
            location=(location or "").strip() or None,
            reminder_minutes=reminder_minutes,
        )
        return ExtraClassOperationResult(True)

    async def update(
        self,
        access: ExtraClassesAccess,
        extra_id: int,
        *,
        day_of_week: int,
        time_start: str,
        time_end: str,
        title: str,
        location: Optional[str],
        reminder_minutes: int = 30,
    ) -> ExtraClassOperationResult:
        existing = await self.get_item(access, extra_id)
        if existing is None:
            return ExtraClassOperationResult(False, "not_found", "Занятие не найдено.")

        time_start = (time_start or "").strip().replace(".", ":").replace(",", ":")
        time_end = (time_end or "").strip().replace(".", ":").replace(",", ":")
        title = (title or "").strip()
        error = self._validate(
            day_of_week=day_of_week, time_start=time_start, time_end=time_end, title=title
        )
        if error:
            return ExtraClassOperationResult(False, "invalid", error)

        conflict = await self.find_conflict(
            access, day_of_week=day_of_week, time_start=time_start,
            time_end=time_end, exclude_id=extra_id,
        )
        if conflict:
            return ExtraClassOperationResult(
                False, "conflict",
                f"Пересекается по времени с «{conflict}» в этот же день.",
            )

        changed = await self.repo.update_extra_class(
            extra_id=extra_id,
            student_id=access.student_id,
            day_of_week=day_of_week,
            time_start=time_start,
            time_end=time_end,
            title=title,
            location=(location or "").strip() or None,
            reminder_minutes=reminder_minutes,
        )
        if not changed:
            return ExtraClassOperationResult(False, "not_found", "Занятие не найдено.")
        return ExtraClassOperationResult(True)

    async def delete(
        self, access: ExtraClassesAccess, extra_id: int
    ) -> ExtraClassOperationResult:
        deleted = await self.repo.delete_extra_class(
            extra_id=extra_id, student_id=access.student_id
        )
        if not deleted:
            return ExtraClassOperationResult(False, "not_found", "Занятие не найдено.")
        return ExtraClassOperationResult(True)