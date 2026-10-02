from core.mappers.profile_mapper import ProfileMapper
from core.models.dto import (
    ScheduleWatchTargetDTO,
    SchoolDictionariesDTO, StudentTelegramSettingsDTO, 
    WatchTargetViewModel, FamilyMemberDTO, ParentStudentNotificationSettingsDTO
)


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
    
    
def test_family_invite_mapper_maps_full_row() -> None:
    row = {
        "id": 11,
        "token": "secure-token",
        "short_code": "ABC123",
        "family_id": 15,
        "intended_role": "child",
        "expires_at": "2026-10-03 09:00:00",
        "max_uses": 3,
        "uses_count": 1,
        "is_revoked": 0,
        "created_at": "2026-10-02 09:00:00",
        "used_by_user_id": 7001,
        "used_at": "2026-10-02 10:00:00",
    }

    dto = ProfileMapper.to_family_invite_dto(row)

    assert dto.id == 11
    assert dto.token == "secure-token"
    assert dto.short_code == "ABC123"
    assert dto.family_id == 15
    assert dto.intended_role == "child"
    assert dto.expires_at == "2026-10-03 09:00:00"
    assert dto.max_uses == 3
    assert dto.uses_count == 1
    assert dto.is_revoked is False
    assert dto.created_at == "2026-10-02 09:00:00"
    assert dto.used_by_user_id == 7001
    assert dto.used_at == "2026-10-02 10:00:00"


def test_family_invite_mapper_supports_partial_select_row() -> None:
    dto = ProfileMapper.to_family_invite_dto(
        {
            "id": 12,
            "token": "deep-link-token",
            "family_id": 16,
            "intended_role": "parent",
            "expires_at": "2026-10-03 12:00:00",
            "max_uses": 1,
        }
    )

    assert dto.id == 12
    assert dto.short_code is None
    assert dto.uses_count == 0
    assert dto.is_revoked is False
    assert dto.created_at is None
    assert dto.used_by_user_id is None
    assert dto.used_at is None


def test_family_member_mapper_uses_fallback_for_blank_name() -> None:
    dto = ProfileMapper.to_family_member_dto(
        {
            "user_id": 501,
            "name": "   ",
            "role": "child",
            "class_id": "016",
        }
    )

    assert dto.user_id == 501
    assert dto.name == "   "
    assert dto.role == "child"
    assert dto.class_id == "016"
    
    
def test_family_member_mapper_uses_fallback_for_empty_name() -> None:
    dto = ProfileMapper.to_family_member_dto(
        {
            "user_id": 502,
            "name": "",
            "role": "observer",
            "class_id": None,
        }
    )

    assert dto.user_id == 502
    assert dto.name == "Участник 502"
    assert dto.role == "observer"
    assert dto.class_id is None
    
    
    
def test_reset_impact_mapper_uses_family_extra_count_for_admin() -> None:
    dto = ProfileMapper.to_profile_reset_impact_dto(
        {
            "user_id": 601,
            "role": "parent",
            "family_id": 15,
            "is_family_admin": 1,
            "family_members_count": 4,
            "children_count": 2,
            "family_extra_classes_count": 9,
            "own_extra_classes_count": 1,
        }
    )

    assert dto.user_id == 601
    assert dto.role == "parent"
    assert dto.family_id == 15
    assert dto.is_family_admin is True
    assert dto.family_members_count == 4
    assert dto.children_count == 2
    assert dto.extra_classes_count == 9


def test_reset_impact_mapper_uses_own_extra_count_for_non_admin() -> None:
    dto = ProfileMapper.to_profile_reset_impact_dto(
        {
            "user_id": 602,
            "role": "child",
            "family_id": 15,
            "is_family_admin": 0,
            "family_members_count": 4,
            "children_count": 2,
            "family_extra_classes_count": 9,
            "own_extra_classes_count": 3,
        }
    )

    assert dto.is_family_admin is False
    assert dto.extra_classes_count == 3


def test_parent_student_settings_mapper_preserves_fallbacks_and_bools() -> None:
    dto = ProfileMapper.to_parent_student_notification_settings_dto(
        {
            "parent_user_id": 701,
            "student_id": 702,
            "student_name": "",
            "student_class_id": None,
            "student_group_id": None,
            "telegram_user_id": None,
            "receive_morning_summary": 1,
            "receive_pre_lesson_reminders": 0,
            "receive_schedule_changes": 1,
            "receive_extra_class_reminders": 0,
            "can_manage_extra_classes": 1,
        }
    )

    assert dto.parent_user_id == 701
    assert dto.student_id == 702
    assert dto.student_name == "Ученик 702"
    assert dto.student_class_id == "—"
    assert dto.student_group_id == "ALL"
    assert dto.telegram_user_id is None
    assert dto.receive_morning_summary is True
    assert dto.receive_pre_lesson_reminders is False
    assert dto.receive_schedule_changes is True
    assert dto.receive_extra_class_reminders is False
    assert dto.can_manage_extra_classes is True


def test_adult_extra_classes_permission_mapper_maps_list() -> None:
    dtos = (
        ProfileMapper.to_adult_student_extra_classes_permission_dto_list(
            [
                {
                    "adult_user_id": 801,
                    "adult_name": "Анна",
                    "adult_role": "parent",
                    "student_id": 803,
                    "can_manage_extra_classes": 1,
                },
                {
                    "adult_user_id": 802,
                    "adult_name": "Иван",
                    "adult_role": "observer",
                    "student_id": 803,
                    "can_manage_extra_classes": 0,
                },
            ]
        )
    )

    assert len(dtos) == 2

    assert dtos[0].adult_user_id == 801
    assert dtos[0].adult_name == "Анна"
    assert dtos[0].adult_role == "parent"
    assert dtos[0].student_id == 803
    assert dtos[0].can_manage_extra_classes is True

    assert dtos[1].adult_user_id == 802
    assert dtos[1].adult_role == "observer"
    assert dtos[1].can_manage_extra_classes is False


def test_student_telegram_settings_mapper_preserves_fallbacks() -> None:
    dto = ProfileMapper.to_student_telegram_settings_dto(
        {
            "student_id": 901,
            "telegram_user_id": 902,
            "student_name": None,
            "class_id": None,
            "group_id": None,
            "is_notifications_enabled": 1,
            "morning_summary_time": None,
            "pre_lesson_offset_minutes": 15,
            "receive_schedule_changes": 0,
            "receive_extra_class_reminders": 1,
            "can_manage_own_extra_classes": 0,
            "child_notification_settings_locked": 1,
        }
    )

    assert dto.student_id == 901
    assert dto.telegram_user_id == 902
    assert dto.student_name == "Ученик 901"
    assert dto.class_id == "—"
    assert dto.group_id == "ALL"
    assert dto.is_notifications_enabled is True
    assert dto.morning_summary_time is None
    assert dto.pre_lesson_offset_minutes == 15
    assert dto.receive_schedule_changes is False
    assert dto.receive_extra_class_reminders is True
    assert dto.can_manage_own_extra_classes is False
    assert dto.child_notification_settings_locked is True
    
    
    
def test_family_member_view_models_sort_and_format_roles() -> None:
    dictionaries = SchoolDictionariesDTO(
        classes={
            "016": "10А",
        },
        groups={
            "ALL": "Весь класс",
        },
    )

    members = [
        FamilyMemberDTO(
            user_id=1,
            name="Наблюдатель",
            role="observer",
            class_id=None,
        ),
        FamilyMemberDTO(
            user_id=2,
            name="Ребёнок",
            role="child",
            class_id="016",
        ),
        FamilyMemberDTO(
            user_id=3,
            name="Родитель",
            role="parent",
            class_id=None,
        ),
        FamilyMemberDTO(
            user_id=4,
            name="Текущий ребёнок",
            role="child",
            class_id=None,
        ),
    ]

    view_models = ProfileMapper.to_family_member_view_models(
        members,
        current_user_id=4,
        dictionaries=dictionaries,
    )

    assert [view_model.user_id for view_model in view_models] == [
        4,
        3,
        2,
        1,
    ]

    assert view_models[0].is_current_user is True
    assert view_models[0].role_display == "👶 Ребёнок"
    assert view_models[0].class_name == "— класс не выбран —"

    assert view_models[1].role_display == "👨‍👩‍👧 Родитель"
    assert view_models[1].class_name == ""

    assert view_models[2].role_display == "👶 Ребёнок"
    assert view_models[2].class_name == "10А"

    assert view_models[3].role_display == "👁 Наблюдатель"
    
    
def test_student_telegram_settings_view_model_formats_statuses() -> None:
    dictionaries = SchoolDictionariesDTO(
        classes={
            "016": "10А",
        },
        groups={
            "0": "Группа 1",
        },
    )

    dto = StudentTelegramSettingsDTO(
        student_id=501,
        telegram_user_id=502,
        student_name="Иван",
        class_id="016",
        group_id="0",
        is_notifications_enabled=True,
        morning_summary_time=None,
        pre_lesson_offset_minutes=0,
        receive_schedule_changes=False,
        receive_extra_class_reminders=True,
        can_manage_own_extra_classes=False,
        child_notification_settings_locked=True,
    )

    view_model = ProfileMapper.to_student_telegram_settings_view_model(
        dto,
        dictionaries=dictionaries,
    )

    assert view_model.student_id == 501
    assert view_model.student_name == "Иван"
    assert view_model.class_name == "10А"
    assert view_model.group_name == "Группа 1"
    assert view_model.telegram_status == "📱 Telegram подключён"

    assert view_model.morning_summary_time == "ВЫКЛ"
    assert view_model.pre_lesson_offset_minutes == 0
    assert view_model.pre_lesson_text == "ВЫКЛ 🔴"
    assert view_model.lock_text == "ВКЛ 🔒"

    assert view_model.is_notifications_enabled is True
    assert view_model.receive_schedule_changes is False
    assert view_model.receive_extra_class_reminders is True
    assert view_model.can_manage_own_extra_classes is False
    assert view_model.child_notification_settings_locked is True
    
    
def test_parent_student_notification_view_model_formats_virtual_student() -> None:
    dictionaries = SchoolDictionariesDTO(
        classes={
            "016": "10А",
        },
        groups={
            "ALL": "Весь класс",
        },
    )

    dto = ParentStudentNotificationSettingsDTO(
        parent_user_id=601,
        student_id=602,
        student_name="Маша",
        student_class_id="016",
        student_group_id="ALL",
        telegram_user_id=None,
        receive_morning_summary=True,
        receive_pre_lesson_reminders=False,
        receive_schedule_changes=True,
        receive_extra_class_reminders=False,
        can_manage_extra_classes=False,
    )

    view_model = ProfileMapper.to_parent_student_notification_view_model(
        dto,
        dictionaries=dictionaries,
    )

    assert view_model.student_id == 602
    assert view_model.student_name == "Маша"
    assert view_model.class_name == "10А"
    assert view_model.group_name == "Весь класс"

    assert view_model.telegram_connected is False
    assert view_model.telegram_status == (
        "🧒 <b>Telegram пока не подключён</b>"
    )

    assert view_model.receive_morning_summary is True
    assert view_model.receive_pre_lesson_reminders is False
    assert view_model.receive_schedule_changes is True
    assert view_model.receive_extra_class_reminders is False
    assert view_model.can_manage_extra_classes is False
    assert view_model.manage_status_text == "👁 Только просмотр"
    
    
    
def test_family_invite_code_lookup_mapper_exposes_only_required_fields() -> None:
    dto = ProfileMapper.to_family_invite_code_lookup_dto(
        {
            "token": "invite-secret-token",
            "intended_role": "child",
            "family_id": 77,
            "family_code": "LEGACY77",
            "admin_user_id": 991,
            "short_code": "ABC123",
        }
    )

    assert dto.token == "invite-secret-token"
    assert dto.intended_role == "child"

    assert not hasattr(dto, "family_id")
    assert not hasattr(dto, "family_code")
    assert not hasattr(dto, "admin_user_id")
    assert not hasattr(dto, "short_code")