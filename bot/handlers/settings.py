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
async def show_family_management(callback: CallbackQuery, profile_service: ProfileService, schedule_service: ScheduleService):
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    
    # Жесткая изоляция: ребенок не управляет семьей
    if user_dto.role == "child":
        text = UIRenderer.render_family_management_error()
        kb = Keyboards.get_settings_main_kb(user_dto)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        return await callback.answer()

    children_dtos = await profile_service.get_children_for_parent(callback.from_user.id)
    list_dto = ChildrenListDTO(children=children_dtos, action="settings")
    
    # Запрашиваем классы для расшифровки ID (например, 016 -> 6а)
    class_dto = await schedule_service.get_classes_list()
    
    text = UIRenderer.render_family_management_menu()
    kb = Keyboards.get_family_management_kb(list_dto, class_dto.classes)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("family:child_settings:"))
async def show_child_settings(callback: CallbackQuery, profile_service: ProfileService):
    child_user_id = int(callback.data.split(":")[2])
    child_dto = await profile_service.get_user_profile_dto(child_user_id)
    
    text = UIRenderer.render_child_settings_menu(child_dto.name, child_dto.class_id)
    kb = Keyboards.get_child_settings_kb(child_dto)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# ================= 4. ПЕРЕКЛЮЧАТЕЛИ (TOGGLES) =================

@router.callback_query(F.data.startswith("child_set:notif:"))
async def toggle_child_notifications(callback: CallbackQuery, profile_service: ProfileService):
    child_user_id = int(callback.data.split(":")[2])
    await profile_service.toggle_user_flag(child_user_id, "is_notifications_enabled")
    await _refresh_child_settings(callback, child_user_id, profile_service)

@router.callback_query(F.data.startswith("child_set:parent_notif:"))
async def toggle_parent_notif(callback: CallbackQuery, profile_service: ProfileService):
    child_user_id = int(callback.data.split(":")[2])
    await profile_service.toggle_user_flag(child_user_id, "notify_parent_about_me")
    await _refresh_child_settings(callback, child_user_id, profile_service)

@router.callback_query(F.data.startswith("child_set:lock:"))
async def toggle_child_lock(callback: CallbackQuery, profile_service: ProfileService):
    child_user_id = int(callback.data.split(":")[2])
    await profile_service.toggle_user_flag(child_user_id, "parent_control_notifications")
    await _refresh_child_settings(callback, child_user_id, profile_service)

async def _refresh_child_settings(callback: CallbackQuery, child_user_id: int, profile_service: ProfileService):
    """Вспомогательный метод для обновления экрана после переключения флага."""
    child_dto = await profile_service.get_user_profile_dto(child_user_id)
    text = UIRenderer.render_child_settings_menu(child_dto.name, child_dto.class_id)
    kb = Keyboards.get_child_settings_kb(child_dto)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# Настройки самого родителя
@router.callback_query(F.data == "settings:my_notifications")
async def toggle_my_notifications(callback: CallbackQuery, profile_service: ProfileService):
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    
    # Блокировка: если это ребенок и родитель включил контроль
    if user_dto.role == "child" and user_dto.parent_control_notifications:
        return await callback.answer("🔒 Ваши настройки уведомлений заблокированы родителем.", show_alert=True)
    await profile_service.toggle_user_flag(callback.from_user.id, "is_notifications_enabled")
    await settings_main_menu_cb(callback, profile_service)
    
    
    # ================= 5. ВВОД ВРЕМЕНИ СВОДКИ (FSM) =================

@router.callback_query(F.data == "settings:my_summary_time")
async def prompt_my_summary_time(callback: CallbackQuery, state: FSMContext):
    text = UIRenderer.render_summary_time_prompt()
    kb = Keyboards.get_summary_time_prompt_kb()
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(SettingsStates.waiting_for_my_time)
    await callback.answer()

@router.callback_query(F.data.startswith("child_set:time:"))
async def prompt_child_summary_time(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService):
    child_id = int(callback.data.split(":")[2])
    await state.update_data(child_id=child_id)
    
    # Получаем DTO, чтобы отобразить имя ребенка в тексте
    child_dto = await profile_service.get_user_profile_dto(child_id)

    text = UIRenderer.render_summary_time_prompt(child_dto.name)
    kb = Keyboards.get_summary_time_prompt_kb()
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(SettingsStates.waiting_for_child_time)
    await callback.answer()

@router.message(SettingsStates.waiting_for_my_time)
async def process_my_time(callback: CallbackQuery, message: Message, state: FSMContext, time_service: TimeService, profile_service: ProfileService, schedule_service: ScheduleService):
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    
    # Блокировка: если это ребенок и родитель включил контроль
    if user_dto.role == "child" and user_dto.parent_control_notifications:
        return await callback.answer("🔒 Ваши настройки уведомлений заблокированы родителем.", show_alert=True)
    # Умная нормализация ввода (понимает "715", "7.15", "07:15")
    norm_time = time_service.normalize_time(message.text)
    
    if not norm_time:
        text = UIRenderer.render_invalid_time_format()
        kb = Keyboards.get_summary_time_prompt_kb()
        return await message.answer(text, reply_markup=kb, parse_mode="HTML")

    await profile_service.update_morning_summary_time(message.from_user.id, norm_time)
    await state.clear()
    
    # Возвращаем пользователя в главное меню настроек
    await _show_settings_menu(message, message.from_user.id, profile_service, schedule_service, is_callback=False)

@router.message(SettingsStates.waiting_for_child_time)
async def process_child_time(message: Message, state: FSMContext, time_service: TimeService, profile_service: ProfileService):
    norm_time = time_service.normalize_time(message.text)
    
    if not norm_time:
        text = UIRenderer.render_invalid_time_format()
        kb = Keyboards.get_summary_time_prompt_kb()
        return await message.answer(text, reply_markup=kb, parse_mode="HTML")

    data = await state.get_data()
    child_id = data["child_id"]
    
    await profile_service.update_morning_summary_time(child_id, norm_time)
    await state.clear()
    
    # Возвращаем пользователя в меню настроек конкретного ребенка.
    # Так как мы в Message (а не CallbackQuery), отправим новое сообщение, 
    # использовав хак с созданием фейкового CallbackQuery или продублировав логику.
    # Для чистоты просто вызовем отрисовку нового сообщения:
    child_dto = await profile_service.get_user_profile_dto(child_id)
    text = UIRenderer.render_child_settings_menu(child_dto.name, child_dto.class_id)
    kb = Keyboards.get_child_settings_kb(child_dto)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

# Отключение сводки и Отмена ввода
@router.callback_query(F.data == "set_time:off")
async def turn_off_summary_time(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService, schedule_service: ScheduleService):
    current_state = await state.get_state()
    
    if current_state == SettingsStates.waiting_for_child_time.state:
        data = await state.get_data()
        child_id = data["child_id"]
        await profile_service.update_morning_summary_time(child_id, None)
        await state.clear()
        await _refresh_child_settings(callback, child_id, profile_service)
    else:
        await profile_service.update_morning_summary_time(callback.from_user.id, None)
        await state.clear()
        await settings_main_menu_cb(callback, profile_service, schedule_service)

@router.callback_query(F.data == "settings:cancel_input")
async def cancel_time_input(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService):
    current_state = await state.get_state()
    is_child_state = current_state == SettingsStates.waiting_for_child_time.state
    data = await state.get_data()
    await state.clear()

    if is_child_state and "child_id" in data:
        await _refresh_child_settings(callback, data["child_id"], profile_service)
    else:
        await settings_main_menu_cb(callback, profile_service)
        
        
# ================= НАСТРОЙКИ УВЕДОМЛЕНИЙ =================
@router.callback_query(F.data == "settings:notifications")
async def show_notifications_menu(callback: CallbackQuery, profile_service: ProfileService):
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    text = UIRenderer.render_notifications_menu()
    kb = Keyboards.get_notifications_kb(user_dto)

# Глушим ошибку TelegramBadRequest, если меню не изменилось 
    # (например, при быстром двойном клике)
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        
    await callback.answer()
    
@router.callback_query(F.data == "set_notif:changes")
async def toggle_changes_notif(callback: CallbackQuery, profile_service: ProfileService):

    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    if user_dto.role == "child" and user_dto.parent_control_notifications:
        return await callback.answer("🔒 Ваши настройки заблокированы родителем.", show_alert=True)
    
    await profile_service.toggle_user_flag(callback.from_user.id, "is_notifications_enabled")
    await show_notifications_menu(callback, profile_service)

@router.callback_query(F.data == "set_notif:prelesson")
async def toggle_prelesson_notif(callback: CallbackQuery, profile_service: ProfileService):

    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    if user_dto.role == "child" and user_dto.parent_control_notifications:
        return await callback.answer("🔒 Ваши настройки заблокированы родителем.", show_alert=True)
    
    # Переключаем между 0 (ВЫКЛ) и 10 (ВКЛ)
    new_val = 0 if user_dto.pre_lesson_offset_minutes > 0 else 10
    await profile_service.update_integer_setting(callback.from_user.id, "pre_lesson_offset_minutes", new_val)
    await show_notifications_menu(callback, profile_service)

@router.callback_query(F.data == "set_notif:extra")
async def toggle_extra_notif(callback: CallbackQuery, profile_service: ProfileService):
    # Добавь этот блок в самое начало хендлеров toggle_changes_notif, toggle_prelesson_notif и toggle_extra_notif:
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    if user_dto.role == "child" and user_dto.parent_control_notifications:
        return await callback.answer("🔒 Ваши настройки заблокированы родителем.", show_alert=True)
    # Переключаем между 0 (ВЫКЛ) и 30 (ВКЛ)
    new_val = 0 if user_dto.global_extra_reminder > 0 else 30
    await profile_service.update_integer_setting(callback.from_user.id, "global_extra_reminder", new_val)
    await show_notifications_menu(callback, profile_service)
    
    

# ================= 5. СМЕНА КЛАССА И ГРУППЫ =================
   
    
@router.callback_query(F.data == "settings:change_class")
async def settings_change_class(callback: CallbackQuery, state: FSMContext, schedule_service: ScheduleService):
    """Смена класса для ребенка-одиночки."""
    class_dto = await schedule_service.get_classes_list()
    
    text = UIRenderer.render_class_selection(class_dto)
    kb = Keyboards.get_class_selection(class_dto)
    
    # НОВОЕ: Устанавливаем флаг, что это редактирование из настроек, а не новая регистрация
    await state.update_data(is_settings_edit=True)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(RegistrationStates.waiting_for_class)
    await callback.answer()

@router.callback_query(F.data.startswith("child_set:class:"))
async def child_settings_change_class(callback: CallbackQuery, state: FSMContext, schedule_service: ScheduleService):
    """Смена класса для ребенка через меню родителя."""
    child_id = int(callback.data.split(":")[2])
    
    # Сохраняем ID ребенка, которого редактируем, чтобы RegistrationStates знал, кому менять класс
    await state.update_data(editing_child_id=child_id)
    
    class_dto = await schedule_service.get_classes_list()
    
    text = UIRenderer.render_class_selection(class_dto)
    kb = Keyboards.get_class_selection(class_dto)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(RegistrationStates.waiting_for_class)
    await callback.answer()