import logging
from typing import Dict, Any, List, Optional

from core.models.dto import UserProfileDTO, ChildInfoDTO
from core.repository.profile_repository import ProfileRepository

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

    async def update_user_role(self, user_id: int, role: str) -> None:
        """
        Обновляет роль пользователя.
        """
        await self.repo.update_user_role(user_id, role)

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
        Возвращает DTO с информацией о пользователе и статусе регистрации.
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

        if role == "child" and row["class_id"]:
            is_registered = True
        elif role in ("parent", "observer") and row["family_id"]:
            is_registered = True

        return UserProfileDTO(
            user_id=user_id,
            role=role,
            is_fully_registered=is_registered,
            class_id=row["class_id"],
            group_id=row["group_id"],
            parent_control_notifications=bool(row["parent_control_notifications"]),
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
        Блокировка изменения настроек уведомлений ребёнком (parent_control_notifications).
        """
        same_family = await self.repo.check_parent_child_same_family(
            parent_user_id=parent_user_id,
            child_user_id=child_user_id,
        )
        if not same_family:
            return False

        await self.repo.set_child_notifications_lock_flag(child_user_id, locked)
        return True

    # ========== СПИСКИ ДЕТЕЙ ==========

    async def get_children_for_parent(self, parent_user_id: int) -> List[ChildInfoDTO]:
        """
        Возвращает список детей родителя в виде DTO.
        """
        rows = await self.repo.get_children_for_parent_rows(parent_user_id)
        return [
            ChildInfoDTO(
                user_id=r["user_id"],
                # TODO: когда добавишь колонку name, заменить на r["name"]
                name=f"Ребёнок {r['user_id']}",
                class_id=r["class_id"] or "—",
            )
            for r in rows
        ]