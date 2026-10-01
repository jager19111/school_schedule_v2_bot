from __future__ import annotations


from dataclasses import replace


import pytest


from core.models.dto import (
    ScheduleTargetDTO,
    ScheduleTargetKind,
    ScheduleTargetState,
    ScheduleWatchTargetDTO,
    SchoolDictionariesDTO,
    StudentProfileDTO,
    UserProfileDTO,
)
from services.schedule_targets_service import (
    ScheduleTargetsService,
)


class FakeProfileService:
    def __init__(
        self,
        profiles: dict[int, UserProfileDTO | None],
        *,
        family_admin_user_ids: set[int] | None = None,
    ) -> None:
        self.profiles = profiles
        self.family_admin_user_ids = (
            family_admin_user_ids
            if family_admin_user_ids is not None
            else set()
        )

    async def get_user_profile_dto(
        self,
        user_id: int,
    ) -> UserProfileDTO | None:
        return self.profiles.get(user_id)

    async def is_family_admin(
        self,
        *,
        user_id: int,
        family_id: int,
    ) -> bool:
        return user_id in self.family_admin_user_ids


class FakeStudentsService:
    def __init__(
        self,
        *,
        adult_students: dict[
            int,
            list[StudentProfileDTO],
        ]
        | None = None,
        telegram_students: dict[
            int,
            StudentProfileDTO | None,
        ]
        | None = None,
    ) -> None:
        self.adult_students = (
            adult_students
            if adult_students is not None
            else {}
        )
        self.telegram_students = (
            telegram_students
            if telegram_students is not None
            else {}
        )

    async def get_students_for_adult(
        self,
        *,
        adult_user_id: int,
    ) -> list[StudentProfileDTO]:
        return self.adult_students.get(
            adult_user_id,
            [],
        )

    async def get_student_by_telegram_user_id(
        self,
        *,
        telegram_user_id: int,
    ) -> StudentProfileDTO | None:
        return self.telegram_students.get(
            telegram_user_id,
        )


class FakeWatchTargetsService:
    def __init__(
        self,
        targets_by_owner: dict[
            int,
            list[ScheduleWatchTargetDTO],
        ]
        | None = None,
    ) -> None:
        self.targets_by_owner = (
            targets_by_owner
            if targets_by_owner is not None
            else {}
        )

    async def get_targets(
        self,
        *,
        owner_user_id: int,
        enabled_only: bool = False,
    ) -> list[ScheduleWatchTargetDTO]:
        targets = self.targets_by_owner.get(
            owner_user_id,
            [],
        )

        if not enabled_only:
            return list(targets)

        return [
            target
            for target in targets
            if target.is_enabled
        ]


class FakeScheduleService:
    def __init__(
        self,
        dictionaries: SchoolDictionariesDTO,
        *,
        should_fail: bool = False,
    ) -> None:
        self.dictionaries = dictionaries
        self.should_fail = should_fail

    async def get_school_dictionaries(
        self,
    ) -> SchoolDictionariesDTO:
        if self.should_fail:
            raise RuntimeError(
                "School dictionaries temporarily unavailable."
            )

        return self.dictionaries


def _profile(
    *,
    user_id: int,
    role: str | None,
    family_id: int | None = None,
    class_id: str | None = None,
    group_id: str | None = None,
    teacher_id: str | None = None,
) -> UserProfileDTO:
    return UserProfileDTO(
        user_id=user_id,
        role=role,
        is_fully_registered=role is not None,
        family_id=family_id,
        class_id=class_id,
        group_id=group_id,
        teacher_id=teacher_id,
    )


def _student(
    *,
    student_id: int,
    name: str,
    class_id: str,
    group_id: str = "ALL",
    family_id: int | None = 1,
    telegram_user_id: int | None = None,
) -> StudentProfileDTO:
    return StudentProfileDTO(
        id=student_id,
        family_id=family_id,
        telegram_user_id=telegram_user_id,
        name=name,
        class_id=class_id,
        group_id=group_id,
    )


def _watch_target(
    *,
    target_id: int,
    owner_user_id: int,
    class_id: str,
    group_id: str = "ALL",
    title: str | None = None,
    is_enabled: bool = True,
) -> ScheduleWatchTargetDTO:
    return ScheduleWatchTargetDTO(
        id=target_id,
        owner_user_id=owner_user_id,
        class_id=class_id,
        group_id=group_id,
        title=title,
        is_enabled=is_enabled,
        receive_schedule_changes=True,
    )


@pytest.fixture
def school_dictionaries() -> SchoolDictionariesDTO:
    return SchoolDictionariesDTO(
        classes={
            "001": "1 А",
            "010": "10 А",
            "011": "11 А",
        },
        groups={
            "ENG": "Английский",
            "INF": "Информатика",
        },
    )


def _service(
    *,
    profiles: dict[int, UserProfileDTO | None],
    school_dictionaries: SchoolDictionariesDTO,
    adult_students: dict[int, list[StudentProfileDTO]] | None = None,
    telegram_students: dict[
        int,
        StudentProfileDTO | None,
    ]
    | None = None,
    watch_targets: dict[
        int,
        list[ScheduleWatchTargetDTO],
    ]
    | None = None,
    family_admin_user_ids: set[int] | None = None,
    dictionaries_should_fail: bool = False,
) -> ScheduleTargetsService:
    return ScheduleTargetsService(
        profile_service=FakeProfileService(
            profiles,
            family_admin_user_ids=family_admin_user_ids,
        ),
        students_service=FakeStudentsService(
            adult_students=adult_students,
            telegram_students=telegram_students,
        ),
        watch_targets_service=FakeWatchTargetsService(
            targets_by_owner=watch_targets,
        ),
        schedule_service=FakeScheduleService(
            school_dictionaries,
            should_fail=dictionaries_should_fail,
        ),
    )


@pytest.mark.asyncio
async def test_parent_targets_preserve_student_order(
    school_dictionaries: SchoolDictionariesDTO,
):
    service = _service(
        profiles={
            1001: _profile(
                user_id=1001,
                role="parent",
                family_id=11,
            ),
        },
        school_dictionaries=school_dictionaries,
        adult_students={
            1001: [
                _student(
                    student_id=501,
                    name="Кореш",
                    class_id="010",
                ),
                _student(
                    student_id=502,
                    name="Лиза",
                    class_id="011",
                    group_id="ENG",
                ),
            ],
        },
    )

    targets = await service.get_targets_for_user(
        user_id=1001,
    )

    assert [
        target.selection_key
        for target in targets
    ] == [
        "student:501",
        "student:502",
    ]

    assert [
        target.name
        for target in targets
    ] == [
        "Кореш",
        "Лиза",
    ]

    assert all(
        target.kind == ScheduleTargetKind.STUDENT
        for target in targets
    )


@pytest.mark.asyncio
async def test_child_uses_canonical_student_profile(
    school_dictionaries: SchoolDictionariesDTO,
):
    service = _service(
        profiles={
            1002: _profile(
                user_id=1002,
                role="child",
                class_id="001",
                group_id="ALL",
            ),
        },
        school_dictionaries=school_dictionaries,
        telegram_students={
            1002: _student(
                student_id=601,
                telegram_user_id=1002,
                name="Петя",
                class_id="010",
                group_id="ENG",
            ),
        },
    )

    targets = await service.get_targets_for_user(
        user_id=1002,
    )

    assert len(targets) == 1

    target = targets[0]

    assert target.kind == ScheduleTargetKind.STUDENT
    assert target.selection_key == "student:601"
    assert target.student_id == 601
    assert target.name == "Петя"
    assert target.class_id == "010"
    assert target.group_id == "ENG"


@pytest.mark.asyncio
async def test_child_without_student_profile_uses_legacy_target(
    school_dictionaries: SchoolDictionariesDTO,
):
    service = _service(
        profiles={
            1003: _profile(
                user_id=1003,
                role="child",
                class_id="011",
                group_id="INF",
            ),
        },
        school_dictionaries=school_dictionaries,
        telegram_students={
            1003: None,
        },
    )

    targets = await service.get_targets_for_user(
        user_id=1003,
    )

    assert len(targets) == 1

    target = targets[0]

    assert target.kind == ScheduleTargetKind.STUDENT
    assert target.selection_key == "student:legacy:1003"
    assert target.student_id is None
    assert target.class_id == "011"
    assert target.group_id == "INF"
    assert target.name == "Моё расписание"


@pytest.mark.asyncio
async def test_teacher_gets_teacher_target(
    school_dictionaries: SchoolDictionariesDTO,
):
    service = _service(
        profiles={
            1004: _profile(
                user_id=1004,
                role="teacher",
                teacher_id="T-77",
            ),
        },
        school_dictionaries=school_dictionaries,
    )

    targets = await service.get_targets_for_user(
        user_id=1004,
    )

    assert len(targets) == 1

    target = targets[0]

    assert target.kind == ScheduleTargetKind.TEACHER
    assert target.selection_key == "teacher:T-77"
    assert target.teacher_id == "T-77"
    assert target.student_id is None
    assert target.class_id == ""
    assert target.group_id == ""


@pytest.mark.asyncio
async def test_watch_targets_use_readable_names_and_group_suffix(
    school_dictionaries: SchoolDictionariesDTO,
):
    service = _service(
        profiles={
            1005: _profile(
                user_id=1005,
                role="parent",
                family_id=15,
            ),
        },
        school_dictionaries=school_dictionaries,
        watch_targets={
            1005: [
                _watch_target(
                    target_id=701,
                    owner_user_id=1005,
                    class_id="010",
                    group_id="ALL",
                    title="10 А",
                ),
                _watch_target(
                    target_id=702,
                    owner_user_id=1005,
                    class_id="011",
                    group_id="ENG",
                    title="11 А",
                ),
            ],
        },
    )

    targets = await service.get_watch_targets_for_user(
        user_id=1005,
    )

    assert [
        target.selection_key
        for target in targets
    ] == [
        "watch:701",
        "watch:702",
    ]

    assert [
        target.name
        for target in targets
    ] == [
        "10 А",
        "11 А · Английский",
    ]

    assert all(
        target.kind == ScheduleTargetKind.WATCH
        for target in targets
    )

    assert [
        target.watch_target_id
        for target in targets
    ] == [
        701,
        702,
    ]


@pytest.mark.asyncio
async def test_disabled_watch_target_is_not_available(
    school_dictionaries: SchoolDictionariesDTO,
):
    service = _service(
        profiles={
            1006: _profile(
                user_id=1006,
                role="parent",
                family_id=16,
            ),
        },
        school_dictionaries=school_dictionaries,
        watch_targets={
            1006: [
                _watch_target(
                    target_id=703,
                    owner_user_id=1006,
                    class_id="010",
                    is_enabled=False,
                ),
            ],
        },
    )

    targets = await service.get_watch_targets_for_user(
        user_id=1006,
    )

    assert targets == []


@pytest.mark.asyncio
async def test_parent_without_children_and_with_watch_target_is_ready(
    school_dictionaries: SchoolDictionariesDTO,
):
    service = _service(
        profiles={
            1007: _profile(
                user_id=1007,
                role="parent",
                family_id=17,
            ),
        },
        school_dictionaries=school_dictionaries,
        adult_students={
            1007: [],
        },
        watch_targets={
            1007: [
                _watch_target(
                    target_id=704,
                    owner_user_id=1007,
                    class_id="010",
                    title="10 А",
                ),
            ],
        },
    )

    resolution = await service.resolve_for_web_user(
        user_id=1007,
        requested_selection_key=None,
    )

    assert resolution.state == ScheduleTargetState.READY
    assert resolution.selected_target is not None
    assert resolution.selected_target.kind == (
        ScheduleTargetKind.WATCH
    )
    assert resolution.selected_target.selection_key == "watch:704"


@pytest.mark.asyncio
async def test_stale_selection_key_falls_back_to_first_owned_target(
    school_dictionaries: SchoolDictionariesDTO,
):
    service = _service(
        profiles={
            1008: _profile(
                user_id=1008,
                role="parent",
                family_id=18,
            ),
        },
        school_dictionaries=school_dictionaries,
        adult_students={
            1008: [
                _student(
                    student_id=801,
                    name="Кореш",
                    class_id="001",
                ),
            ],
        },
        watch_targets={
            1008: [
                _watch_target(
                    target_id=705,
                    owner_user_id=1008,
                    class_id="010",
                    title="10 А",
                ),
            ],
        },
    )

    resolution = await service.resolve_for_web_user(
        user_id=1008,
        requested_selection_key="watch:foreign-target",
    )

    assert resolution.state == ScheduleTargetState.READY
    assert resolution.selected_target is not None

    assert resolution.selected_target.selection_key == (
        "student:801"
    )


def test_selection_key_does_not_mix_student_and_watch_ids():
    student_target = ScheduleTargetDTO(
        kind=ScheduleTargetKind.STUDENT,
        selection_key="student:42",
        name="Кореш",
        student_id=42,
        class_id="010",
        group_id="ALL",
    )

    watch_target = ScheduleTargetDTO(
        kind=ScheduleTargetKind.WATCH,
        selection_key="watch:42",
        name="10 А",
        student_id=None,
        class_id="010",
        group_id="ALL",
        watch_target_id=42,
    )

    service = _service(
        profiles={},
        school_dictionaries=SchoolDictionariesDTO(
            classes={},
            groups={},
        ),
    )

    found_student = service.find_target_by_selection_key(
        [student_target, watch_target],
        "student:42",
    )

    found_watch = service.find_target_by_selection_key(
        [student_target, watch_target],
        "watch:42",
    )

    assert found_student == student_target
    assert found_watch == watch_target
    assert found_student != found_watch