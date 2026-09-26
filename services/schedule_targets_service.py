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
from typing import List, Optional

from core.repository.student_repository import StudentRepository
from services.profiles_service import ProfileService
from services.students_service import StudentsService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScheduleTarget:
    """Допустимая цель просмотра расписания для actor'а."""

    student_id: Optional[int]  # None => legacy child без student_profile
    class_id: str
    group_id: str
    name: str


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

        # teacher — Phase 3 (реальный teacher_id из профиля).
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
