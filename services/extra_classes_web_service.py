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
from dataclasses import dataclass
from typing import Optional, Any

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

    def _get_val(self, obj: Any, key: str, default: Any = None) -> Any:
        if hasattr(obj, "model_dump"): obj = obj.model_dump()
        elif hasattr(obj, "dict"): obj = obj.dict()
        if isinstance(obj, dict): return obj.get(key, default)
        return getattr(obj, key, default)

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
            can_manage = bool(
                getattr(access, "can_manage_extra_classes", False)
                or getattr(access, "is_family_admin", False)
            )
            if not can_manage:
                return None  # просмотр без права управления недоступен в web Phase 5
            return ExtraClassesAccess(
                student_id=int(student.id),
                family_id=getattr(student, "family_id", None),
                student_name=str(getattr(student, "name", "") or "Ученик"),
                can_manage=True,
            )

        if role == "child":
            row = await self.student_repo.get_student_by_telegram_user_id(
                telegram_user_id=actor_user_id
            )
            if not row or not row.get("id"):
                return None
            if student_id is not None and int(row["id"]) != int(student_id):
                return None
            # ИСПРАВЛЕНО: Используем get_user_profile_dto
            user_dto = await self.profile_service.get_user_profile_dto(actor_user_id)
            can_manage = bool(getattr(user_dto, "can_manage_own_extra_classes", False))
            if not can_manage:
                return None
            return ExtraClassesAccess(
                student_id=int(row["id"]),
                family_id=row.get("family_id"),
                student_name=str(row.get("name") or "Моё расписание"),
                can_manage=True,
            )

        return None

    # ==========================================================
    # Чтение
    # ==========================================================
    
    async def list_items(self, access: ExtraClassesAccess) -> list:
        return await self.repo.get_extra_classes_for_student(
            student_id=access.student_id
        )

    async def get_item(
        self, access: ExtraClassesAccess, extra_id: int
    ) -> Optional[Any]:
        return await self.repo.get_extra_class(
            extra_id=extra_id, student_id=access.student_id
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
            item_id = self._get_val(item, "id")
            if exclude_id is not None and int(item_id) == int(exclude_id):
                continue
            other_s = self._parse(self._get_val(item, "time_start", "00:00"))
            other_e = self._parse(self._get_val(item, "time_end", "00:00"))
            if s < other_e and other_s < e:
                return str(self._get_val(item, "title", "занятие"))
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