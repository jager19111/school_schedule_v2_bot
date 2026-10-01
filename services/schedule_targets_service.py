# services/schedule_targets_service.py
#
# Разрешение целей просмотра расписания для web actor.
#
# Важные границы:
#
# - ProfileService возвращает UserProfileDTO.
# - StudentsService возвращает StudentProfileDTO.
# - WatchTargetsService возвращает ScheduleWatchTargetDTO.
# - ScheduleTargetsService не читает raw database rows и не использует
#   getattr() для typed DTO.
#
# Current web routes пока работают через profile targets и legacy
# web_student cookie. Watch targets подготовлены отдельным typed method
# и будут включены в selection flow следующим атомарным этапом.


from __future__ import annotations


import logging


from core.models.dto import (
    ScheduleTargetDTO,
    ScheduleTargetKind,
    ScheduleTargetResolutionDTO,
    ScheduleTargetState,
)
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.students_service import StudentsService
from services.watch_targets_service import WatchTargetsService


logger = logging.getLogger(__name__)


class ScheduleTargetsService:
    """
    Собирает разрешённые schedule targets текущего web user.

    Сервис не зависит от repository:
    - profile data приходит из ProfileService;
    - students data приходит из StudentsService;
    - personal watch targets приходят из WatchTargetsService;
    - NIKA display names приходят из ScheduleService.
    """

    def __init__(
        self,
        profile_service: ProfileService,
        students_service: StudentsService,
        watch_targets_service: WatchTargetsService,
        schedule_service: ScheduleService,
    ) -> None:
        self.profile_service = profile_service
        self.students_service = students_service
        self.watch_targets_service = watch_targets_service
        self.schedule_service = schedule_service

    async def get_targets_for_user(
        self,
        *,
        user_id: int,
    ) -> list[ScheduleTargetDTO]:
        """
        Existing profile targets пользователя.

        На текущем этапе возвращает только:
        - student targets;
        - teacher target.

        Watch targets специально не добавляются сюда до typed web selector:
        current routes и templates ещё используют student_id-based cookie.
        """
        profile = await self.profile_service.get_user_profile_dto(
            user_id,
        )

        # Current ProfileService всегда возвращает UserProfileDTO,
        # но guard сохраняем на случай изменения public contract.
        if profile is None:
            return []

        if profile.role in {"parent", "observer"}:
            students = await self.students_service.get_students_for_adult(
                adult_user_id=user_id,
            )

            return [
                ScheduleTargetDTO(
                    kind=ScheduleTargetKind.STUDENT,
                    selection_key=(ScheduleTargetKind.STUDENT.build_selection_key(student.id,)),
                    name=(
                        student.name.strip()
                        if student.name.strip()
                        else f"Ученик {student.id}"
                    ),
                    student_id=student.id,
                    class_id=student.class_id,
                    group_id=student.group_id or "ALL",
                )
                for student in students
            ]

        if profile.role == "child":
            student = (
                await self.students_service.get_student_by_telegram_user_id(
                    telegram_user_id=user_id,
                )
            )

            if student is not None:
                return [
                    ScheduleTargetDTO(
                        kind=ScheduleTargetKind.STUDENT,
                        selection_key=(ScheduleTargetKind.STUDENT.build_selection_key(student.id,)),
                        name=(
                            student.name.strip()
                            if student.name.strip()
                            else "Моё расписание"
                        ),
                        student_id=student.id,
                        class_id=student.class_id,
                        group_id=student.group_id or "ALL",
                    )
                ]

            # Legacy child без student_profiles row.
            #
            # extra classes здесь недоступны, потому что отсутствует
            # canonical student_id. Existing web flow уже умеет
            # работать с student_id=None.
            if not profile.class_id:
                return []

            return [
                ScheduleTargetDTO(
                    kind=ScheduleTargetKind.STUDENT,
                    selection_key=(ScheduleTargetKind.STUDENT.build_selection_key("legacy",user_id,)),
                    name="Моё расписание",
                    student_id=None,
                    class_id=profile.class_id,
                    group_id=profile.group_id or "ALL",
                )
            ]

        if profile.role == "teacher" and profile.teacher_id:
            teacher_id = profile.teacher_id.strip()

            if teacher_id:
                return [
                    ScheduleTargetDTO(
                        kind=ScheduleTargetKind.TEACHER,
                        selection_key=(ScheduleTargetKind.TEACHER.build_selection_key(teacher_id,)),
                        name="Моё расписание",
                        student_id=None,
                        class_id="",
                        group_id="",
                        teacher_id=teacher_id,
                    )
                ]

        return []

    async def get_watch_targets_for_user(
        self,
        *,
        user_id: int,
    ) -> list[ScheduleTargetDTO]:
        """
        Возвращает только enabled personal watch targets пользователя.

        Watch target:
        - принадлежит owner_user_id;
        - не имеет student_id;
        - не участвует в family permissions;
        - не получает extra classes;
        - использует отдельный typed selection key.
        """
        watch_targets = await self.watch_targets_service.get_targets(
            owner_user_id=user_id,
            enabled_only=True,
        )

        if not watch_targets:
            return []

        try:
            dictionaries = (
                await self.schedule_service.get_school_dictionaries()
            )
        except Exception as exc:
            logger.warning(
                "Не удалось получить school dictionaries для "
                "watch targets пользователя %s: %s",
                user_id,
                exc,
            )
            dictionaries = None

        result: list[ScheduleTargetDTO] = []

        for watch_target in watch_targets:
            class_id = watch_target.class_id.strip()
            group_id = watch_target.group_id.strip() or "ALL"

            if dictionaries is not None:
                class_name = dictionaries.get_readable_class(
                    class_id,
                )
                group_name = dictionaries.get_readable_group(
                    group_id,
                )
            else:
                class_name = class_id
                group_name = (
                    "Весь класс"
                    if group_id == "ALL"
                    else group_id
                )

            explicit_title = (
                watch_target.title.strip()
                if watch_target.title
                and watch_target.title.strip()
                else None
            )

            base_title = explicit_title or class_name

            display_title = (
                base_title
                if group_id == "ALL"
                else f"{base_title} · {group_name}"
            )

            result.append(
                ScheduleTargetDTO(
                    kind=ScheduleTargetKind.WATCH,
                    selection_key=(ScheduleTargetKind.WATCH.build_selection_key(watch_target.id,)),
                    name=display_title,
                    student_id=None,
                    class_id=class_id,
                    group_id=group_id,
                    watch_target_id=watch_target.id,
                )
            )

        return result

    async def get_all_targets_for_user(
        self,
        *,
        user_id: int,
    ) -> list[ScheduleTargetDTO]:
        """
        Все доступные schedule targets пользователя.

        Порядок фиксирован и является частью будущего UI contract:

        1. Student/teacher targets.
        2. Enabled watched classes.
        """
        profile_targets = await self.get_targets_for_user(
            user_id=user_id,
        )
        watch_targets = await self.get_watch_targets_for_user(
            user_id=user_id,
        )

        return [
            *profile_targets,
            *watch_targets,
        ]

    def find_target(
        self,
        targets: list[ScheduleTargetDTO],
        student_id: int | None,
    ) -> ScheduleTargetDTO | None:
        """
        Existing compatibility lookup по student_id.

        Используется current web_student cookie flow до следующего этапа.
        """
        if not targets:
            return None

        if student_id is None:
            return targets[0]

        for target in targets:
            if target.student_id == student_id:
                return target

        return None

    def find_target_by_selection_key(
        self,
        targets: list[ScheduleTargetDTO],
        selection_key: str,
    ) -> ScheduleTargetDTO | None:
        """
        Находит target по typed selection key.

        Не делает fallback по числовым ID:
        student:42 и watch:42 — разные типы и разные security targets.
        """
        normalized_key = selection_key.strip()

        if not normalized_key:
            return None

        for target in targets:
            if target.selection_key == normalized_key:
                return target

        return None

    async def resolve_for_web_user(
        self,
        *,
        user_id: int,
        requested_selection_key: str | None,
    ) -> ScheduleTargetResolutionDTO:
        """
        Разрешает current target для web user по typed selection key.

        Target sources:
        - student profile;
        - teacher profile;
        - enabled personal watch targets.

        Если cookie устарел, target выключен, удалён или принадлежит
        другому пользователю, выбор безопасно падает на первый разрешённый
        target текущего actor.
        """
        profile = await self.profile_service.get_user_profile_dto(
            user_id,
        )

        if profile is None:
            return ScheduleTargetResolutionDTO(
                targets=[],
                selected_target=None,
                state=ScheduleTargetState.OTHER_EMPTY,
                can_manage_family=False,
            )

        targets = await self.get_all_targets_for_user(
            user_id=user_id,
        )

        if targets:
            selected_target = (
                self.find_target_by_selection_key(
                    targets,
                    requested_selection_key,
                )
                if requested_selection_key
                else None
            )

            if selected_target is None:
                selected_target = targets[0]

            return ScheduleTargetResolutionDTO(
                targets=targets,
                selected_target=selected_target,
                state=ScheduleTargetState.READY,
                can_manage_family=False,
            )

        if profile.role == "parent":
            can_manage_family = bool(
                profile.family_id is not None
                and await self.profile_service.is_family_admin(
                    user_id=user_id,
                    family_id=profile.family_id,
                )
            )

            return ScheduleTargetResolutionDTO(
                targets=[],
                selected_target=None,
                state=ScheduleTargetState.PARENT_EMPTY,
                can_manage_family=can_manage_family,
            )

        if profile.role == "observer":
            return ScheduleTargetResolutionDTO(
                targets=[],
                selected_target=None,
                state=ScheduleTargetState.OBSERVER_EMPTY,
                can_manage_family=False,
            )

        return ScheduleTargetResolutionDTO(
            targets=[],
            selected_target=None,
            state=ScheduleTargetState.OTHER_EMPTY,
            can_manage_family=False,
        )