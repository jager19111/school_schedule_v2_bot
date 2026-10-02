from core.mappers.profile_mapper import ProfileMapper


def test_none_row_returns_unregistered_profile_with_defaults() -> None:
    dto = ProfileMapper.to_user_profile_dto(
        None,
        user_id=101,
    )

    assert dto.user_id == 101
    assert dto.role is None
    assert dto.is_fully_registered is False
    assert dto.name is None
    assert dto.family_id is None
    assert dto.class_id is None
    assert dto.group_id is None
    assert dto.teacher_id is None

    assert dto.pre_lesson_offset_minutes == 10
    assert dto.receive_schedule_changes is True
    assert dto.receive_extra_class_reminders is True
    assert dto.can_manage_own_extra_classes is True
    assert dto.changes_window_days == 3
    assert dto.is_notifications_enabled is True
    assert dto.global_extra_reminder == 30


def test_child_is_registered_when_class_is_present() -> None:
    dto = ProfileMapper.to_user_profile_dto(
        {
            "role": "child",
            "name": "Иван",
            "class_id": "016",
            "group_id": "ALL",
        },
        user_id=102,
    )

    assert dto.user_id == 102
    assert dto.role == "child"
    assert dto.is_fully_registered is True
    assert dto.name == "Иван"
    assert dto.class_id == "016"
    assert dto.group_id == "ALL"


def test_child_without_class_is_not_registered() -> None:
    dto = ProfileMapper.to_user_profile_dto(
        {
            "role": "child",
            "group_id": "ALL",
        },
        user_id=103,
    )

    assert dto.role == "child"
    assert dto.is_fully_registered is False


def test_parent_and_observer_require_family_id() -> None:
    parent = ProfileMapper.to_user_profile_dto(
        {
            "role": "parent",
            "family_id": 41,
        },
        user_id=104,
    )
    observer = ProfileMapper.to_user_profile_dto(
        {
            "role": "observer",
            "family_id": 41,
        },
        user_id=105,
    )
    unlinked_parent = ProfileMapper.to_user_profile_dto(
        {
            "role": "parent",
        },
        user_id=106,
    )

    assert parent.is_fully_registered is True
    assert observer.is_fully_registered is True
    assert unlinked_parent.is_fully_registered is False


def test_teacher_requires_teacher_id() -> None:
    teacher = ProfileMapper.to_user_profile_dto(
        {
            "role": "teacher",
            "teacher_id": "T-10",
        },
        user_id=107,
    )
    teacher_without_id = ProfileMapper.to_user_profile_dto(
        {
            "role": "teacher",
        },
        user_id=108,
    )

    assert teacher.is_fully_registered is True
    assert teacher.teacher_id == "T-10"
    assert teacher_without_id.is_fully_registered is False


def test_sqlite_boolean_values_are_mapped_to_bool() -> None:
    dto = ProfileMapper.to_user_profile_dto(
        {
            "role": "child",
            "class_id": "016",
            "receive_schedule_changes": 0,
            "receive_extra_class_reminders": 1,
            "can_manage_own_extra_classes": 0,
            "is_notifications_enabled": 1,
        },
        user_id=109,
    )

    assert dto.receive_schedule_changes is False
    assert dto.receive_extra_class_reminders is True
    assert dto.can_manage_own_extra_classes is False
    assert dto.is_notifications_enabled is True


def test_explicit_none_boolean_preserves_current_service_semantics() -> None:
    dto = ProfileMapper.to_user_profile_dto(
        {
            "receive_schedule_changes": None,
            "receive_extra_class_reminders": None,
            "can_manage_own_extra_classes": None,
            "is_notifications_enabled": None,
        },
        user_id=110,
    )

    assert dto.receive_schedule_changes is False
    assert dto.receive_extra_class_reminders is False
    assert dto.can_manage_own_extra_classes is False
    assert dto.is_notifications_enabled is False


def test_mapper_does_not_mutate_source_row() -> None:
    row = {
        "role": "child",
        "class_id": "016",
        "group_id": "ALL",
        "receive_schedule_changes": 1,
    }
    original = dict(row)

    dto = ProfileMapper.to_user_profile_dto(
        row,
        user_id=111,
    )

    assert row == original
    assert dto.is_fully_registered is True
    assert dto.receive_schedule_changes is True