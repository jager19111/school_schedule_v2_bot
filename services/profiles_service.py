import logging
import aiosqlite
from typing import Dict, Any, List, Optional

from core.repository.profile_repository import ProfileRepository
from core.models.dto import (
    UserProfileDTO,
    ChildInfoDTO,
    FamilyMemberDTO,
    ParentChildNotificationSettingsDTO,
)

logger = logging.getLogger(__name__)


class ProfileService:
    """
    Сервис профилей.

    - Не содержит SQL.
    - Работает через ProfileRepository и оперирует DTO/бизнес-логикой.
    """

    def __init__(self, repo: ProfileRepository):
        self.repo = repo

    # ========== БАЗОВЫЕ ОПЕРАЦИИ ==========
    async def update_user_name(self, user_id: int, name: str) -> None:
        """Обновляет имя пользователя."""
        await self.repo.update_user_name(user_id, name)
        
    async def register_user_initial(self, user_id: int) -> None:
        """
        Создаёт пользователя, если его нет, и обновляет last_active_at.
        """
        await self.repo.register_user_initial(user_id)

    async def update_last_active(self, user_id: int) -> None:
        """
        Обновляет время последней активности.
        """
        await self.repo.update_last_active(user_id)

# Далее переименовать в set_user_role_with_defaults()
    async def update_user_role(self, user_id: int, role: str) -> None:
        """Делегирует обновление роли и настроек репозиторию."""
        await self.repo.update_role_and_defaults(user_id, role)
        
    # ========== ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ==========

    async def get_user_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Возвращает профиль пользователя (dict) и обновляет last_active_at.
        """
        row = await self.repo.get_user_row(user_id)
        if row:
            await self.repo.update_last_active(user_id)
            return row
        return None

    async def get_user_profile_dto(self, user_id: int) -> UserProfileDTO:
        """
        Возвращает DTO с информацией о пользователе. 
        Логика SQL полностью изолирована в ProfileRepository.
        """
        row = await self.repo.get_user_profile_for_dto(user_id)

        if not row or not row.get("role"):
            return UserProfileDTO(
                user_id=user_id,
                role=None,
                is_fully_registered=False,
            )

        role = row["role"]
        is_registered = False

        # Проверка завершенности регистрации
        if role == "child" and row.get("class_id"):
            is_registered = True
        elif role in ("parent", "observer") and row.get("family_id"):
            is_registered = True

        return UserProfileDTO(
            user_id=user_id,
            role=role,
            is_fully_registered=is_registered,
            name=row.get("name"),
            family_id=row.get("family_id"),
            class_id=row.get("class_id"),
            group_id=row.get("group_id"),
            morning_summary_time=row.get("morning_summary_time"),
            pre_lesson_offset_minutes=row.get(
                "pre_lesson_offset_minutes",
                10,
            ),
            changes_window_days=row.get(
                "changes_window_days",
                3,
            ),
            is_notifications_enabled=bool(
                row.get("is_notifications_enabled", True)
            ),
            global_extra_reminder=row.get(
                "global_extra_reminder",
                30,
            ),
        )

    # ========== СЕМЬИ ==========

    async def create_family_and_link(self, admin_user_id: int) -> str:
        """
        Создаёт семью и привязывает создателя как parent.

        Возвращает family_code.
        """
        return await self.repo.create_family_and_link(admin_user_id)

    async def link_child_to_parent(self, user_id: int, family_code: str, role: str = "child") -> bool:
        """
        Привязывает пользователя (child/observer) к семье по коду.
        """
        family = await self.repo.get_family_by_code(family_code)
        if not family:
            return False

        await self.repo.link_user_to_family(user_id=user_id, family_id=family["id"], role=role)
        return True

    # ========== КЛАСС/ГРУППА ==========

    async def set_child_class_and_group(self, user_id: int, class_id: str, group_id: str) -> None:
        """
        Задаёт класс и группу ребёнка.
        """
        await self.repo.set_child_class_and_group(user_id, class_id, group_id)

    # ========== РОДИТЕЛЬСКИЙ КОНТРОЛЬ ==========

    async def set_child_notifications_lock(
        self,
        parent_user_id: int,
        child_user_id: int,
        locked: bool,
    ) -> bool:
        """
        Блокирует или разблокирует изменение ребёнком собственных настроек.

        Взрослый может менять только настройки ребёнка, на которого у него
        существует связь в parent_child_settings.
        """
        has_access = await self.repo.parent_can_access_child(
            parent_user_id=parent_user_id,
            child_user_id=child_user_id,
        )

        if not has_access:
            logger.warning(
                "Parent access denied: parent_id=%s, child_id=%s",
                parent_user_id,
                child_user_id,
            )
            return False

        return await self.repo.set_child_notifications_lock(
            parent_user_id=parent_user_id,
            child_user_id=child_user_id,
            locked=locked,
        )

    # ========== СПИСКИ ДЕТЕЙ ==========

    async def get_children_for_parent(self, parent_user_id: int) -> List[ChildInfoDTO]:
        """
        Возвращает список детей родителя в виде DTO.
        """
        rows = await self.repo.get_children_for_parent_rows(parent_user_id)
        return [
            ChildInfoDTO(
                user_id=r["user_id"],
                name=r["name"] if r["name"] else f"Ученик {r['user_id']}",
                class_id=r["class_id"] or "—",
                group_id=r["group_id"] or "ALL"
            )
            for r in rows
        ]

    async def get_parent_child_notification_settings(
        self,
        parent_user_id: int,
        child_user_id: int,
    ) -> Optional[ParentChildNotificationSettingsDTO]:
        """
        Возвращает настройки уведомлений текущего взрослого
        по выбранному ребёнку.
        """
        row = await self.repo.get_parent_child_notification_settings_row(
            parent_user_id=parent_user_id,
            child_user_id=child_user_id,
        )

        if row is None:
            return None

        child_name = row.get("child_name")
        if not child_name:
            child_name = f"Ученик {child_user_id}"

        return ParentChildNotificationSettingsDTO(
            parent_id=row["parent_id"],
            child_id=row["child_id"],
            child_name=child_name,
            child_class_id=row.get("child_class_id"),
            child_group_id=row.get("child_group_id"),
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
        )

    async def toggle_parent_child_notification_setting(
        self,
        parent_user_id: int,
        child_user_id: int,
        setting_name: str,
    ) -> bool:
        """
        Переключает настройку уведомлений взрослого по конкретному ребёнку.

        Взрослый может изменить только собственную строку
        parent_child_settings и только для ребёнка, к которому он привязан.
        """
        return await self.repo.toggle_parent_child_notification_setting(
            parent_user_id=parent_user_id,
            child_user_id=child_user_id,
            setting_name=setting_name,
        )
                
# для переключения флагов (toggles) и получения family_code по ID, чтобы изолировать SQL от хендлеров.
    async def get_family_code(self, family_id: int) -> str | None:
        return await self.repo.get_family_code_by_id(family_id)

    async def toggle_user_flag(self, user_id: int, flag_name: str) -> None:
        await self.repo.toggle_boolean_flag(user_id, flag_name)
        
  # Сводка      
    async def update_morning_summary_time(self, user_id: int, time_str: str | None) -> None:
        """Обновляет индивидуальное время утренней рассылки."""
        await self.repo.update_morning_summary_time(user_id, time_str)
    # Перерегистрация    
    async def reset_user_profile(self, user_id: int) -> None:
        await self.repo.reset_user(user_id)

    async def update_integer_setting(self, user_id: int, field_name: str, value: int) -> None:
        await self.repo.update_integer_setting(user_id, field_name, value)
    
    # метод получения состава семьи
    async def get_family_members(self, family_id: int) -> list[FamilyMemberDTO]:
        """Возвращает список всех участников семьи."""
        rows = await self.repo.get_family_members_rows(family_id)
        return [
            FamilyMemberDTO(
                user_id=r['user_id'],
                name=r['name'] if r['name'] else f"Участник {r['user_id']}",
                role=r['role'],
                class_id=r['class_id']
            ) for r in rows
        ]
