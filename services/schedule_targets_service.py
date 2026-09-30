# services/schedule_targets_service.py
#
# Разрешение schedule-целей actor'а (ТЗ 18-19: actor/target split).
#
# Phase 2.1: для роли child используется НАСТОЯЩИЙ student_profile.id
# через СУЩЕСТВУЮЩИЙ метод StudentRepository.get_student_by_telegram_user_id
# (проверен по baseline 588700f). Существующий service layer не меняется —
# это тонкое web-расширение, использующее публичный метод репозитория.
#
# Frontend НЕ является security boundary: target проверяется здесь
# на каждом запросе, подмена student_id из URL невозможна.

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from core.repository.student_repository import StudentRepository
from services.profiles_service import ProfileService
from services.students_service import StudentsService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScheduleTarget:
    """Допустимая цель просмотра расписания для actor'а."""
    student_id: Optional[int]
    class_id: str
    group_id: str
    name: str
    teacher_id: Optional[str] = None  # <-- ДОБАВЛЕНО ДЛЯ ФАЗЫ 3

class ScheduleTargetState(str, Enum):
    """
    Runtime state schedule target для web actor.

    Не является DB role и не меняет семейные permissions.
    """

    READY = "ready"
    PARENT_EMPTY = "parent_empty"
    OBSERVER_EMPTY = "observer_empty"
    OTHER_EMPTY = "other_empty"


@dataclass(frozen=True, slots=True)
class ScheduleTargetResolution:
    """
    Результат target resolution для schedule UI.

    target=None может быть normal PWA state:
    parent/observer допущен к web и состоит в семье, но student profiles
    пока отсутствуют.
    """

    targets: List[ScheduleTarget]
    target: Optional[ScheduleTarget]
    state: ScheduleTargetState
    can_manage_family: bool
    
class ScheduleTargetsService:
    def __init__(
        self,
        profile_service: ProfileService,
        students_service: StudentsService,
        student_repo: StudentRepository,
    ) -> None:
        self.profile_service = profile_service
        self.students_service = students_service
        self.student_repo = student_repo

    async def get_targets_for_user(self, *, user_id: int) -> List[ScheduleTarget]:
        dto = await self.profile_service.get_user_profile_dto(user_id)
        if dto is None:
            return []

        role = getattr(dto, "role", None)

        if role in ("parent", "observer"):
            students = await self.students_service.get_students_for_adult(
                adult_user_id=user_id
            )
            return [
                ScheduleTarget(
                    student_id=int(s.id),
                    class_id=str(s.class_id),
                    group_id=str(s.group_id or "ALL"),
                    name=str(s.name or f"Ученик {s.id}"),
                )
                for s in (students or [])
            ]

        if role == "child":
            # Настоящий student profile ребёнка: доп. занятия (extra_classes
            # по student_id) показываются так же, как у parent.
            row = await self.student_repo.get_student_by_telegram_user_id(
                telegram_user_id=user_id
            )
            if row and row.get("id"):
                return [
                    ScheduleTarget(
                        student_id=int(row["id"]),
                        class_id=str(row.get("class_id") or ""),
                        group_id=str(row.get("group_id") or "ALL"),
                        name=str(row.get("name") or "Моё расписание"),
                    )
                ]

            # Legacy-fallback: child без student_profile — только класс/группа
            # из users (доп. занятия недоступны, ровно как до Phase 2.1).
            class_id = getattr(dto, "class_id", None)
            if not class_id:
                return []
            return [
                ScheduleTarget(
                    student_id=None,
                    class_id=str(class_id),
                    group_id=str(getattr(dto, "group_id", None) or "ALL"),
                    name="Моё расписание",
                )
            ]

        # ВНЕДРЕНИЕ ФАЗЫ 3: УЧИТЕЛЬ
        if role == "teacher":
            teacher_id = getattr(dto, "teacher_id", None)
            if teacher_id:
                return [
                    ScheduleTarget(
                        student_id=None,
                        class_id="",
                        group_id="",
                        name="Моё расписание",
                        teacher_id=str(teacher_id)
                    )
                ]

        return []

    def find_target(
        self,
        targets: List[ScheduleTarget],
        student_id: Optional[int],
    ) -> Optional[ScheduleTarget]:
        """
        Безопасный выбор target по student_id из URL/cookie.

        None для единственного/implicit target; иначе — только
        принадлежащий actor'у (иначе None -> route вернёт 403).
        """
        if not targets:
            return None
        if student_id is None:
            return targets[0]
        for target in targets:
            if target.student_id == student_id:
                return target
        return None
    
    async def resolve_for_web_user(
        self,
        *,
        user_id: int,
        requested_student_id: Optional[int],
    ) -> ScheduleTargetResolution:
        """
        Разрешает current schedule target либо возвращает friendly no-target
        state для parent/observer без student profiles.

        Security boundary остаётся прежней:
        - require_family_allowed() уже проверил family allowlist;
        - explicit target selection валидируется через find_target();
        - target другой семьи сюда не попадёт.
        """
        dto = await self.profile_service.get_user_profile_dto(
            user_id,
        )

        if dto is None:
            return ScheduleTargetResolution(
                targets=[],
                target=None,
                state=ScheduleTargetState.OTHER_EMPTY,
                can_manage_family=False,
            )

        role = getattr(dto, "role", None)

        targets = await self.get_targets_for_user(
            user_id=user_id,
        )

        if targets:
            target = self.find_target(
                targets,
                requested_student_id,
            )

            if target is None:
                target = targets[0]

            return ScheduleTargetResolution(
                targets=targets,
                target=target,
                state=ScheduleTargetState.READY,
                can_manage_family=False,
            )

        family_id = getattr(dto, "family_id", None)

        if role == "parent":
            can_manage_family = bool(
                family_id
                and await self.profile_service.is_family_admin(
                    user_id=user_id,
                    family_id=int(family_id),
                )
            )

            return ScheduleTargetResolution(
                targets=[],
                target=None,
                state=ScheduleTargetState.PARENT_EMPTY,
                can_manage_family=can_manage_family,
            )

        if role == "observer":
            return ScheduleTargetResolution(
                targets=[],
                target=None,
                state=ScheduleTargetState.OBSERVER_EMPTY,
                can_manage_family=False,
            )

        return ScheduleTargetResolution(
            targets=[],
            target=None,
            state=ScheduleTargetState.OTHER_EMPTY,
            can_manage_family=False,
        )