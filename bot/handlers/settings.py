import logging
import contextlib
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from services.profiles_service import ProfileService
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from core.models.dto import ChildrenListDTO


from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from services.time_service import TimeService
from services.schedule_service import ScheduleService
from bot.handlers.registration import RegistrationStates




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
async def process_restart(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService):
    await profile_service.reset_user_profile(callback.from_user.id)
    await state.clear()
    await callback.message.edit_text("🔄 Профиль сброшен. Отправьте /start для новой регистрации.")
    await callback.answer()
    
# ================= 3. УПРАВЛЕНИЕ СЕМЬЕЙ =================

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

    # Получаем полный состав семьи
    family_members = await profile_service.get_family_members(user_dto.family_id)
    class_dto = await schedule_service.get_classes_list()
    
    text = UIRenderer.render_family_members_menu(family_members, user_dto, class_dto.classes)
    kb = Keyboards.get_family_management_kb(family_members, user_dto, class_dto.classes)
    
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
