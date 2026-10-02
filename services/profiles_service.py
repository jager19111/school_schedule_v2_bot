# services/profiles_service.py
import logging
from typing import List, Optional, Tuple
import time

from core.repository.profile_repository import ProfileRepository
from services.audit_service import AuditService
from core.models.dto import (
    AdultStudentExtraClassesPermissionDTO,
    AuditAction,
    FamilyInviteDTO,
    FamilyMemberDTO,
    FamilyMemberViewModel,
    ParentStudentNotificationSettingsDTO,
    ParentStudentNotificationSettingsViewModel,
    ProfileResetImpactDTO,
    SchoolDictionariesDTO,
    StudentTelegramSettingsDTO,
    StudentTelegramSettingsViewModel,
    UserProfileDTO,     FamilyInviteCodeLookupDTO,
)
from core.mappers.profile_mapper import ProfileMapper

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

    def __init__(self, repo: ProfileRepository, audit_service: AuditService):
        self.repo = repo
        self.audit = audit_service
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

        Audit USER_REGISTERED создаётся только при фактической вставке
        нового пользователя, а не при каждом повторном /start.
        """
        created = await self.repo.register_user_initial(user_id)

        if created:
            await self.audit.log_action(
                actor_id=user_id,
                target_id=user_id,
                action=AuditAction.USER_REGISTERED,
            )

    async def update_last_active(self, user_id: int) -> None:
        """
        Обновляет время последней активности.
        """
        await self.repo.update_last_active(user_id)


    async def update_user_role(self, user_id: int, role: str) -> None:
        """Делегирует обновление роли и настроек репозиторию."""
        await self.repo.update_role_and_defaults(user_id, role)
        await self.audit.log_action(
            actor_id=user_id, target_id=user_id, 
            action=AuditAction.SETTINGS_CHANGED, 
            details={"setting_name": "role", "new_value": role}
        )
        
    # ========== ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ==========

    async def get_user_profile_dto(self, user_id: int) -> UserProfileDTO:
        """
        Возвращает DTO с информацией о пользователе.

        SQL остаётся в ProfileRepository, а row → DTO преобразование
        выполняется в ProfileMapper.
        """
        row = await self.repo.get_user_profile_for_dto(user_id)

        # Троттлинг активности выполняется только для реально существующего
        # пользователя. Для row=None ничего в БД не записываем.
        if row:
            await self._touch_last_active(user_id)

        return ProfileMapper.to_user_profile_dto(
            row,
            user_id=user_id,
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
        code = await self.repo.create_family_and_link(admin_user_id)
        await self.audit.log_action(
            actor_id=admin_user_id, target_id=admin_user_id, 
            action=AuditAction.FAMILY_CREATED, 
            details={"code": code}
        )
        return code

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
        
        await self.audit.log_action(
            actor_id=created_by_user_id, target_id=created_by_user_id, 
            action=AuditAction.INVITE_CREATED, 
            details={"role": intended_role}
        )
        return ProfileMapper.to_family_invite_dto(row)
        
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

        return ProfileMapper.to_family_invite_dto(row)

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

        await self.audit.log_action(
            actor_id=user_id, target_id=user_id, 
            action=AuditAction.INVITE_USED, 
            details={"role": result["intended_role"]}
        )
        return result["intended_role"]
    

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

        return ProfileMapper.to_family_invite_dto_list(rows)

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

        return ProfileMapper.to_family_invite_dto(row)

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

    async def get_valid_family_invite_by_code(
        self,
        short_code: str,
    ) -> FamilyInviteCodeLookupDTO | None:
        """
        Возвращает действующее приглашение по печатаемому short code.

        DTO намеренно содержит только invite token и назначенную роль;
        metadata семьи не выдаётся в registration layer.
        """
        row = await self.repo.get_valid_family_invite_by_code(short_code)

        if row is None:
            return None

        return ProfileMapper.to_family_invite_code_lookup_dto(row)
    
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

        await self.audit.log_action(
            actor_id=user_id, target_id=user_id, 
            action=AuditAction.SETTINGS_CHANGED, 
            details={"setting_name": field_name, "new_value": "toggled"}
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

        return ProfileMapper.to_profile_reset_impact_dto(row)
          
    async def reset_user_profile(
        self,
        user_id: int,
    ) -> Tuple[bool, Optional[int]]:
        """
        Сброс/выход пользователя.

        Администратор семьи:
        - есть второй родитель -> полномочия автоматически переходят
          ему, админ выходит как обычный пользователь (семья живёт);
        - второго родителя нет -> семья расформировывается.

        Возвращает (success, new_admin_id): new_admin_id задан только
        при авто-передаче — хендлер шлёт по нему уведомление.
        """
        # Используем метод сервиса, возвращающий DTO
        impact = await self.get_profile_reset_impact(user_id)
        
        if impact is not None and impact.is_family_admin:
            family_id = impact.family_id

            successor_id = await self.repo.find_family_admin_successor(
                family_id=family_id,
                excluding_user_id=user_id,
            )

            if successor_id is not None:
                transferred = await self.repo.transfer_family_admin(
                    from_user_id=user_id,
                    to_user_id=successor_id,
                    family_id=family_id,
                )

                if not transferred:
                    logger.error(
                        "Family admin transfer failed: family_id=%s, "
                        "from_user_id=%s, to_user_id=%s",
                        family_id,
                        user_id,
                        successor_id,
                    )
                    return False, None

                reset_ok = await self.repo.reset_non_admin_user(
                    user_id=user_id,
                )

                if reset_ok:
                    await self.audit.log_action(
                        user_id,
                        successor_id,
                        AuditAction.FAMILY_ADMIN_TRANSFERRED,
                    )
                    await self.audit.log_action(
                        user_id,
                        user_id,
                        AuditAction.PROFILE_RESET,
                        {
                            "details": "Успешная передача прав",
                        },
                    )

                return reset_ok, successor_id

            # Расформирование допустимо только тогда, когда другого
            # parent в семье действительно нет.
            disbanded = await self.repo.disband_family_by_admin(
                admin_user_id=user_id,
            )

            if disbanded:
                await self.audit.log_action(
                    user_id,
                    user_id,
                    AuditAction.PROFILE_RESET,
                    {
                        "details": "Семья расформирована",
                    },
                )

            return disbanded, None
    
    # метод получения состава семьи
    async def get_family_members(
        self,
        family_id: int,
    ) -> list[FamilyMemberDTO]:
        """Возвращает список всех участников семьи."""
        rows = await self.repo.get_family_members_rows(family_id)

        return ProfileMapper.to_family_member_dto_list(rows)
    
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

        return ProfileMapper.to_parent_student_notification_settings_dto(row)

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

        return (
            ProfileMapper.to_adult_student_extra_classes_permission_dto_list(rows))

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
        result = await self.repo.set_adult_student_extra_classes_permission(admin_user_id=admin_user_id, adult_user_id=adult_user_id, student_id=student_id, can_manage=can_manage)
        if result:
            await self.audit.log_action(
                actor_id=admin_user_id, target_id=adult_user_id, 
                action=AuditAction.EXTRA_CLASS_PERMISSION_CHANGED, 
                details={"student_id": student_id, "can_manage": can_manage}
            )
        return result
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

        return ProfileMapper.to_student_telegram_settings_dto(row)
        
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
        result = await self.repo.set_student_notification_settings_locked(admin_user_id=admin_user_id, student_id=student_id, locked=locked)
        if result:
            await self.audit.log_action(
                actor_id=admin_user_id, target_id=student_id, 
                action=AuditAction.SETTINGS_LOCKED, 
                details={"new_value": locked}
            )
        return result
        
    # ==========================================================
    # ЭТАП 5: ViewModel builders
    # ==========================================================

    @staticmethod
    def build_family_member_view_models(
        members: List[FamilyMemberDTO],
        current_user_id: int,
        dicts_dto: SchoolDictionariesDTO,
    ) -> List[FamilyMemberViewModel]:
        """Compatibility facade: DTO → ViewModel logic lives in ProfileMapper."""
        return ProfileMapper.to_family_member_view_models(
            members,
            current_user_id=current_user_id,
            dictionaries=dicts_dto,
        )

    @staticmethod
    def build_student_telegram_settings_view_model(
        dto: StudentTelegramSettingsDTO,
        dicts_dto: SchoolDictionariesDTO,
    ) -> StudentTelegramSettingsViewModel:
        """Compatibility facade: DTO → ViewModel logic lives in ProfileMapper."""
        return ProfileMapper.to_student_telegram_settings_view_model(
            dto,
            dictionaries=dicts_dto,
        )

    @staticmethod
    def build_parent_student_notification_view_model(
        dto: ParentStudentNotificationSettingsDTO,
        dicts_dto: SchoolDictionariesDTO,
    ) -> ParentStudentNotificationSettingsViewModel:
        """Compatibility facade: DTO → ViewModel logic lives in ProfileMapper."""
        return ProfileMapper.to_parent_student_notification_view_model(
            dto,
            dictionaries=dicts_dto,
        )
    # ---------------------------------------------------------
    # ADMIN TRANSFER / SUCCESSION
    # ---------------------------------------------------------
    async def get_family_transfer_candidates(
        self,
        family_id: int,
        exclude_user_id: int,
    ) -> List[FamilyMemberDTO]:
        """
        Кандидаты на передачу полномочий: родители семьи,
        кроме текущего пользователя. Observer и child
        полномочия получать не могут.
        """
        members = await self.get_family_members(family_id)
        return [
            member
            for member in members
            if member.role == "parent"
            and member.user_id != exclude_user_id
        ]

    async def transfer_family_admin(
        self,
        from_user_id: int,
        to_user_id: int,
    ) -> bool:
        """
        Ручная передача полномочий администратора семьи.

        Отправитель — текущий админ, получатель — родитель той же
        семьи (user_id из callback не является источником доверия:
        всё перепроверяется здесь). После передачи бывший админ
        остаётся в семье как обычный родитель.
        """
        actor_dto = await self.get_user_profile_dto(from_user_id)
        if actor_dto is None or actor_dto.family_id is None:
            return False
        if not await self.is_family_admin(
            user_id=from_user_id,
            family_id=actor_dto.family_id,
        ):
            return False
        target_dto = await self.get_user_profile_dto(to_user_id)
        if (
            target_dto is None
            or target_dto.family_id != actor_dto.family_id
            or target_dto.role != "parent"
        ):
            return False
        transferred = await self.repo.transfer_family_admin(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            family_id=actor_dto.family_id,
        )

        if transferred:
            await self.audit.log_action(
                actor_id=from_user_id,
                target_id=to_user_id,
                action=AuditAction.FAMILY_ADMIN_TRANSFERRED,
                details={
                    "family_id": actor_dto.family_id,
                    "mode": "manual",
                },
            )

        return transferred

    async def get_family_admin_successor(
        self,
        family_id: int,
        excluding_user_id: int,
    ) -> Optional[int]:
        """Кандидат на авто-наследование полномочий (или None)."""
        return await self.repo.find_family_admin_successor(
            family_id=family_id,
            excluding_user_id=excluding_user_id,
        )



