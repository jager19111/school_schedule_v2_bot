import logging
import aiosqlite
from typing import Dict, Any, List, Optional
import time

from core.repository.profile_repository import ProfileRepository
from core.models.dto import (
    UserProfileDTO,
    FamilyMemberDTO,ParentStudentNotificationSettingsDTO, AdultStudentExtraClassesPermissionDTO,
    ProfileResetImpactDTO, FamilyInviteDTO,StudentTelegramSettingsDTO, FamilyMemberViewModel,
    SchoolDictionariesDTO, StudentTelegramSettingsViewModel, ParentStudentNotificationSettingsViewModel,
    StudentTelegramSettingsDTO, ParentStudentNotificationSettingsDTO,
)

logger = logging.getLogger(__name__)


class ProfileService:
    """
    Сервис профилей.

    - Не содержит SQL.
    - Работает через ProfileRepository и оперирует DTO/бизнес-логикой.
    """
    # Запись last_active_at не чаще раза в 5 минут на пользователя.
    # Гранулярность 5 минут несущественна для 60-дневной деактивации,
    # но убирает write-усиление: раньше UPDATE выполнялся при
    # КАЖДОМ вызове get_user_profile_dto (некоторые хендлеры
    # дергают его 2-3 раза за экран).
    _LAST_ACTIVE_WRITE_INTERVAL_SEC = 300.0

    def __init__(self, repo: ProfileRepository):
        self.repo = repo
        self._last_active_written_at: dict[int, float] = {}

    async def _touch_last_active(self, user_id: int) -> None:
        """
        Троттлит запись last_active_at: не чаще раза в 5 минут.

        Заодно это троттлит и авто-разблокировку
        notifications_blocked (update_last_active сбрасывает флаг) —
        5 минут задержки разблокировки после активности
        практически незаметны.
        """
        now_mono = time.monotonic()
        if (
            now_mono - self._last_active_written_at.get(user_id, 0.0)
            < self._LAST_ACTIVE_WRITE_INTERVAL_SEC
        ):
            return
        self._last_active_written_at[user_id] = now_mono
        # Микроочистка: не даём словарю расти неограниченно.
        if len(self._last_active_written_at) > 2000:
            cutoff = now_mono - self._LAST_ACTIVE_WRITE_INTERVAL_SEC
            self._last_active_written_at = {
                uid: ts
                for uid, ts in self._last_active_written_at.items()
                if ts > cutoff
            }
        logging.getLogger(__name__).info(">>> ФИЗИЧЕСКАЯ ЗАПИСЬ АКТИВНОСТИ В БД ДЛЯ USER_ID: %s", user_id) # <-- Добавь это
        await self.repo.update_last_active(user_id)
        
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

    async def get_user_profile_dto(self, user_id: int) -> UserProfileDTO:
            """
            Возвращает DTO с информацией о пользователе. 
            Логика SQL полностью изолирована в ProfileRepository.
            """
            row = await self.repo.get_user_profile_for_dto(user_id)
            
            # Троттлинг активности обновляем только если профиль уже физически есть в БД
            if row:
                await self._touch_last_active(user_id)

            # Безопасный словарь. Если профиля нет, подставит {} и .get() сработает штатно.
            row_data = dict(row) if row else {}

            role = row_data.get("role")
            is_registered = False

            # Проверка завершенности регистрации
            if role:
                if role == "child" and row_data.get("class_id"):
                    is_registered = True
                elif role in ("parent", "observer") and row_data.get("family_id"):
                    is_registered = True
                elif role == "teacher" and row_data.get("teacher_id"):
                    is_registered = True

            return UserProfileDTO(
                user_id=user_id,
                role=role,
                is_fully_registered=is_registered,
                # ВАЖНО: Везде ниже используем row_data, а не row!
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

    async def set_teacher_profile(
        self,
        *,
        user_id: int,
        teacher_id: str,
    ) -> bool:
        """
        Привязывает Telegram user к NIKA teacher ID.
        """
        if not teacher_id or not teacher_id.strip():
            return False

        return await self.repo.set_teacher_profile(
            user_id=user_id,
            teacher_id=teacher_id,
        )
    
    # ========== СЕМЬИ ==========
    async def is_family_admin(
        self,
        user_id: int,
        family_id: int,
    ) -> bool:
        """
        Проверяет, является ли Telegram-пользователь администратором
        конкретной семьи.
        """
        return await self.repo.is_family_admin(
            user_id=user_id,
            family_id=family_id,
        )
        
    async def create_family_and_link(self, admin_user_id: int) -> str:
        """
        Создаёт семью и привязывает создателя как parent.

        Возвращает family_code.
        """
        return await self.repo.create_family_and_link(admin_user_id)

    async def create_family_invite(
        self,
        *,
        created_by_user_id: int,
        family_id: int,
        intended_role: str,
        expires_in_hours: int = 24,
    ) -> Optional[FamilyInviteDTO]:
        """
        Создаёт role-specific invite.

        Вернёт None, если инициатор не является family admin.
        """
        row = await self.repo.create_family_invite(
            family_id=family_id,
            created_by_user_id=created_by_user_id,
            intended_role=intended_role,
            expires_in_hours=expires_in_hours,
            max_uses=1,
        )

        if row is None:
            return None

        return FamilyInviteDTO(
            id=row["id"],  # <-- Добавлено недостающее поле
            token=row["token"],
            family_id=row["family_id"],
            intended_role=row["intended_role"],
            expires_at=row["expires_at"],
            max_uses=row["max_uses"],
        )
        
    async def get_valid_family_invite(
        self,
        token: str,
    ) -> Optional[FamilyInviteDTO]:
        """
        Возвращает активное invite для deep-link onboarding.
        """
        row = await self.repo.get_valid_family_invite(
            token=token,
        )

        if row is None:
            return None

        return FamilyInviteDTO(
            id=row["id"],
            token=row["token"],
            family_id=row["family_id"],
            intended_role=row["intended_role"],
            expires_at=row["expires_at"],
            max_uses=row["max_uses"],
            uses_count=row["uses_count"],
            is_revoked=bool(row["is_revoked"]),
        )

    async def consume_family_invite(
        self,
        *,
        token: str,
        user_id: int,
        name: str,
        class_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Завершает регистрацию через invite.

        Возвращает роль пользователя при успехе:
            child / parent / observer

        Возвращает None, если invite стало невалидным к моменту consume.
        """
        result = await self.repo.consume_family_invite(
            token=token,
            user_id=user_id,
            name=name,
            class_id=class_id,
            group_id=group_id,
        )

        if result is None:
            return None

        return result["intended_role"]
    
    # Helper конвертации DTO
    @staticmethod
    def _family_invite_dto_from_row(
        row: Dict[str, Any],
    ) -> FamilyInviteDTO:
        return FamilyInviteDTO(
            id=row["id"],
            token=row["token"],
            family_id=row["family_id"],
            intended_role=row["intended_role"],
            expires_at=row["expires_at"],
            max_uses=row["max_uses"],
            uses_count=row["uses_count"],
            is_revoked=bool(row["is_revoked"]),
            created_at=row.get("created_at"),
            used_by_user_id=row.get("used_by_user_id"),
            used_at=row.get("used_at"),
        )

    async def get_active_family_invites(
        self,
        *,
        admin_user_id: int,
        family_id: int,
    ) -> Optional[List[FamilyInviteDTO]]:
        """
        Возвращает активные invites, если пользователь является family admin.

        None означает отсутствие admin-права.
        Пустой список означает, что active invites отсутствуют.
        """
        is_admin = await self.repo.is_family_admin(
            user_id=admin_user_id,
            family_id=family_id,
        )

        if not is_admin:
            return None

        rows = await self.repo.get_active_family_invites(
            family_id=family_id,
            admin_user_id=admin_user_id,
        )

        return [
            self._family_invite_dto_from_row(row)
            for row in rows
        ]

    async def get_active_family_invite_by_id(
        self,
        *,
        invite_id: int,
        family_id: int,
        admin_user_id: int,
    ) -> Optional[FamilyInviteDTO]:
        """
        Возвращает active invite для admin family.
        """
        row = await self.repo.get_active_family_invite_by_id(
            invite_id=invite_id,
            family_id=family_id,
            admin_user_id=admin_user_id,
        )

        if row is None:
            return None

        return self._family_invite_dto_from_row(row)

    async def revoke_family_invite(
        self,
        *,
        invite_id: int,
        family_id: int,
        admin_user_id: int,
    ) -> bool:
        """
        Отзывает active invite от имени family admin.
        """
        return await self.repo.revoke_family_invite(
            invite_id=invite_id,
            family_id=family_id,
            admin_user_id=admin_user_id,
        )
                                
# Переименовать позже в join_family_by_code()        
    async def link_child_to_parent(self, user_id: int, family_code: str, role: str = "child") -> bool:
        """
        LEGACY_FALLBACK.

        Ручное присоединение пользователя к семье по family_code.
        Оставлено для обратной совместимости и аварийного сценария.
        Основной путь подключения: role-specific deep-link invite.

        В будущем переименовать в join_family_by_code().
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


    # ========== СПИСКИ ДЕТЕЙ ==========


    async def can_user_change_own_notification_settings(
        self,
        user_id: int,
    ) -> bool:
        """
        Parent/observer всегда меняет собственные настройки.

        Telegram child не может менять personal settings только если
        family admin поставил lock в parent_student_settings.
        """
        profile = await self.repo.get_user_row(user_id)

        if profile is None:
            return False

        if profile["role"] != "child":
            return True

        return not await (
            self.repo.is_telegram_child_notification_settings_locked(
                telegram_user_id=user_id,
            )
        )

    async def toggle_own_notifications_enabled(
        self,
        user_id: int,
    ) -> bool:
        """
        Переключает общий флаг уведомлений самого пользователя.

        Ребёнок может сделать это только при отсутствии административной
        блокировки его notification settings.
        """
        allowed = await self.can_user_change_own_notification_settings(
            user_id=user_id,
        )

        if not allowed:
            return False

        await self.repo.toggle_boolean_flag(
            user_id=user_id,
            field_name="is_notifications_enabled",
        )

        return True

    async def update_own_morning_summary_time(
        self,
        user_id: int,
        time_str: str | None,
    ) -> bool:
        """
        Обновляет личное время утренней сводки пользователя.

        time_str=None отключает сводку.
        """
        allowed = await self.can_user_change_own_notification_settings(
            user_id=user_id,
        )

        if not allowed:
            return False

        await self.repo.update_morning_summary_time(
            user_id=user_id,
            time_str=time_str,
        )

        return True

    async def toggle_own_boolean_notification_setting(
        self,
        user_id: int,
        field_name: str,
    ) -> bool:
        """
        Переключает личный boolean-параметр уведомлений пользователя.

        Для ребёнка проверяется administrative lock.
        """
        allowed = await self.can_user_change_own_notification_settings(
            user_id=user_id,
        )

        if not allowed:
            return False

        allowed_fields = {
            "is_notifications_enabled",
            "receive_schedule_changes",
            "receive_extra_class_reminders",
        }

        if field_name not in allowed_fields:
            raise ValueError(
                f"Unsupported own notification setting: {field_name}"
            )

        await self.repo.toggle_boolean_flag(
            user_id=user_id,
            field_name=field_name,
        )

        return True
    
    async def update_own_integer_notification_setting(
        self,
        user_id: int,
        field_name: str,
        value: int,
    ) -> bool:
        """
        Обновляет личный числовой параметр уведомлений.

        Допустимы только поля личного профиля пользователя.
        """
        allowed = await self.can_user_change_own_notification_settings(
            user_id=user_id,
        )

        if not allowed:
            return False

        allowed_fields = {
            "pre_lesson_offset_minutes",
            "changes_window_days",
            "global_extra_reminder",
        }

        if field_name not in allowed_fields:
            raise ValueError(
                f"Unsupported notification field: {field_name}"
            )

        await self.repo.update_integer_setting(
            user_id=user_id,
            field_name=field_name,
            value=value,
        )

        return True
                                
# для переключения флагов (toggles) и получения family_code по ID, чтобы изолировать SQL от хендлеров.
    async def get_family_code(self, family_id: int) -> str | None:
        return await self.repo.get_family_code_by_id(family_id)

    async def get_profile_reset_impact(
        self,
        user_id: int,
    ) -> Optional[ProfileResetImpactDTO]:
        """
        Возвращает последствия reset без выполнения destructive action.

        Используется handler-ом для предупреждения пользователя
        до нажатия «Да, перерегистрироваться».
        """
        row = await self.repo.get_profile_reset_impact(
            user_id=user_id,
        )

        if row is None:
            return None

        is_family_admin = bool(
            row["is_family_admin"]
        )

        if is_family_admin:
            extra_classes_count = int(
                row["family_extra_classes_count"]
            )
        else:
            extra_classes_count = int(
                row["own_extra_classes_count"]
            )


        return ProfileResetImpactDTO(
            user_id=row["user_id"],
            role=row.get("role"),
            family_id=row.get("family_id"),
            is_family_admin=is_family_admin,
            family_members_count=int(
                row["family_members_count"]
            ),
            children_count=int(
                row["children_count"]
            ),
            extra_classes_count=extra_classes_count,
        )
          
    async def reset_user_profile(
        self,
        user_id: int,
    ) -> bool:
        """
        Выполняет подтверждённую перерегистрацию пользователя.

        Family admin расформировывает всю семью.
        Обычный участник выходит только сам.
        """
        impact = await self.get_profile_reset_impact(
            user_id=user_id,
        )

        if impact is None:
            return False

        if impact.is_family_admin:
            return await self.repo.disband_family_by_admin(
                admin_user_id=user_id,
            )

        return await self.repo.reset_non_admin_user(
            user_id=user_id,
        )

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

    # ========== НАСТРОЙКИ ВЗРОСЛЫЙ → STUDENT PROFILE ==========

    async def get_parent_student_notification_settings(
        self,
        *,
        parent_user_id: int,
        student_id: int,
    ) -> Optional[ParentStudentNotificationSettingsDTO]:
        """
        Возвращает настройки уведомлений взрослого
        по конкретному student profile.
        """
        row = await self.repo.get_parent_student_notification_settings_row(
            parent_user_id=parent_user_id,
            student_id=student_id,
        )

        if row is None:
            return None

        return ParentStudentNotificationSettingsDTO(
            parent_user_id=row["parent_user_id"],
            student_id=row["student_id"],

            student_name=row["student_name"] or (
                f"Ученик {student_id}"
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

    async def toggle_parent_student_notification_setting(
        self,
        *,
        parent_user_id: int,
        student_id: int,
        setting_name: str,
    ) -> bool:
        """
        Переключает личную подписку взрослого на student profile.
        """
        return await self.repo.toggle_parent_student_notification_setting(
            parent_user_id=parent_user_id,
            student_id=student_id,
            setting_name=setting_name,
        )           

    async def is_family_admin_for_student(
        self,
        *,
        admin_user_id: int,
        student_id: int,
    ) -> bool:
        """
        Проверяет полномочия family admin над student profile.
        """
        return await self.repo.is_family_admin_for_student(
            admin_user_id=admin_user_id,
            student_id=student_id,
        )

    async def get_adult_student_extra_classes_permissions(
        self,
        *,
        admin_user_id: int,
        student_id: int,
    ) -> Optional[List[AdultStudentExtraClassesPermissionDTO]]:
        """
        Возвращает права non-admin взрослых на кружки ученика.

        None:
        пользователь не является family admin.

        []:
        в семье нет других взрослых.
        """
        rows = await self.repo.get_adult_student_extra_classes_permissions(
            admin_user_id=admin_user_id,
            student_id=student_id,
        )

        if rows is None:
            return None

        return [
            AdultStudentExtraClassesPermissionDTO(
                adult_user_id=row["adult_user_id"],
                adult_name=row["adult_name"],
                adult_role=row["adult_role"],
                student_id=row["student_id"],
                can_manage_extra_classes=bool(
                    row["can_manage_extra_classes"]
                ),
            )
            for row in rows
        ]

    async def set_adult_student_extra_classes_permission(
        self,
        *,
        admin_user_id: int,
        adult_user_id: int,
        student_id: int,
        can_manage: bool,
    ) -> bool:
        """
        Family admin изменяет право другого adult
        на управление кружками student profile.
        """
        return await self.repo.set_adult_student_extra_classes_permission(
            admin_user_id=admin_user_id,
            adult_user_id=adult_user_id,
            student_id=student_id,
            can_manage=can_manage,
        )
        
    #---------------------------------------------
    # Управление настройками уведомлений у ребенка
    #----------------------------------------------         
            
    async def get_student_telegram_settings_for_admin(
        self,
        *,
        admin_user_id: int,
        student_id: int,
    ) -> Optional[StudentTelegramSettingsDTO]:
        """
        Возвращает Telegram-настройки student profile
        только family admin.
        """
        row = await self.repo.get_student_telegram_settings_for_admin(
            admin_user_id=admin_user_id,
            student_id=student_id,
        )

        if row is None:
            return None

        return StudentTelegramSettingsDTO(
            student_id=row["student_id"],
            telegram_user_id=row["telegram_user_id"],

            student_name=row["student_name"] or (
                f"Ученик {student_id}"
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
        
    async def toggle_student_telegram_boolean_setting(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        field_name: str,
    ) -> bool:
        """
        Family admin переключает personal boolean setting
        Telegram-linked student.
        """
        return await self.repo.toggle_student_telegram_boolean_setting(
            admin_user_id=admin_user_id,
            student_id=student_id,
            field_name=field_name,
        )
        
    async def update_student_telegram_integer_setting(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        field_name: str,
        value: int,
    ) -> bool:
        """
        Family admin меняет personal integer setting
        Telegram-linked student.
        """
        return await self.repo.update_student_telegram_integer_setting(
            admin_user_id=admin_user_id,
            student_id=student_id,
            field_name=field_name,
            value=value,
        )
        
    async def update_student_telegram_morning_summary_time(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        time_str: str | None,
    ) -> bool:
        """
        Family admin задаёт personal morning summary time
        Telegram-linked student.
        """
        return await self.repo.update_student_telegram_morning_summary_time(
            admin_user_id=admin_user_id,
            student_id=student_id,
            time_str=time_str,
        )
        
    async def set_student_notification_settings_locked(
        self,
        *,
        admin_user_id: int,
        student_id: int,
        locked: bool,
    ) -> bool:
        """
        Family admin включает или выключает lock
        personal Telegram settings student profile.
        """
        return await self.repo.set_student_notification_settings_locked(
            admin_user_id=admin_user_id,
            student_id=student_id,
            locked=locked,
        )
        
    # ==========================================================
    # ЭТАП 5: ViewModel builders
    # ==========================================================

    # Приоритет ролей для сортировки списка семьи.
    _ROLE_PRIORITY = {
        "parent": 1,
        "child": 2,
        "observer": 3,
    }

    # Отображение ролей для списка семьи.
    _ROLE_DISPLAY = {
        "parent": "👨‍👩‍👧 Родитель",
        "child": "👶 Ребёнок",
        "observer": "👁 Наблюдатель",
    }

    @staticmethod
    def build_family_member_view_models(
        members: List[FamilyMemberDTO],
        current_user_id: int,
        dicts_dto: SchoolDictionariesDTO,
    ) -> List[FamilyMemberViewModel]:
        """
        Строит ViewModel для списка состава семьи.

        Сортировка: текущий пользователь первым,
        затем parent > child > observer.
        Классы детей расшифрованы через SchoolDictionariesDTO.
        """
        view_models = []
        for member in members:
            # Класс — только для ребёнка
            if member.role == "child" and member.class_id:
                class_name = dicts_dto.get_readable_class(
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
                    role_display=ProfileService._ROLE_DISPLAY.get(
                        member.role,
                        member.role,
                    ),
                    class_name=class_name,
                    is_current_user=(
                        member.user_id == current_user_id
                    ),
                )
            )

        # Сортировка: текущий пользователь → приоритет роли
        view_models.sort(
            key=lambda vm: (
                0 if vm.is_current_user else 1,
                ProfileService._ROLE_PRIORITY.get(vm.role, 4),
            )
        )

        return view_models


    @staticmethod
    def build_student_telegram_settings_view_model(
        dto: StudentTelegramSettingsDTO,
        dicts_dto: SchoolDictionariesDTO,
    ) -> StudentTelegramSettingsViewModel:
        """
        Строит ViewModel для экрана Telegram-настроек ребёнка.
        """
        return StudentTelegramSettingsViewModel(
            student_id=dto.student_id,
            student_name=dto.student_name,
            class_name=dicts_dto.get_readable_class(dto.class_id),
            group_name=dicts_dto.get_readable_group(dto.group_id),
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
    def build_parent_student_notification_view_model(
        dto: ParentStudentNotificationSettingsDTO,
        dicts_dto: SchoolDictionariesDTO,
    ) -> ParentStudentNotificationSettingsViewModel:
        """
        Строит ViewModel для экрана подписок взрослого.
        """
        telegram_connected = dto.telegram_user_id is not None

        return ParentStudentNotificationSettingsViewModel(
            student_id=dto.student_id,
            student_name=dto.student_name,
            class_name=dicts_dto.get_readable_class(
                dto.student_class_id,
            ),
            group_name=dicts_dto.get_readable_group(
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

