import logging
import contextlib
from urllib.parse import urlencode
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from services.profiles_service import ProfileService
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from core.models.dto import ChildrenListDTO, ClassListDTO, GroupListDTO
from services.students_service import StudentsService

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from services.time_service import TimeService
from services.schedule_service import ScheduleService
from bot.handlers.registration import RegistrationStates
from services.watch_targets_service import WatchTargetsService



logger = logging.getLogger(__name__)
router = Router()

async def _safe_edit_text(
    message: Message,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> bool:
    """
    Безопасно обновляет inline-сообщение.

    Telegram выбрасывает TelegramBadRequest, например если:
    - новый текст и keyboard не отличаются от текущих;
    - сообщение нельзя изменить;
    - callback пришёл по старому/удалённому сообщению.

    Ошибка логируется, но не прерывает handler.
    Другие ошибки намеренно не подавляются.
    """
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return True
    except TelegramBadRequest as exc:
        logger.debug(
            "Telegram edit_text skipped: %s",
            exc,
        )
        return False


async def _safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    """
    Безопасно закрывает Telegram callback spinner.

    Не допускает, чтобы вторичный TelegramBadRequest ломал рабочую
    бизнес-операцию после успешного изменения БД.
    """
    try:
        await callback.answer(
            text=text,
            show_alert=show_alert,
        )
    except TelegramBadRequest as exc:
        logger.debug(
            "Telegram callback answer skipped: %s",
            exc,
        )
async def _require_family_admin_for_child(
    callback: CallbackQuery,
    profile_service: ProfileService,
    child_user_id: int,
) -> bool:
    """
    Проверяет, что инициатор callback — администратор семьи ребёнка.

    Observer и обычный parent могут иметь доступ к просмотру ребёнка
    и к собственным подпискам, но не могут менять его личный профиль,
    уведомления, класс, группу или блокировку.
    """
    is_admin = await profile_service.is_family_admin_for_child(
        admin_user_id=callback.from_user.id,
        child_user_id=child_user_id,
    )

    if is_admin:
        return True

    await _safe_callback_answer(
        callback,
        "Только администратор семьи может менять настройки ребёнка.",
        show_alert=True,
    )

    return False        

async def _require_own_notification_settings_access(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> bool:
    """
    Проверяет, что пользователь может менять собственные уведомления.

    Для ребёнка учитывается блокировка, заданная администратором семьи.
    Parent и observer всегда меняют только свои настройки.
    """
    allowed = await profile_service.can_user_change_own_notification_settings(
        user_id=callback.from_user.id,
    )

    if allowed:
        return True

    await _safe_callback_answer(
        callback,
        "🔒 Ваши настройки уведомлений заблокированы "
        "администратором семьи.",
        show_alert=True,
    )

    return False

class SettingsStates(StatesGroup):
    waiting_for_my_time = State()
    waiting_for_child_time = State()
    waiting_for_watch_group = State()
    
    waiting_for_virtual_student_name = State()
    waiting_for_virtual_student_group = State()



# ================= 1. ПОИСК ПО ШКОЛЕ =================

@router.message(F.text == "🏫 Поиск по школе")
async def show_school_search(message: Message):
    text = UIRenderer.render_school_search_menu()
    kb = Keyboards.get_school_search_kb()
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

# ================= 2. ГЛАВНЫЕ НАСТРОЙКИ =================

@router.message(F.text == "⚙️ Настройки")
async def settings_main_menu(message: Message, profile_service: ProfileService, schedule_service: ScheduleService):
    """Главное меню настроек. Вызывается из главного меню и после изменения настроек."""
    await _show_settings_menu(message, message.from_user.id, profile_service, schedule_service, is_callback=False)

# refresh-функция перед callback handlers child_ctl:*.
async def _refresh_child_control_menu(
    callback: CallbackQuery,
    child_user_id: int,
    profile_service: ProfileService,
) -> None:
    """
    Перерисовывает экран профиля ребёнка.

    Управляющие кнопки показываются только семейному администратору.
    Обычный parent/observer может видеть ограниченный экран просмотра.
    """
    actor_user_id = callback.from_user.id

    child_dto = await profile_service.get_user_profile_dto(
        child_user_id,
    )

    if child_dto.role != "child":
        logger.warning(
            "Child control refresh rejected: target_user_id=%s role=%s",
            child_user_id,
            child_dto.role,
        )

        await _safe_callback_answer(
            callback,
            "Этот профиль не является профилем ребёнка.",
            show_alert=True,
        )
        return

    is_family_admin = await profile_service.is_family_admin_for_child(
        admin_user_id=actor_user_id,
        child_user_id=child_user_id,
    )

    is_locked = await profile_service.is_child_notification_settings_locked(
        child_user_id=child_user_id,
    )

    text = UIRenderer.render_child_settings_menu(
        child_dto.name,
        child_dto.class_id,
    )

    keyboard = Keyboards.get_child_settings_kb(
        child_dto=child_dto,
        is_family_admin=is_family_admin,
        is_notifications_locked=is_locked,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )
# Обработчик юлокировок после refresh-функцию
@router.callback_query(F.data.startswith("child_ctl:lock:"))
async def toggle_child_notification_settings_lock(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """Администратор включает или снимает lock настроек ребёнка."""
    try:
        child_user_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    if not await _require_family_admin_for_child(
        callback=callback,
        profile_service=profile_service,
        child_user_id=child_user_id,
    ):
        return

    is_locked = await profile_service.is_child_notification_settings_locked(
        child_user_id=child_user_id,
    )

    changed = await profile_service.set_child_notification_settings_locked(
        admin_user_id=callback.from_user.id,
        child_user_id=child_user_id,
        locked=not is_locked,
    )

    if not changed:
        logger.warning(
            "Failed to change child lock: admin_id=%s child_id=%s",
            callback.from_user.id,
            child_user_id,
        )

        await _safe_callback_answer(
            callback,
            "Не удалось изменить блокировку настроек ребёнка.",
            show_alert=True,
        )
        return

    await _refresh_child_control_menu(
        callback=callback,
        child_user_id=child_user_id,
        profile_service=profile_service,
    )

    await _safe_callback_answer(
        callback,
        (
            "Блокировка настроек ребёнка включена."
            if not is_locked
            else "Блокировка настроек ребёнка выключена."
        ),
    )

@router.callback_query(F.data.startswith("child_ctl:notif:"))
async def toggle_child_notifications_by_admin(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """Администратор меняет users.is_notifications_enabled ребёнка."""
    try:
        child_user_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    if not await _require_family_admin_for_child(
        callback=callback,
        profile_service=profile_service,
        child_user_id=child_user_id,
    ):
        return

    changed = await profile_service.toggle_child_notifications_enabled(
        admin_user_id=callback.from_user.id,
        child_user_id=child_user_id,
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить уведомления ребёнка.",
            show_alert=True,
        )
        return

    await _refresh_child_control_menu(
        callback=callback,
        child_user_id=child_user_id,
        profile_service=profile_service,
    )

    await _safe_callback_answer(
        callback,
        "Настройки уведомлений ребёнка обновлены.",
    )

@router.callback_query(F.data.startswith("child_ctl:own_extra_edit:"))
async def toggle_child_own_extra_classes_management(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Администратор разрешает или запрещает ребёнку
    самостоятельно управлять собственными дополнительными занятиями.
    """
    try:
        child_user_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    if not await _require_family_admin_for_child(
        callback=callback,
        profile_service=profile_service,
        child_user_id=child_user_id,
    ):
        return

    changed = await profile_service.toggle_child_own_extra_classes_management(
        admin_user_id=callback.from_user.id,
        child_user_id=child_user_id,
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить право ребёнка на редактирование занятий.",
            show_alert=True,
        )
        return

    await _refresh_child_control_menu(
        callback=callback,
        child_user_id=child_user_id,
        profile_service=profile_service,
    )

    await _safe_callback_answer(
        callback,
        "Право ребёнка на управление занятиями обновлено.",
    )
    
@router.callback_query(F.data.startswith("child_ctl:prelesson:"))
async def toggle_child_pre_lesson_reminders(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """Администратор включает/выключает предурочные напоминания ребёнка."""
    try:
        child_user_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    if not await _require_family_admin_for_child(
        callback=callback,
        profile_service=profile_service,
        child_user_id=child_user_id,
    ):
        return

    child_dto = await profile_service.get_user_profile_dto(
        child_user_id,
    )

    new_value = (
        0
        if child_dto.pre_lesson_offset_minutes > 0
        else 10
    )

    changed = await profile_service.update_child_integer_notification_setting(
        admin_user_id=callback.from_user.id,
        child_user_id=child_user_id,
        field_name="pre_lesson_offset_minutes",
        value=new_value,
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить предурочные напоминания ребёнка.",
            show_alert=True,
        )
        return

    await _refresh_child_control_menu(
        callback=callback,
        child_user_id=child_user_id,
        profile_service=profile_service,
    )

    await _safe_callback_answer(
        callback,
        "Настройка напоминаний об уроках обновлена.",
    )

@router.callback_query(F.data.startswith("child_ctl:changes:"))
async def toggle_child_schedule_changes(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """Администратор включает/выключает уведомления ребёнка о заменах."""
    try:
        child_user_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    if not await _require_family_admin_for_child(
        callback=callback,
        profile_service=profile_service,
        child_user_id=child_user_id,
    ):
        return

    changed = await profile_service.toggle_child_boolean_notification_setting(
        admin_user_id=callback.from_user.id,
        child_user_id=child_user_id,
        field_name="receive_schedule_changes",
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить уведомления ребёнка о заменах.",
            show_alert=True,
        )
        return

    await _refresh_child_control_menu(
        callback=callback,
        child_user_id=child_user_id,
        profile_service=profile_service,
    )

    await _safe_callback_answer(
        callback,
        "Настройки уведомлений о заменах обновлены.",
    )

@router.callback_query(F.data.startswith("child_ctl:extra:"))
async def toggle_child_extra_class_reminders(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """Администратор включает/выключает напоминания ребёнку о допзанятиях."""
    try:
        child_user_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    if not await _require_family_admin_for_child(
        callback=callback,
        profile_service=profile_service,
        child_user_id=child_user_id,
    ):
        return

    changed = await profile_service.toggle_child_boolean_notification_setting(
        admin_user_id=callback.from_user.id,
        child_user_id=child_user_id,
        field_name="receive_extra_class_reminders",
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить напоминания о допзанятиях ребёнка.",
            show_alert=True,
        )
        return

    await _refresh_child_control_menu(
        callback=callback,
        child_user_id=child_user_id,
        profile_service=profile_service,
    )

    await _safe_callback_answer(
        callback,
        "Настройки дополнительных занятий ребёнка обновлены.",
    )

@router.callback_query(F.data.startswith("child_ctl:extra_permissions:"))
async def show_adult_extra_classes_permissions(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает семейному администратору права взрослых
    на дополнительные занятия выбранного ребёнка.
    """
    try:
        child_user_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    admin_user_id = callback.from_user.id

    permissions = await profile_service.get_adult_extra_classes_permissions(
        admin_user_id=admin_user_id,
        child_user_id=child_user_id,
    )

    if permissions is None:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может менять права взрослых.",
            show_alert=True,
        )
        return

    child_dto = await profile_service.get_user_profile_dto(
        child_user_id,
    )

    text = UIRenderer.render_adult_extra_classes_permissions(
        child_name=child_dto.name or f"Ученик {child_user_id}",
        permissions=permissions,
    )

    keyboard = Keyboards.get_adult_extra_classes_permissions_kb(
        child_user_id=child_user_id,
        permissions=permissions,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

@router.callback_query(F.data.startswith("extra_perm:toggle:"))
async def toggle_adult_extra_classes_permission(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Администратор включает или выключает право другого взрослого
    управлять занятиями конкретного ребёнка.
    """
    try:
        _, _, child_id_raw, adult_id_raw = callback.data.split(":")

        child_user_id = int(child_id_raw)
        adult_user_id = int(adult_id_raw)
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректные параметры права.",
            show_alert=True,
        )
        return

    admin_user_id = callback.from_user.id

    permissions = await profile_service.get_adult_extra_classes_permissions(
        admin_user_id=admin_user_id,
        child_user_id=child_user_id,
    )

    if permissions is None:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может менять права взрослых.",
            show_alert=True,
        )
        return

    selected_permission = next(
        (
            item
            for item in permissions
            if item.adult_user_id == adult_user_id
        ),
        None,
    )

    if selected_permission is None:
        await _safe_callback_answer(
            callback,
            "Взрослый не найден среди участников семьи.",
            show_alert=True,
        )
        return

    changed = await profile_service.set_adult_extra_classes_permission(
        admin_user_id=admin_user_id,
        adult_user_id=adult_user_id,
        child_user_id=child_user_id,
        can_manage=not selected_permission.can_manage_extra_classes,
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить право управления занятиями.",
            show_alert=True,
        )
        return

    refreshed_permissions = (
        await profile_service.get_adult_extra_classes_permissions(
            admin_user_id=admin_user_id,
            child_user_id=child_user_id,
        )
    )

    child_dto = await profile_service.get_user_profile_dto(
        child_user_id,
    )

    text = UIRenderer.render_adult_extra_classes_permissions(
        child_name=child_dto.name or f"Ученик {child_user_id}",
        permissions=refreshed_permissions,
    )

    keyboard = Keyboards.get_adult_extra_classes_permissions_kb(
        child_user_id=child_user_id,
        permissions=refreshed_permissions,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(
        callback,
        "Права на дополнительные занятия обновлены.",
    )
                    
@router.callback_query(F.data.startswith("child_ctl:class:"))
async def child_settings_change_class(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Только администратор семьи запускает изменение класса/группы ребёнка.
    """
    try:
        child_user_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    if not await _require_family_admin_for_child(
        callback=callback,
        profile_service=profile_service,
        child_user_id=child_user_id,
    ):
        return

    class_dto = await schedule_service.get_classes_list()

    text = UIRenderer.render_class_selection(class_dto)
    keyboard = Keyboards.get_class_selection(class_dto)

    await state.update_data(
        editing_child_id=child_user_id,
        editing_child_admin_id=callback.from_user.id,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await state.set_state(RegistrationStates.waiting_for_class)

    await _safe_callback_answer(callback)
                
@router.callback_query(F.data == "settings:main")
async def settings_main_menu_cb(callback: CallbackQuery, profile_service: ProfileService, schedule_service: ScheduleService):
    """Главное меню настроек. Вызывается из коллбэка после изменения настроек."""
    await _show_settings_menu(callback.message, callback.from_user.id, profile_service, schedule_service, is_callback=True)
    await callback.answer()

async def _show_settings_menu(
    message_obj: Message, 
    user_id: int, 
    profile_service: ProfileService, 
    schedule_service: ScheduleService,  # <-- Сервис расписания обязателен
    is_callback: bool
):
    user_dto = await profile_service.get_user_profile_dto(user_id)
    family_code = await profile_service.get_family_code(user_dto.family_id) if user_dto.family_id else None
    
    # Запрашиваем красивые имена из сервиса расписания
    class_name = None
    group_names = None
    
    if user_dto.class_id:
        class_dto = await schedule_service.get_classes_list()
        class_name = class_dto.classes.get(user_dto.class_id, user_dto.class_id)
        
    if user_dto.group_id:
        if user_dto.group_id == "ALL":
            group_names = "Весь класс (без групп)"
        else:
            groups_dto = await schedule_service.get_groups_list()
            # Превращаем "4,0,1,2" в "2 группа, Группа 1, Группа 2, Группа 3"
            names = [groups_dto.groups.get(g, f"Группа {g}") for g in user_dto.group_id.split(",")]
            group_names = ", ".join(names)
            
    # Передаем подготовленные строки в рендерер
    text = UIRenderer.render_settings_main(user_dto, family_code, class_name, group_names)
    kb = Keyboards.get_settings_main_kb(user_dto)
    
    if is_callback:
        await message_obj.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message_obj.answer(text, reply_markup=kb, parse_mode="HTML")

# ================= ПЕРЕРЕГИСТРАЦИЯ =================
@router.callback_query(F.data == "auth:restart")
async def process_restart(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает последствия перерегистрации.

    Никакие данные здесь не удаляются.
    """
    impact = await profile_service.get_profile_reset_impact(
        user_id=callback.from_user.id,
    )

    if impact is None:
        await _safe_callback_answer(
            callback,
            "Не удалось найти ваш профиль.",
            show_alert=True,
        )
        return

    text = UIRenderer.render_profile_reset_confirmation(
        impact,
    )

    keyboard = Keyboards.get_profile_reset_confirmation_kb()

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

@router.callback_query(F.data == "auth:restart_confirm")
async def confirm_restart(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    """
    Выполняет перерегистрацию только после явного подтверждения.
    """
    user_id = callback.from_user.id

    try:
        success = await profile_service.reset_user_profile(
            user_id=user_id,
        )

    except ValueError as exc:
        logger.warning(
            "Profile reset rejected: user_id=%s, error=%s",
            user_id,
            exc,
        )

        await _safe_callback_answer(
            callback,
            "Не удалось перерегистрировать профиль.",
            show_alert=True,
        )
        return

    except Exception:
        logger.exception(
            "Profile reset failed: user_id=%s",
            user_id,
        )

        await _safe_callback_answer(
            callback,
            "❌ Не удалось выполнить перерегистрацию. "
            "Попробуйте ещё раз.",
            show_alert=True,
        )
        return

    if not success:
        await _safe_callback_answer(
            callback,
            "Не удалось выполнить перерегистрацию.",
            show_alert=True,
        )
        return

    await state.clear()

    try:
        await callback.message.edit_text(
            "✅ Профиль сброшен.\n\n"
            "Отправьте /start, чтобы пройти регистрацию заново."
        )
    except TelegramBadRequest as exc:
        logger.debug(
            "Restart confirmation message update skipped: %s",
            exc,
        )

    await _safe_callback_answer(
        callback,
        "Профиль успешно сброшен.",
    )
        
# ================= 3. УПРАВЛЕНИЕ СЕМЬЕЙ =================
# Порядок хендлеров важен
#1. family:invite_menu
#2. family:invite_role:
#3. family:invite_revoke_confirm:
#4. family:invite_revoke:
#5. family:invite:
#6. family:invites
@router.callback_query(F.data == "family:invite_menu")
async def show_family_invite_menu(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает admin-у список role-specific invites.
    """
    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if not user_dto.family_id:
        await _safe_callback_answer(
            callback,
            "Вы не состоите в семье.",
            show_alert=True,
        )
        return

    is_family_admin = await profile_service.is_family_admin(
        user_id=callback.from_user.id,
        family_id=user_dto.family_id,
    )

    if not is_family_admin:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может создавать приглашения.",
            show_alert=True,
        )
        return

    text = UIRenderer.render_family_invite_role_menu()
    keyboard = Keyboards.get_family_invite_role_kb()

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

@router.callback_query(
    F.data.startswith("family:invite_role:")
)
async def create_family_invite(
    callback: CallbackQuery,
    bot: Bot,
    profile_service: ProfileService,
) -> None:
    """
    Создаёт one-time role-specific invite и отдаёт deep link.
    """
    try:
        intended_role = callback.data.split(":")[2]
    except IndexError:
        await _safe_callback_answer(
            callback,
            "Некорректная роль приглашения.",
            show_alert=True,
        )
        return

    allowed_roles = {
        "child",
        "parent",
        "observer",
    }

    if intended_role not in allowed_roles:
        await _safe_callback_answer(
            callback,
            "Неизвестная роль приглашения.",
            show_alert=True,
        )
        return

    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if not user_dto.family_id:
        await _safe_callback_answer(
            callback,
            "Вы не состоите в семье.",
            show_alert=True,
        )
        return

    invite = await profile_service.create_family_invite(
        created_by_user_id=callback.from_user.id,
        family_id=user_dto.family_id,
        intended_role=intended_role,
        expires_in_hours=24,
    )

    if invite is None:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может создавать приглашения.",
            show_alert=True,
        )
        return

    me = await bot.get_me()

    if not me.username:
        logger.error(
            "Bot username is empty; cannot build deep link."
        )

        await _safe_callback_answer(
            callback,
            "Не удалось сформировать ссылку приглашения. "
            "У bot отсутствует username.",
            show_alert=True,
        )
        return

    deep_link = (
        f"https://t.me/{me.username}"
        f"?start=join_{invite.token}"
    )
    role_for_recipient = {
        "child": "ребёнка",
        "parent": "родителя",
        "observer": "наблюдателя",
    }[invite.intended_role]

    share_text = (
        "👋 Вас пригласили присоединиться к семье "
        "школьного расписания.\n\n"
        f"Роль: {role_for_recipient}.\n"
        "Откройте ссылку и завершите регистрацию."
    )

    share_link = (
        "https://t.me/share/url?"
        + urlencode(
            {
                "url": deep_link,
                "text": share_text,
            }
        )
    )
    
    role_label = {
        "child": "Ребёнок с Telegram",
        "parent": "Родитель",
        "observer": "Наблюдатель",
    }[invite.intended_role]

    text = UIRenderer.render_family_invite_created(
        role_label=role_label,
        expires_at=invite.expires_at,
    )

    keyboard = Keyboards.get_family_invite_result_kb(
        share_link=share_link,
        deep_link=deep_link,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await callback.message.answer(
        "📎 <b>Ссылка приглашения</b>\n\n"
        f"{deep_link}\n\n"
        "Вы можете скопировать или переслать это сообщение. "
        "Ссылка одноразовая и действует ограниченное время.",
        parse_mode="HTML",
    )
    
    await _safe_callback_answer(
        callback,
        "Приглашение создано.",
    )

@router.callback_query(
    F.data.startswith("family:invite_revoke_confirm:")
)
async def revoke_family_invite(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Отзывает invite после явного подтверждения.
    """
    try:
        invite_id = int(
            callback.data.split(":")[2]
        )
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор приглашения.",
            show_alert=True,
        )
        return

    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if not user_dto.family_id:
        await _safe_callback_answer(
            callback,
            "Вы не состоите в семье.",
            show_alert=True,
        )
        return

    revoked = await profile_service.revoke_family_invite(
        invite_id=invite_id,
        family_id=user_dto.family_id,
        admin_user_id=callback.from_user.id,
    )

    if not revoked:
        await _safe_callback_answer(
            callback,
            "Приглашение уже использовано, отозвано или недоступно.",
            show_alert=True,
        )
        return

    invites = await profile_service.get_active_family_invites(
        admin_user_id=callback.from_user.id,
        family_id=user_dto.family_id,
    )

    text = (
        "✅ <b>Приглашение отозвано.</b>\n\n"
        "Ссылка больше не позволит присоединиться к семье.\n\n"
        + UIRenderer.render_active_family_invites(invites)
    )

    keyboard = Keyboards.get_active_family_invites_kb(
        invites,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(
        callback,
        "Приглашение отозвано.",
    )
    
@router.callback_query(
    F.data.startswith("family:invite_revoke:")
)         
async def confirm_family_invite_revoke(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает confirmation перед revoke active invite.
    """
    try:
        invite_id = int(
            callback.data.split(":")[2]
        )
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор приглашения.",
            show_alert=True,
        )
        return

    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if not user_dto.family_id:
        await _safe_callback_answer(
            callback,
            "Вы не состоите в семье.",
            show_alert=True,
        )
        return

    invite = await profile_service.get_active_family_invite_by_id(
        invite_id=invite_id,
        family_id=user_dto.family_id,
        admin_user_id=callback.from_user.id,
    )

    if invite is None:
        await _safe_callback_answer(
            callback,
            "Приглашение уже недействительно.",
            show_alert=True,
        )
        return

    text = UIRenderer.render_family_invite_revoke_confirmation(
        invite,
    )

    keyboard = Keyboards.get_family_invite_revoke_confirmation_kb(
        invite_id=invite.id,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

@router.callback_query(F.data.startswith("family:invite:"))
async def show_family_invite_details(
    callback: CallbackQuery,
    bot: Bot,
    profile_service: ProfileService,
) -> None:
    """
    Показывает active invite и позволяет повторно отправить ссылку.
    """
    try:
        invite_id = int(
            callback.data.split(":")[2]
        )
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор приглашения.",
            show_alert=True,
        )
        return

    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if not user_dto.family_id:
        await _safe_callback_answer(
            callback,
            "Вы не состоите в семье.",
            show_alert=True,
        )
        return

    invite = await profile_service.get_active_family_invite_by_id(
        invite_id=invite_id,
        family_id=user_dto.family_id,
        admin_user_id=callback.from_user.id,
    )

    if invite is None:
        await _safe_callback_answer(
            callback,
            "Приглашение не найдено, уже использовано, отозвано "
            "или срок его действия истёк.",
            show_alert=True,
        )
        return

    me = await bot.get_me()

    if not me.username:
        await _safe_callback_answer(
            callback,
            "Bot username не задан, невозможно сформировать ссылку.",
            show_alert=True,
        )
        return

    deep_link = (
        f"https://t.me/{me.username}"
        f"?start=join_{invite.token}"
    )

    role_for_recipient = {
        "child": "ребёнка",
        "parent": "родителя",
        "observer": "наблюдателя",
    }[invite.intended_role]

    share_text = (
        "👋 Вас пригласили присоединиться к семье "
        "школьного расписания.\n\n"
        f"Роль: {role_for_recipient}.\n"
        "Откройте ссылку и завершите регистрацию."
    )

    share_link = (
        "https://t.me/share/url?"
        + urlencode(
            {
                "url": deep_link,
                "text": share_text,
            }
        )
    )

    text = UIRenderer.render_family_invite_details(
        invite,
    )

    keyboard = Keyboards.get_family_invite_details_kb(
        invite_id=invite.id,
        share_link=share_link,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

                  
@router.callback_query(F.data == "family:invites")
async def show_active_family_invites(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает family admin список активных invites.
    """
    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if not user_dto.family_id:
        await _safe_callback_answer(
            callback,
            "Вы не состоите в семье.",
            show_alert=True,
        )
        return

    invites = await profile_service.get_active_family_invites(
        admin_user_id=callback.from_user.id,
        family_id=user_dto.family_id,
    )

    if invites is None:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может видеть приглашения.",
            show_alert=True,
        )
        return

    text = UIRenderer.render_active_family_invites(
        invites,
    )

    keyboard = Keyboards.get_active_family_invites_kb(
        invites,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

   
@router.callback_query(F.data == "settings:family")
async def show_family_management(
    callback: CallbackQuery, 
    profile_service: ProfileService, 
    schedule_service: ScheduleService
):
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    
    if not user_dto.family_id:
        text = UIRenderer.render_family_management_error()
        kb = Keyboards.get_settings_main_kb(user_dto)
        return await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

    is_family_admin = await profile_service.is_family_admin(
        user_id=callback.from_user.id,
        family_id=user_dto.family_id,
    )
    
    # Получаем полный состав семьи
    family_members = await profile_service.get_family_members(user_dto.family_id)
    class_dto = await schedule_service.get_classes_list()
    
    text = UIRenderer.render_family_members_menu(family_members, user_dto, class_dto.classes)
    kb = Keyboards.get_family_management_kb(
        members=family_members,
        current_user=user_dto,
        classes_dict=class_dto.classes,
        is_family_admin=is_family_admin,
    )
    
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "settings:children_notifications")
async def show_children_notification_settings(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает взрослому список детей, по которым он может настроить
    персональные подписки.
    """
    parent_id = callback.from_user.id

    parent_dto = await profile_service.get_user_profile_dto(parent_id)

    if parent_dto.role not in ("parent", "observer"):
        await callback.answer(
            "Эта настройка доступна только родителям и наблюдателям.",
            show_alert=True,
        )
        return

    children = await profile_service.get_children_for_parent(parent_id)

    if not children:
        await callback.message.edit_text(
            "👥 У вас пока нет детей, доступных для настройки уведомлений.\n\n"
            "Сначала добавьте ребёнка в семью.",
            reply_markup=Keyboards.get_settings_main_kb(parent_dto),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    text = UIRenderer.render_parent_notification_children_menu()
    keyboard = Keyboards.get_parent_notification_children_kb(children)

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(F.data.startswith("pcn:child:"))
async def show_parent_child_notification_settings(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает настройки уведомлений текущего взрослого по ребёнку.
    """
    try:
        child_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer(
            "Некорректные данные выбранного ребёнка.",
            show_alert=True,
        )
        return

    parent_id = callback.from_user.id

    settings_dto = await profile_service.get_parent_child_notification_settings(
        parent_user_id=parent_id,
        child_user_id=child_id,
    )

    if settings_dto is None:
        logger.warning(
            "Parent-child notification access denied: parent_id=%s child_id=%s",
            parent_id,
            child_id,
        )
        await callback.answer(
            "У вас нет доступа к настройкам этого ребёнка.",
            show_alert=True,
        )
        return

    text = UIRenderer.render_parent_child_notification_settings(
        settings_dto,
    )

    keyboard = Keyboards.get_parent_child_notification_settings_kb(
        settings_dto,
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(F.data.startswith("pcn:toggle:"))
async def toggle_parent_child_notification_setting(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Переключает один тип уведомлений текущего взрослого
    для выбранного ребёнка.
    """
    try:
        _, _, setting_token, child_id_raw = callback.data.split(":")
        child_id = int(child_id_raw)
    except (ValueError, IndexError):
        await callback.answer(
            "Некорректные параметры настройки.",
            show_alert=True,
        )
        return

    setting_map = {
        "morning": "receive_morning_summary",
        "prelesson": "receive_pre_lesson_reminders",
        "changes": "receive_schedule_changes",
        "extra": "receive_extra_class_reminders",
    }

    setting_name = setting_map.get(setting_token)

    if setting_name is None:
        await callback.answer(
            "Неизвестный тип уведомления.",
            show_alert=True,
        )
        return

    parent_id = callback.from_user.id

    changed = await profile_service.toggle_parent_child_notification_setting(
        parent_user_id=parent_id,
        child_user_id=child_id,
        setting_name=setting_name,
    )

    if not changed:
        await callback.answer(
            "Не удалось изменить настройку. "
            "Возможно, у вас нет доступа к ребёнку.",
            show_alert=True,
        )
        return

    settings_dto = await profile_service.get_parent_child_notification_settings(
        parent_user_id=parent_id,
        child_user_id=child_id,
    )

    if settings_dto is None:
        await callback.answer(
            "Настройки ребёнка больше недоступны.",
            show_alert=True,
        )
        return

    text = UIRenderer.render_parent_child_notification_settings(
        settings_dto,
    )

    keyboard = Keyboards.get_parent_child_notification_settings_kb(
        settings_dto,
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    await callback.answer("Настройка обновлена")
            
@router.callback_query(F.data.startswith("family:child_settings:"))
async def show_child_settings(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает профиль ребёнка из семейного меню.

    Управляющие элементы доступны только администратору семьи.
    """
    try:
        child_user_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer(
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    actor_user_id = callback.from_user.id

    child_dto = await profile_service.get_user_profile_dto(
        child_user_id,
    )

    if child_dto.role != "child":
        await callback.answer(
            "Этот профиль не является профилем ребёнка.",
            show_alert=True,
        )
        return

    is_family_admin = await profile_service.is_family_admin_for_child(
        admin_user_id=actor_user_id,
        child_user_id=child_user_id,
    )

    has_access = await profile_service.parent_can_access_child(
        parent_user_id=actor_user_id,
        child_user_id=child_user_id,
    )

    if not has_access:
        await callback.answer(
            "У вас нет доступа к профилю этого ребёнка.",
            show_alert=True,
        )
        return

    is_locked = await profile_service.is_child_notification_settings_locked(
        child_user_id=child_user_id,
    )

    text = UIRenderer.render_child_settings_menu(
        child_dto.name,
        child_dto.class_id,
    )

    keyboard = Keyboards.get_child_settings_kb(
        child_dto=child_dto,
        is_family_admin=is_family_admin,
        is_notifications_locked=is_locked,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

 
# Настройки самого родителя
@router.callback_query(F.data == "settings:my_notifications")
async def toggle_my_notifications(
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Пользователь меняет собственный глобальный флаг уведомлений.

    Для ребёнка операция запрещается, если settings заблокированы
    администратором семьи.
    """
    changed = await profile_service.toggle_own_notifications_enabled(
        user_id=callback.from_user.id,
    )

    if not changed:
        await callback.answer(
            "🔒 Ваши настройки уведомлений заблокированы "
            "администратором семьи.",
            show_alert=True,
        )
        return

    await _show_settings_menu(
        message_obj=callback.message,
        user_id=callback.from_user.id,
        profile_service=profile_service,
        schedule_service=schedule_service,
        is_callback=True,
    )

    await callback.answer("Настройки уведомлений обновлены.")
    
async def _show_family_students_menu(
    *,
    callback: CallbackQuery,
    profile_service: ProfileService,
    students_service: StudentsService,
) -> None:
    """
    Рендерит список student_profiles, доступных текущему взрослому.
    """
    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if user_dto.role not in ("parent", "observer"):
        await _safe_callback_answer(
            callback,
            "Раздел учеников доступен только взрослым.",
            show_alert=True,
        )
        return

    if not user_dto.family_id:
        await _safe_callback_answer(
            callback,
            "Вы не состоите в семье.",
            show_alert=True,
        )
        return

    is_family_admin = await profile_service.is_family_admin(
        user_id=callback.from_user.id,
        family_id=user_dto.family_id,
    )

    students = await students_service.get_students_for_adult(
        adult_user_id=callback.from_user.id,
    )

    text = UIRenderer.render_family_students(
        students,
    )

    keyboard = Keyboards.get_family_students_kb(
        students,
        is_family_admin=is_family_admin,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )
            
    # ================= 5. ВВОД ВРЕМЕНИ СВОДКИ (FSM) =================

@router.callback_query(F.data == "settings:my_summary_time")
async def prompt_my_summary_time(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    """
    Запрашивает время личной утренней сводки.

    Если ребёнок заблокирован администратором семьи, изменение запрещено.
    Parent и observer всегда настраивают свои сводки независимо.
    """
    if not await _require_own_notification_settings_access(
        callback=callback,
        profile_service=profile_service,
    ):
        return

    text = UIRenderer.render_summary_time_prompt()
    keyboard = Keyboards.get_summary_time_prompt_kb()

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await state.set_state(SettingsStates.waiting_for_my_time)

    await _safe_callback_answer(callback)

@router.message(SettingsStates.waiting_for_my_time)
async def process_my_time(
    message: Message,
    state: FSMContext,
    time_service: TimeService,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Сохраняет личное время утренней сводки пользователя.
    """
    norm_time = time_service.normalize_time(message.text)

    if not norm_time:
        await message.answer(
            UIRenderer.render_invalid_time_format(),
            reply_markup=Keyboards.get_summary_time_prompt_kb(),
            parse_mode="HTML",
        )
        return

    changed = await profile_service.update_own_morning_summary_time(
        user_id=message.from_user.id,
        time_str=norm_time,
    )

    if not changed:
        await message.answer(
            "🔒 Ваши настройки уведомлений заблокированы "
            "администратором семьи."
        )
        return

    await state.clear()

    await _show_settings_menu(
        message_obj=message,
        user_id=message.from_user.id,
        profile_service=profile_service,
        schedule_service=schedule_service,
        is_callback=False,
    )
        
@router.callback_query(F.data.startswith("child_ctl:summary_time:"))
async def prompt_child_summary_time(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    """Администратор задаёт ребёнку время утренней сводки."""
    try:
        child_user_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    if not await _require_family_admin_for_child(
        callback=callback,
        profile_service=profile_service,
        child_user_id=child_user_id,
    ):
        return

    child_dto = await profile_service.get_user_profile_dto(
        child_user_id,
    )

    text = UIRenderer.render_summary_time_prompt(
        child_dto.name,
    )

    keyboard = Keyboards.get_summary_time_prompt_kb()

    await state.update_data(
        child_id=child_user_id,
        child_settings_admin_id=callback.from_user.id,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await state.set_state(SettingsStates.waiting_for_child_time)

    await _safe_callback_answer(callback)

@router.callback_query(F.data == "set_time:off")
async def turn_off_summary_time(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Отключает утреннюю сводку.

    Для ребёнка действие возможно только через FSM,
    созданный администратором семьи.
    """
    current_state = await state.get_state()
    data = await state.get_data()

    if current_state == SettingsStates.waiting_for_child_time.state:
        child_user_id = data.get("child_id")
        admin_user_id = data.get("child_settings_admin_id")

        if not child_user_id or admin_user_id != callback.from_user.id:
            await state.clear()

            await _safe_callback_answer(
                callback,
                "Состояние настройки устарело. Откройте настройки заново.",
                show_alert=True,
            )
            return

        changed = await profile_service.update_child_morning_summary_time(
            admin_user_id=admin_user_id,
            child_user_id=child_user_id,
            time_str=None,
        )

        await state.clear()

        if not changed:
            await _safe_callback_answer(
                callback,
                "Только администратор семьи может менять "
                "настройки ребёнка.",
                show_alert=True,
            )
            return

        await _refresh_child_control_menu(
            callback=callback,
            child_user_id=child_user_id,
            profile_service=profile_service,
        )

        await _safe_callback_answer(
            callback,
            "Утренняя сводка ребёнка отключена.",
        )
        return

    changed = await profile_service.update_own_morning_summary_time(
        user_id=callback.from_user.id,
        time_str=None,
    )

    await state.clear()

    if not changed:
        await _safe_callback_answer(
            callback,
            "🔒 Ваши настройки уведомлений заблокированы "
            "администратором семьи.",
            show_alert=True,
        )
        return

    await _show_settings_menu(
        message_obj=callback.message,
        user_id=callback.from_user.id,
        profile_service=profile_service,
        schedule_service=schedule_service,
        is_callback=True,
    )

    await _safe_callback_answer(
        callback,
        "Утренняя сводка отключена.",
    )

@router.message(SettingsStates.waiting_for_child_time)
async def process_child_time(
    message: Message,
    state: FSMContext,
    time_service: TimeService,
    profile_service: ProfileService,
) -> None:
    """Сохраняет время сводки ребёнка только от имени family admin."""
    norm_time = time_service.normalize_time(message.text)

    if not norm_time:
        text = UIRenderer.render_invalid_time_format()
        keyboard = Keyboards.get_summary_time_prompt_kb()

        await message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    data = await state.get_data()

    child_user_id = data.get("child_id")
    admin_user_id = data.get("child_settings_admin_id")

    if not child_user_id or admin_user_id != message.from_user.id:
        await state.clear()

        await message.answer(
            "❌ Состояние настройки устарело. "
            "Откройте настройки ребёнка заново."
        )
        return

    changed = await profile_service.update_child_morning_summary_time(
        admin_user_id=admin_user_id,
        child_user_id=child_user_id,
        time_str=norm_time,
    )

    if not changed:
        await state.clear()

        await message.answer(
            "🔒 Только администратор семьи может менять "
            "время сводки ребёнка."
        )
        return

    await state.clear()

    child_dto = await profile_service.get_user_profile_dto(
        child_user_id,
    )

    is_locked = await profile_service.is_child_notification_settings_locked(
        child_user_id,
    )

    text = UIRenderer.render_child_settings_menu(
        child_dto.name,
        child_dto.class_id,
    )

    keyboard = Keyboards.get_child_settings_kb(
        child_dto=child_dto,
        is_family_admin=True,
        is_notifications_locked=is_locked,
    )

    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    
@router.callback_query(F.data == "settings:cancel_input")
async def cancel_time_input(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """Отменяет ввод времени и возвращает пользователя к исходному экрану."""
    current_state = await state.get_state()
    data = await state.get_data()

    is_child_state = (
        current_state == SettingsStates.waiting_for_child_time.state
    )

    await state.clear()

    if is_child_state and data.get("child_id"):
        child_user_id = data["child_id"]

        has_access = await profile_service.parent_can_access_child(
            parent_user_id=callback.from_user.id,
            child_user_id=child_user_id,
        )

        if has_access:
            await _refresh_child_control_menu(
                callback=callback,
                child_user_id=child_user_id,
                profile_service=profile_service,
            )

            await _safe_callback_answer(callback)
            return

    await _show_settings_menu(
        message_obj=callback.message,
        user_id=callback.from_user.id,
        profile_service=profile_service,
        schedule_service=schedule_service,
        is_callback=True,
    )

    await _safe_callback_answer(callback)
    
# ================= НАСТРОЙКИ УВЕДОМЛЕНИЙ =================
@router.callback_query(F.data == "settings:notifications")
async def show_notifications_menu(callback: CallbackQuery, profile_service: ProfileService):
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    text = UIRenderer.render_notifications_menu(user_dto)
    kb = Keyboards.get_notifications_kb(user_dto)

# Глушим ошибку TelegramBadRequest, если меню не изменилось 
    # (например, при быстром двойном клике)
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        
    await callback.answer()
   
@router.callback_query(F.data == "set_notif:changes")
async def toggle_changes_notif(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    if not await _require_own_notification_settings_access(
        callback=callback,
        profile_service=profile_service,
    ):
        return

    changed = await profile_service.toggle_own_boolean_notification_setting(
        user_id=callback.from_user.id,
        field_name="receive_schedule_changes",
    )
    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить настройки уведомлений.",
            show_alert=True,
        )
        return

    await show_notifications_menu(
        callback=callback,
        profile_service=profile_service,
    )

@router.callback_query(F.data == "set_notif:prelesson")
async def toggle_prelesson_notif(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    if not await _require_own_notification_settings_access(
        callback=callback,
        profile_service=profile_service,
    ):
        return

    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    new_value = (
        0
        if user_dto.pre_lesson_offset_minutes > 0
        else 10
    )

    changed = await profile_service.update_own_integer_notification_setting(
        user_id=callback.from_user.id,
        field_name="pre_lesson_offset_minutes",
        value=new_value,
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить настройку предурочных уведомлений.",
            show_alert=True,
        )
        return

    await show_notifications_menu(
        callback=callback,
        profile_service=profile_service,
    )    

@router.callback_query(F.data == "set_notif:extra")
async def toggle_extra_notif(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    if not await _require_own_notification_settings_access(
        callback=callback,
        profile_service=profile_service,
    ):
        return

    changed = await profile_service.toggle_own_boolean_notification_setting(
        user_id=callback.from_user.id,
        field_name="receive_extra_class_reminders",
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить настройку дополнительных занятий.",
            show_alert=True,
        )
        return

    await show_notifications_menu(
        callback=callback,
        profile_service=profile_service,
    )

# ================= 5. СМЕНА КЛАССА И ГРУППЫ =================
   
    
@router.callback_query(F.data == "settings:change_class")
async def settings_change_class(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Смена класса/группы для собственного профиля.

    Ребёнок не может менять класс, если профиль заблокирован
    администратором семьи.
    """
    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if user_dto.role == "child":
        allowed = await profile_service.can_user_change_own_notification_settings(
            user_id=callback.from_user.id,
        )

        if not allowed:
            await _safe_callback_answer(
                callback,
                "🔒 Изменение профиля заблокировано "
                "администратором семьи.",
                show_alert=True,
            )
            return

    class_dto = await schedule_service.get_classes_list()

    text = UIRenderer.render_class_selection(class_dto)
    keyboard = Keyboards.get_class_selection(class_dto)

    await state.update_data(
        is_settings_edit=True,
        editing_own_profile_id=callback.from_user.id,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await state.set_state(RegistrationStates.waiting_for_class)

    await _safe_callback_answer(callback)
    
# Меню watch targets    
@router.callback_query(F.data == "watch:menu")
async def show_watch_targets_menu(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
) -> None:
    """
    Показывает самостоятельные отслеживаемые классы пользователя.
    """
    targets = await watch_targets_service.get_targets(
        owner_user_id=callback.from_user.id,
    )

    text = UIRenderer.render_watch_targets_menu(
        targets,
    )

    keyboard = Keyboards.get_watch_targets_menu_kb(
        targets,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

@router.callback_query(F.data == "watch:add")
async def start_add_watch_target(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    """
    Запускает выбор класса для direct watch target.
    """
    class_dto = await schedule_service.get_classes_list()

    if not class_dto.classes:
        await _safe_callback_answer(
            callback,
            "Расписание школы ещё не загружено. "
            "Попробуйте позже.",
            show_alert=True,
        )
        return

    text = (
        "🎓 <b>Добавить отслеживаемый класс</b>\n\n"
        "Выберите класс, расписание которого хотите отслеживать."
    )

    keyboard = Keyboards.get_watch_class_selection_kb(
        class_dto,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await state.set_state(
        SettingsStates.waiting_for_watch_group,
    )

    await state.update_data(
        watch_target_owner_id=callback.from_user.id,
        watch_target_stage="class",
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    SettingsStates.waiting_for_watch_group,
    F.data.startswith("watch:class:"),
)
async def select_watch_target_class(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    try:
        class_id = callback.data.split(":")[2]
    except IndexError:
        await _safe_callback_answer(
            callback,
            "Некорректный класс.",
            show_alert=True,
        )
        return

    data = await state.get_data()

    if data.get("watch_target_owner_id") != callback.from_user.id:
        await state.clear()

        await _safe_callback_answer(
            callback,
            "Состояние добавления устарело.",
            show_alert=True,
        )
        return

    groups_dto = await schedule_service.get_groups_list()

    await state.update_data(
        watch_target_class_id=class_id,
        watch_target_stage="group",
    )

    text = (
        "👥 <b>Выберите группу</b>\n\n"
        "Если группа неизвестна или класс не делится на группы, "
        "выберите «Весь класс»."
    )

    keyboard = Keyboards.get_watch_group_selection_kb(
        groups_dto,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    SettingsStates.waiting_for_watch_group,
    F.data.startswith("watch:group:"),
)
async def select_watch_target_group(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
    watch_targets_service: WatchTargetsService,
) -> None:
    try:
        group_id = callback.data.split(":")[2]
    except IndexError:
        await _safe_callback_answer(
            callback,
            "Некорректная группа.",
            show_alert=True,
        )
        return

    data = await state.get_data()

    owner_user_id = data.get("watch_target_owner_id")
    class_id = data.get("watch_target_class_id")

    if (
        owner_user_id != callback.from_user.id
        or not class_id
    ):
        await state.clear()

        await _safe_callback_answer(
            callback,
            "Состояние добавления устарело.",
            show_alert=True,
        )
        return

    class_dto = await schedule_service.get_classes_list()

    title = class_dto.classes.get(
        class_id,
        f"Класс {class_id}",
    )

    response = await watch_targets_service.add_target(
        owner_user_id=owner_user_id,
        class_id=class_id,
        group_id=group_id,
        title=title,
    )

    await state.clear()

    if not response.success:
        if response.error_code == "duplicate":
            error_text = (
                "⚠️ Этот класс и группа уже добавлены "
                "в отслеживание."
            )
        elif response.error_code == "limit_reached":
            error_text = (
                "⚠️ Достигнут лимит отслеживаемых классов "
                "(10)."
            )
        else:
            error_text = (
                "❌ Не удалось добавить отслеживаемый класс."
            )

        await _safe_callback_answer(
            callback,
            error_text,
            show_alert=True,
        )
        return

    targets = await watch_targets_service.get_targets(
        owner_user_id=owner_user_id,
    )

    text = (
        "✅ <b>Класс добавлен в отслеживание.</b>\n\n"
        + UIRenderer.render_watch_targets_menu(targets)
    )

    keyboard = Keyboards.get_watch_targets_menu_kb(
        targets,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(
        callback,
        "Класс добавлен.",
    )
    
@router.callback_query(
    F.data.startswith("watch:target:")
)
async def show_watch_target_details(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService,
) -> None:
    try:
        target_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор класса.",
            show_alert=True,
        )
        return

    targets = await watch_targets_service.get_targets(
        owner_user_id=callback.from_user.id,
    )

    target = next(
        (
            item
            for item in targets
            if item.id == target_id
        ),
        None,
    )

    if target is None:
        await _safe_callback_answer(
            callback,
            "Класс не найден или у вас нет доступа.",
            show_alert=True,
        )
        return

    classes_dto = await schedule_service.get_classes_list()
    groups_dto = await schedule_service.get_groups_list()

    class_name = classes_dto.classes.get(
        target.class_id,
        target.class_id,
    )

    group_name = (
        "Весь класс"
        if target.group_id == "ALL"
        else groups_dto.groups.get(
            target.group_id,
            f"Группа {target.group_id}",
        )
    )

    text = UIRenderer.render_watch_target_details(
        target=target,
        class_name=class_name,
        group_name=group_name,
    )

    keyboard = Keyboards.get_watch_target_details_kb(
        target_id=target.id,
        is_enabled=target.is_enabled,
        receive_schedule_changes=target.receive_schedule_changes,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

@router.callback_query(
    F.data.startswith("watch:toggle:")
)
async def toggle_watch_target(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService
) -> None:
    try:
        target_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор класса.",
            show_alert=True,
        )
        return

    targets = await watch_targets_service.get_targets(
        owner_user_id=callback.from_user.id,
    )

    target = next(
        (
            item
            for item in targets
            if item.id == target_id
        ),
        None,
    )

    if target is None:
        await _safe_callback_answer(
            callback,
            "Класс не найден.",
            show_alert=True,
        )
        return

    response = await watch_targets_service.set_target_enabled(
        owner_user_id=callback.from_user.id,
        target_id=target_id,
        is_enabled=not target.is_enabled,
    )

    if not response.success:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить состояние класса.",
            show_alert=True,
        )
        return

    await _safe_callback_answer(
        callback,
        "Отслеживание обновлено.",
    )

    # Повторный callback покажет свежую карточку.
    await show_watch_target_details(
        callback=callback,
        watch_targets_service=watch_targets_service,
        schedule_service=schedule_service,
    )    

@router.callback_query(
    F.data.startswith("watch:changes:")
)
async def toggle_watch_target_schedule_changes(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Включает или выключает уведомления об изменениях
    только для одного watch target.
    """
    try:
        target_id = int(
            callback.data.split(":")[2]
        )
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор класса.",
            show_alert=True,
        )
        return

    target = await watch_targets_service.get_target(
        owner_user_id=callback.from_user.id,
        target_id=target_id,
    )

    if target is None:
        await _safe_callback_answer(
            callback,
            "Класс не найден или у вас нет доступа.",
            show_alert=True,
        )
        return

    response = await watch_targets_service.set_target_receive_schedule_changes(
        owner_user_id=callback.from_user.id,
        target_id=target_id,
        receive_schedule_changes=(
            not target.receive_schedule_changes
        ),
    )

    if not response.success:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить настройки уведомлений.",
            show_alert=True,
        )
        return

    refreshed_target = await watch_targets_service.get_target(
        owner_user_id=callback.from_user.id,
        target_id=target_id,
    )

    classes_dto = await schedule_service.get_classes_list()
    groups_dto = await schedule_service.get_groups_list()

    class_name = classes_dto.classes.get(
        refreshed_target.class_id,
        refreshed_target.class_id,
    )

    group_name = (
        "Весь класс"
        if refreshed_target.group_id == "ALL"
        else groups_dto.groups.get(
            refreshed_target.group_id,
            f"Группа {refreshed_target.group_id}",
        )
    )

    text = UIRenderer.render_watch_target_details(
        target=refreshed_target,
        class_name=class_name,
        group_name=group_name,
    )

    keyboard = Keyboards.get_watch_target_details_kb(
        target_id=refreshed_target.id,
        is_enabled=refreshed_target.is_enabled,
        receive_schedule_changes=(
            refreshed_target.receive_schedule_changes
        ),
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    state_text = (
        "включены"
        if refreshed_target.receive_schedule_changes
        else "выключены"
    )

    await _safe_callback_answer(
        callback,
        f"Уведомления об изменениях {state_text}.",
    )
    
@router.callback_query(
    F.data.startswith("watch:delete:")
)
async def confirm_delete_watch_target(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
) -> None:
    try:
        target_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор класса.",
            show_alert=True,
        )
        return

    targets = await watch_targets_service.get_targets(
        owner_user_id=callback.from_user.id,
    )

    target = next(
        (
            item
            for item in targets
            if item.id == target_id
        ),
        None,
    )

    if target is None:
        await _safe_callback_answer(
            callback,
            "Класс не найден.",
            show_alert=True,
        )
        return

    title = target.title or f"Класс {target.class_id}"

    text = (
        "⚠️ <b>Удалить отслеживаемый класс?</b>\n\n"
        f"Класс: <b>{UIRenderer.escape_html(title)}</b>\n\n"
        "Расписание школы не будет удалено. "
        "Будет удалена только ваша личная цель отслеживания."
    )

    keyboard = Keyboards.get_watch_target_delete_confirmation_kb(
        target_id,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    F.data.startswith("watch:delete_confirm:")
)
async def delete_watch_target(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
) -> None:
    try:
        target_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор класса.",
            show_alert=True,
        )
        return

    response = await watch_targets_service.delete_target(
        owner_user_id=callback.from_user.id,
        target_id=target_id,
    )

    if not response.success:
        await _safe_callback_answer(
            callback,
            "Класс не найден или уже удалён.",
            show_alert=True,
        )
        return

    targets = await watch_targets_service.get_targets(
        owner_user_id=callback.from_user.id,
    )

    text = (
        "✅ <b>Отслеживаемый класс удалён.</b>\n\n"
        + UIRenderer.render_watch_targets_menu(targets)
    )

    keyboard = Keyboards.get_watch_targets_menu_kb(
        targets,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(
        callback,
        "Класс удалён.",
    )
    
# Виртуальный ученик

@router.callback_query(F.data == "family:students")
async def show_family_students(
    callback: CallbackQuery,
    profile_service: ProfileService,
    students_service: StudentsService,
) -> None:
    await _show_family_students_menu(
        callback=callback,
        profile_service=profile_service,
        students_service=students_service,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(F.data == "student:add")
async def start_add_virtual_student(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if not user_dto.family_id:
        await _safe_callback_answer(
            callback,
            "Вы не состоите в семье.",
            show_alert=True,
        )
        return

    is_family_admin = await profile_service.is_family_admin(
        user_id=callback.from_user.id,
        family_id=user_dto.family_id,
    )

    if not is_family_admin:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может добавлять учеников.",
            show_alert=True,
        )
        return

    await state.update_data(
        virtual_student_admin_id=callback.from_user.id,
        virtual_student_family_id=user_dto.family_id,
    )

    await _safe_edit_text(
        callback.message,
        UIRenderer.render_virtual_student_name_prompt(),
        reply_markup=Keyboards.get_cancel_keyboard(),
    )

    await state.set_state(
        SettingsStates.waiting_for_virtual_student_name,
    )

    await _safe_callback_answer(callback)
    
@router.message(
    SettingsStates.waiting_for_virtual_student_name
)
async def process_virtual_student_name(
    message: Message,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    name = message.text.strip()

    if not name:
        await message.answer(
            "❌ Введите имя ученика."
        )
        return

    if len(name) > 64:
        await message.answer(
            "❌ Имя слишком длинное. Используйте до 64 символов."
        )
        return

    data = await state.get_data()

    if data.get("virtual_student_admin_id") != message.from_user.id:
        await state.clear()

        await message.answer(
            "❌ Состояние добавления устарело. "
            "Откройте управление семьёй заново."
        )
        return

    class_dto = await schedule_service.get_classes_list()

    await state.update_data(
        virtual_student_name=name,
    )

    await message.answer(
        "🎓 <b>Выберите класс ученика</b>",
        reply_markup=Keyboards.get_student_class_selection_kb(
            class_dto,
        ),
        parse_mode="HTML",
    )

    await state.set_state(
        SettingsStates.waiting_for_virtual_student_group,
    )
    
@router.callback_query(
    SettingsStates.waiting_for_virtual_student_group,
    F.data.startswith("student:class:"),
)
async def select_virtual_student_class(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    try:
        class_id = callback.data.split(":")[2]
    except IndexError:
        await _safe_callback_answer(
            callback,
            "Некорректный класс.",
            show_alert=True,
        )
        return

    data = await state.get_data()

    if data.get("virtual_student_admin_id") != callback.from_user.id:
        await state.clear()

        await _safe_callback_answer(
            callback,
            "Состояние добавления устарело.",
            show_alert=True,
        )
        return

    groups_dto = await schedule_service.get_groups_list()

    await state.update_data(
        virtual_student_class_id=class_id,
    )

    await _safe_edit_text(
        callback.message,
        (
            "👥 <b>Выберите группу ученика</b>\n\n"
            "Если группа неизвестна, выберите «Весь класс»."
        ),
        reply_markup=Keyboards.get_student_group_selection_kb(
            groups_dto,
        ),
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    SettingsStates.waiting_for_virtual_student_group,
    F.data.startswith("student:group:"),
)
async def create_virtual_student(
    callback: CallbackQuery,
    state: FSMContext,
    students_service: StudentsService,
    profile_service: ProfileService,
) -> None:
    try:
        group_id = callback.data.split(":")[2]
    except IndexError:
        await _safe_callback_answer(
            callback,
            "Некорректная группа.",
            show_alert=True,
        )
        return

    data = await state.get_data()

    admin_user_id = data.get("virtual_student_admin_id")
    family_id = data.get("virtual_student_family_id")
    name = data.get("virtual_student_name")
    class_id = data.get("virtual_student_class_id")

    if (
        admin_user_id != callback.from_user.id
        or not family_id
        or not name
        or not class_id
    ):
        await state.clear()

        await _safe_callback_answer(
            callback,
            "Состояние добавления устарело.",
            show_alert=True,
        )
        return

    response = await students_service.create_virtual_student(
        admin_user_id=admin_user_id,
        family_id=family_id,
        name=name,
        class_id=class_id,
        group_id=group_id,
    )

    await state.clear()

    if not response.success:
        await _safe_callback_answer(
            callback,
            "Не удалось добавить ученика. "
            "Проверьте права администратора семьи.",
            show_alert=True,
        )
        return

    await _show_family_students_menu(
        callback=callback,
        profile_service=profile_service,
        students_service=students_service,
    )

    await _safe_callback_answer(
        callback,
        "✅ Ученик добавлен.",
    )
    
@router.callback_query(
    F.data.startswith("student:show:")
)
async def show_student_details(
    callback: CallbackQuery,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    try:
        student_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

    result = await students_service.get_student_for_adult(
        adult_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if result is None:
        await _safe_callback_answer(
            callback,
            "Ученик не найден или у вас нет доступа.",
            show_alert=True,
        )
        return

    student, access = result

    classes_dto = await schedule_service.get_classes_list()
    groups_dto = await schedule_service.get_groups_list()

    class_name = classes_dto.classes.get(
        student.class_id,
        student.class_id,
    )

    group_name = (
        "Весь класс"
        if student.group_id == "ALL"
        else groups_dto.groups.get(
            student.group_id,
            f"Группа {student.group_id}",
        )
    )

    text = UIRenderer.render_student_details(
        student=student,
        class_name=class_name,
        group_name=group_name,
    )

    keyboard = Keyboards.get_student_details_kb(
        student_id=student.id,
        telegram_user_id=student.telegram_user_id,
        is_family_admin=access.is_family_admin,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    F.data.startswith("student:delete:")
)
async def confirm_delete_virtual_student(
    callback: CallbackQuery,
    students_service: StudentsService,
) -> None:
    try:
        student_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

    result = await students_service.get_student_for_adult(
        adult_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if result is None:
        await _safe_callback_answer(
            callback,
            "Ученик не найден или у вас нет доступа.",
            show_alert=True,
        )
        return

    student, access = result

    if not access.is_family_admin:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может удалять учеников.",
            show_alert=True,
        )
        return

    if student.telegram_user_id is not None:
        await _safe_callback_answer(
            callback,
            "Нельзя удалить ученика с подключённым Telegram. "
            "Сначала потребуется отдельный flow отвязки профиля.",
            show_alert=True,
        )
        return

    text = UIRenderer.render_virtual_student_delete_confirmation(
        student,
    )

    keyboard = Keyboards.get_student_delete_confirmation_kb(
        student.id,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    F.data.startswith("student:delete_confirm:")
)
async def delete_virtual_student(
    callback: CallbackQuery,
    students_service: StudentsService,
    profile_service: ProfileService,
) -> None:
    try:
        student_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

    response = await students_service.delete_virtual_student(
        admin_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if not response.success:
        await _safe_callback_answer(
            callback,
            "Не удалось удалить ученика. "
            "Возможно, Telegram уже подключён или у вас нет прав.",
            show_alert=True,
        )
        return

    await _show_family_students_menu(
        callback=callback,
        profile_service=profile_service,
        students_service=students_service,
    )

    await _safe_callback_answer(
        callback,
        "🗑 Ученик удалён.",
    )