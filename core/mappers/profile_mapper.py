from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.models.dto import UserProfileDTO


class ProfileMapper:
    """
    Преобразует профильную SQL-строку в UserProfileDTO.

    Mapper не выполняет SQL и не имеет side effects.
    Правила полноты регистрации и дефолты DTO централизованы здесь.
    """

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