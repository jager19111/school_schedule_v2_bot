from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from core.models.dto import (
    AdultStudentExtraClassesPermissionDTO,
    FamilyInviteDTO,
    FamilyMemberDTO,
    FamilyMemberViewModel,
    ParentStudentNotificationSettingsDTO,
    ParentStudentNotificationSettingsViewModel,
    ProfileResetImpactDTO,
    SchoolDictionariesDTO,
    StudentTelegramSettingsDTO,
    StudentTelegramSettingsViewModel,
    UserProfileDTO,
    FamilyInviteCodeLookupDTO,
)
class ProfileMapper:
    """
    Преобразует профильную SQL-строку в UserProfileDTO.

    Mapper не выполняет SQL и не имеет side effects.
    Правила полноты регистрации и дефолты DTO централизованы здесь.
    """

    _ROLE_PRIORITY = {
        "parent": 1,
        "child": 2,
        "observer": 3,
    }

    _ROLE_DISPLAY = {
        "parent": "👨‍👩‍👧 Родитель",
        "child": "👶 Ребёнок",
        "observer": "👁 Наблюдатель",
    }

    @staticmethod
    def to_family_member_view_models(
        members: Iterable[FamilyMemberDTO],
        *,
        current_user_id: int,
        dictionaries: SchoolDictionariesDTO,
    ) -> list[FamilyMemberViewModel]:
        """
        Преобразует family DTO list в UI-ready view models.

        Сортировка:
        1. Текущий пользователь.
        2. Parent.
        3. Child.
        4. Observer.
        """
        view_models: list[FamilyMemberViewModel] = []

        for member in members:
            if member.role == "child" and member.class_id:
                class_name = dictionaries.get_readable_class(
                    member.class_id,
                )
            elif member.role == "child":
                class_name = "— класс не выбран —"
            else:
                class_name = ""

            view_models.append(
                FamilyMemberViewModel(
                    user_id=member.user_id,
                    name=member.name,
                    role=member.role,
                    role_display=ProfileMapper._ROLE_DISPLAY.get(
                        member.role,
                        member.role,
                    ),
                    class_name=class_name,
                    is_current_user=(
                        member.user_id == current_user_id
                    ),
                )
            )

        view_models.sort(
            key=lambda view_model: (
                0 if view_model.is_current_user else 1,
                ProfileMapper._ROLE_PRIORITY.get(
                    view_model.role,
                    4,
                ),
            )
        )

        return view_models

    @staticmethod
    def to_student_telegram_settings_view_model(
        dto: StudentTelegramSettingsDTO,
        *,
        dictionaries: SchoolDictionariesDTO,
    ) -> StudentTelegramSettingsViewModel:
        """Преобразует Telegram child settings DTO в UI view model."""
        return StudentTelegramSettingsViewModel(
            student_id=dto.student_id,
            student_name=dto.student_name,
            class_name=dictionaries.get_readable_class(
                dto.class_id,
            ),
            group_name=dictionaries.get_readable_group(
                dto.group_id,
            ),
            telegram_status="📱 Telegram подключён",
            is_notifications_enabled=dto.is_notifications_enabled,
            receive_schedule_changes=dto.receive_schedule_changes,
            receive_extra_class_reminders=(
                dto.receive_extra_class_reminders
            ),
            can_manage_own_extra_classes=(
                dto.can_manage_own_extra_classes
            ),
            child_notification_settings_locked=(
                dto.child_notification_settings_locked
            ),
            morning_summary_time=(
                dto.morning_summary_time
                if dto.morning_summary_time
                else "ВЫКЛ"
            ),
            pre_lesson_offset_minutes=(
                dto.pre_lesson_offset_minutes
            ),
            pre_lesson_text=(
                f"{dto.pre_lesson_offset_minutes} мин 🟢"
                if dto.pre_lesson_offset_minutes > 0
                else "ВЫКЛ 🔴"
            ),
            lock_text=(
                "ВКЛ 🔒"
                if dto.child_notification_settings_locked
                else "ВЫКЛ 🔓"
            ),
        )

    @staticmethod
    def to_parent_student_notification_view_model(
        dto: ParentStudentNotificationSettingsDTO,
        *,
        dictionaries: SchoolDictionariesDTO,
    ) -> ParentStudentNotificationSettingsViewModel:
        """Преобразует adult → student settings DTO в UI view model."""
        telegram_connected = dto.telegram_user_id is not None

        return ParentStudentNotificationSettingsViewModel(
            student_id=dto.student_id,
            student_name=dto.student_name,
            class_name=dictionaries.get_readable_class(
                dto.student_class_id,
            ),
            group_name=dictionaries.get_readable_group(
                dto.student_group_id,
            ),
            telegram_status=(
                "📱 <b>Telegram подключён</b>"
                if telegram_connected
                else "🧒 <b>Telegram пока не подключён</b>"
            ),
            telegram_connected=telegram_connected,
            receive_morning_summary=dto.receive_morning_summary,
            receive_pre_lesson_reminders=(
                dto.receive_pre_lesson_reminders
            ),
            receive_schedule_changes=dto.receive_schedule_changes,
            receive_extra_class_reminders=(
                dto.receive_extra_class_reminders
            ),
            can_manage_extra_classes=(
                dto.can_manage_extra_classes
            ),
            manage_status_text=(
                "✅ Можно управлять"
                if dto.can_manage_extra_classes
                else "👁 Только просмотр"
            ),
        )
        
    @staticmethod
    def to_user_profile_dto(
        row: Mapping[str, Any] | None,
        *,
        user_id: int,
    ) -> UserProfileDTO:
        """
        Преобразует результат ProfileRepository.get_user_profile_for_dto()
        в UserProfileDTO.

        При row=None возвращает DTO незарегистрированного пользователя
        с теми же defaults, что ранее задавались в ProfileService.
        """
        row_data: Mapping[str, Any] = row if row is not None else {}

        role = row_data.get("role")
        is_fully_registered = False

        if role == "child" and row_data.get("class_id"):
            is_fully_registered = True
        elif role in ("parent", "observer") and row_data.get("family_id"):
            is_fully_registered = True
        elif role == "teacher" and row_data.get("teacher_id"):
            is_fully_registered = True

        return UserProfileDTO(
            user_id=user_id,
            role=role,
            is_fully_registered=is_fully_registered,
            name=row_data.get("name"),
            family_id=row_data.get("family_id"),
            class_id=row_data.get("class_id"),
            group_id=row_data.get("group_id"),
            teacher_id=row_data.get("teacher_id"),
            morning_summary_time=row_data.get("morning_summary_time"),
            pre_lesson_offset_minutes=row_data.get(
                "pre_lesson_offset_minutes",
                10,
            ),
            receive_schedule_changes=bool(
                row_data.get("receive_schedule_changes", True)
            ),
            receive_extra_class_reminders=bool(
                row_data.get("receive_extra_class_reminders", True)
            ),
            can_manage_own_extra_classes=bool(
                row_data.get("can_manage_own_extra_classes", True)
            ),
            changes_window_days=row_data.get(
                "changes_window_days",
                3,
            ),
            is_notifications_enabled=bool(
                row_data.get("is_notifications_enabled", True)
            ),
            global_extra_reminder=row_data.get(
                "global_extra_reminder",
                30,
            ),
        )
        
        
    @staticmethod
    def to_family_invite_dto(
        row: Mapping[str, Any],
    ) -> FamilyInviteDTO:
        """
        Преобразует family_invites row в FamilyInviteDTO.

        Метод поддерживает несколько repository SELECT shapes:
        - newly created invite;
        - valid invite by token;
        - active invite list;
        - active invite by id.

        Не все запросы выбирают short_code, created_at, used_by_user_id
        и used_at, поэтому эти поля читаются безопасно через .get().
        """
        return FamilyInviteDTO(
            id=int(row["id"]),
            token=str(row["token"]),
            family_id=int(row["family_id"]),
            intended_role=str(row["intended_role"]),
            expires_at=row["expires_at"],
            max_uses=int(row["max_uses"]),
            uses_count=int(row.get("uses_count", 0)),
            is_revoked=bool(row.get("is_revoked", False)),
            short_code=row.get("short_code"),
            created_at=row.get("created_at"),
            used_by_user_id=row.get("used_by_user_id"),
            used_at=row.get("used_at"),
        )

    @staticmethod
    def to_family_invite_dto_list(
        rows: Iterable[Mapping[str, Any]],
    ) -> list[FamilyInviteDTO]:
        """Преобразует список family invite rows в DTO list."""
        return [
            ProfileMapper.to_family_invite_dto(row)
            for row in rows
        ]

    @staticmethod
    def to_family_invite_code_lookup_dto(
        row: Mapping[str, Any],
    ) -> FamilyInviteCodeLookupDTO:
        """
        Преобразует valid short-code invite row в минимальный DTO
        для registration flow.
        """
        return FamilyInviteCodeLookupDTO(
            token=str(row["token"]),
            intended_role=str(row["intended_role"]),
        )
        
    @staticmethod
    def to_family_member_dto(
        row: Mapping[str, Any],
    ) -> FamilyMemberDTO:
        """
        Преобразует users row из состава семьи в FamilyMemberDTO.

        Пустое имя имеет UI-safe fallback, который ранее находился
        непосредственно в ProfileService.
        """
        user_id = int(row["user_id"])
        name = row.get("name")

        return FamilyMemberDTO(
            user_id=user_id,
            name=name if name else f"Участник {user_id}",
            role=str(row["role"]),
            class_id=row.get("class_id"),
        )

    @staticmethod
    def to_family_member_dto_list(
        rows: Iterable[Mapping[str, Any]],
    ) -> list[FamilyMemberDTO]:
        """Преобразует список users rows в список членов семьи."""
        return [
            ProfileMapper.to_family_member_dto(row)
            for row in rows
        ]
        
        
    @staticmethod
    def to_profile_reset_impact_dto(
        row: Mapping[str, Any],
    ) -> ProfileResetImpactDTO:
        """
        Преобразует row последствий profile reset в DTO.

        Для family admin учитываются все family extra classes.
        Для остальных участников учитываются только собственные
        extra classes, привязанные к Telegram student profile.
        """
        is_family_admin = bool(row["is_family_admin"])

        if is_family_admin:
            extra_classes_count = int(
                row["family_extra_classes_count"]
            )
        else:
            extra_classes_count = int(
                row["own_extra_classes_count"]
            )

        return ProfileResetImpactDTO(
            user_id=int(row["user_id"]),
            role=row.get("role"),
            family_id=row.get("family_id"),
            is_family_admin=is_family_admin,
            family_members_count=int(
                row["family_members_count"]
            ),
            children_count=int(row["children_count"]),
            extra_classes_count=extra_classes_count,
        )

    @staticmethod
    def to_parent_student_notification_settings_dto(
        row: Mapping[str, Any],
    ) -> ParentStudentNotificationSettingsDTO:
        """
        Преобразует adult → student settings row в DTO.

        Fallback values полностью повторяют прежнюю реализацию
        ProfileService.
        """
        student_id = int(row["student_id"])

        return ParentStudentNotificationSettingsDTO(
            parent_user_id=int(row["parent_user_id"]),
            student_id=student_id,
            student_name=(
                row["student_name"]
                or f"Ученик {student_id}"
            ),
            student_class_id=row["student_class_id"] or "—",
            student_group_id=row["student_group_id"] or "ALL",
            telegram_user_id=row.get("telegram_user_id"),
            receive_morning_summary=bool(
                row["receive_morning_summary"]
            ),
            receive_pre_lesson_reminders=bool(
                row["receive_pre_lesson_reminders"]
            ),
            receive_schedule_changes=bool(
                row["receive_schedule_changes"]
            ),
            receive_extra_class_reminders=bool(
                row["receive_extra_class_reminders"]
            ),
            can_manage_extra_classes=bool(
                row["can_manage_extra_classes"]
            ),
        )

    @staticmethod
    def to_adult_student_extra_classes_permission_dto(
        row: Mapping[str, Any],
    ) -> AdultStudentExtraClassesPermissionDTO:
        """Преобразует permission row в DTO."""
        return AdultStudentExtraClassesPermissionDTO(
            adult_user_id=int(row["adult_user_id"]),
            adult_name=row["adult_name"],
            adult_role=row["adult_role"],
            student_id=int(row["student_id"]),
            can_manage_extra_classes=bool(
                row["can_manage_extra_classes"]
            ),
        )

    @staticmethod
    def to_adult_student_extra_classes_permission_dto_list(
        rows: Iterable[Mapping[str, Any]],
    ) -> list[AdultStudentExtraClassesPermissionDTO]:
        """Преобразует список permission rows в DTO list."""
        return [
            ProfileMapper.to_adult_student_extra_classes_permission_dto(
                row
            )
            for row in rows
        ]

    @staticmethod
    def to_student_telegram_settings_dto(
        row: Mapping[str, Any],
    ) -> StudentTelegramSettingsDTO:
        """
        Преобразует Telegram-linked student settings row в DTO.

        Fallback values повторяют существующую service-логику:
        пустое student name, class_id или group_id нормализуются
        только на уровне DTO presentation contract.
        """
        student_id = int(row["student_id"])

        return StudentTelegramSettingsDTO(
            student_id=student_id,
            telegram_user_id=int(row["telegram_user_id"]),
            student_name=(
                row["student_name"]
                or f"Ученик {student_id}"
            ),
            class_id=row["class_id"] or "—",
            group_id=row["group_id"] or "ALL",
            is_notifications_enabled=bool(
                row["is_notifications_enabled"]
            ),
            morning_summary_time=row.get(
                "morning_summary_time"
            ),
            pre_lesson_offset_minutes=int(
                row["pre_lesson_offset_minutes"]
            ),
            receive_schedule_changes=bool(
                row["receive_schedule_changes"]
            ),
            receive_extra_class_reminders=bool(
                row["receive_extra_class_reminders"]
            ),
            can_manage_own_extra_classes=bool(
                row["can_manage_own_extra_classes"]
            ),
            child_notification_settings_locked=bool(
                row.get(
                    "child_notification_settings_locked",
                    False,
                )
            ),
        )