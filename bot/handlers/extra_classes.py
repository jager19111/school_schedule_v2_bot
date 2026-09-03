import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from services.time_service import TimeService
from services.extra_classes_service import ExtraClassesService
from services.profiles_service import ProfileService

logger = logging.getLogger(__name__)
router = Router()

class ExtraClassStates(StatesGroup):
    waiting_for_day = State()
    waiting_for_time_start = State()
    waiting_for_time_end = State()
    waiting_for_title = State()
    waiting_for_location = State()
    waiting_for_reminder = State()
    waiting_for_delete_id = State()
    waiting_for_edit_id = State()
    waiting_for_edit_value = State()
    waiting_for_edit_time_end = State()

# === ГЛАВНОЕ МЕНЮ И УМНАЯ МАРШРУТИЗАЦИЯ ===

@router.message(F.text == "➕ Доп. занятия")
async def show_extra_menu(message: Message, profile_service: ProfileService):
    user_dto = await profile_service.get_user_profile_dto(message.from_user.id)
    
    # 1. Логика маршрутизации: Ребенок или Родитель
    if user_dto.role == "child":
        target_id = message.from_user.id
        can_edit = getattr(user_dto, 'can_edit_extra_classes', True)
    else:
        children = await profile_service.get_children_for_parent(message.from_user.id)
        if not children:
            text, _ = UIRenderer.render_extra_no_children()
            return await message.answer(text, parse_mode="HTML")
        elif len(children) == 1:
            target_id = children[0].user_id
            can_edit = True # Родитель всегда может редактировать
        else:
            text, _ = UIRenderer.render_extra_child_select()
            return await message.answer(text, reply_markup=Keyboards.get_extra_children_select_kb(children), parse_mode="HTML")

    text, _ = UIRenderer.render_extra_classes_menu()
    await message.answer(text, reply_markup=Keyboards.get_extra_classes_menu(target_id, can_edit), parse_mode="HTML")

@router.callback_query(F.data.startswith("extra:menu:"))
async def show_extra_menu_cb(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService):
    await state.clear()
    target_id = int(callback.data.split(":")[2])
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    
    can_edit = True if user_dto.role != "child" else getattr(user_dto, 'can_edit_extra_classes', True)
    
    text, _ = UIRenderer.render_extra_classes_menu()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_extra_classes_menu(target_id, can_edit), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "extra:cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService):
    # Умная отмена: берем ID из state или откатываемся к своему
    data = await state.get_data()
    target_id = data.get("target_user_id", callback.from_user.id)
    await state.clear()
    
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    can_edit = True if user_dto.role != "child" else getattr(user_dto, 'can_edit_extra_classes', True)
    
    text, _ = UIRenderer.render_extra_classes_menu()
    await callback.message.edit_text(f"❌ Действие отменено.\n\n{text}", reply_markup=Keyboards.get_extra_classes_menu(target_id, can_edit), parse_mode="HTML")
    await callback.answer()


# === СПИСОК И УДАЛЕНИЕ ===

@router.callback_query(F.data.startswith("extra:list:"))
async def show_extra_list(callback: CallbackQuery, extra_classes_service: ExtraClassesService):
    target_id = int(callback.data.split(":")[2])
    dto_list = await extra_classes_service.get_user_extra_classes(target_id)
    
    text, _ = UIRenderer.render_extra_classes_list(dto_list)
    await callback.message.edit_text(text, reply_markup=Keyboards.get_back_to_extra_menu(target_id), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("extra:delete:"))
async def start_delete_extra(callback: CallbackQuery, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    target_id = int(callback.data.split(":")[2])
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    
    if user_dto.role == "child" and not getattr(user_dto, 'can_edit_extra_classes', True):
        return await callback.answer(UIRenderer.render_extra_class_locked(), show_alert=True)
        
    dto_list = await extra_classes_service.get_user_extra_classes(target_id)
    
    if not dto_list.items:
        text, _ = UIRenderer.render_extra_class_delete_prompt(dto_list)
        return await callback.message.edit_text(text, reply_markup=Keyboards.get_back_to_extra_menu(target_id), parse_mode="HTML")

    # Сохраняем target_id в State для обработки удаления
    await state.update_data(target_user_id=target_id)
    text, _ = UIRenderer.render_extra_class_delete_prompt(dto_list)
    await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_delete_id)
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_delete_id)
async def process_delete_id(message: Message, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    data = await state.get_data()
    target_id = data["target_user_id"] # Берем ID ребенка!
    
    if not message.text.strip().isdigit():
        text, _ = UIRenderer.render_extra_class_not_found()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")

    class_id = int(message.text.strip())
    response = await extra_classes_service.delete_extra_class(user_id=target_id, extra_id=class_id)

    if not response.success:
        text, _ = UIRenderer.render_extra_class_not_found()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")

    await state.clear()
    
    user_dto = await profile_service.get_user_profile_dto(message.from_user.id)
    can_edit = True if user_dto.role != "child" else getattr(user_dto, 'can_edit_extra_classes', True)
    
    text_deleted, _ = UIRenderer.render_extra_class_deleted()
    text_menu, _ = UIRenderer.render_extra_classes_menu()
    await message.answer(f"{text_deleted}\n\n{text_menu}", reply_markup=Keyboards.get_extra_classes_menu(target_id, can_edit), parse_mode="HTML")


# === ДОБАВЛЕНИЕ ЗАНЯТИЯ ===

@router.callback_query(F.data.startswith("extra:add:"))
async def start_add_extra(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split(":")[2])
    await state.update_data(target_user_id=target_id) # Запомнили, кому добавляем
    
    text, _ = UIRenderer.render_extra_class_day()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_day_selection_kb())
    await state.set_state(ExtraClassStates.waiting_for_day)
    await callback.answer()

@router.callback_query(ExtraClassStates.waiting_for_day, F.data.startswith("extraday:"))
async def process_day(callback: CallbackQuery, state: FSMContext):
    day_num = int(callback.data.split(":")[1])
    await state.update_data(day_of_week=day_num)
    
    text, _ = UIRenderer.render_extra_class_time_start()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard())
    await state.set_state(ExtraClassStates.waiting_for_time_start)
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_time_start)
async def process_time_start(message: Message, state: FSMContext, time_service: TimeService):
    """Шаг 3: Умная нормализация времени начала."""
    # Используем умный нормализатор вместо строгой проверки
    norm_time = time_service.normalize_time(message.text)
    if not norm_time:
        text, _ = UIRenderer.render_extra_class_invalid_time()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    await state.update_data(time_start=norm_time)
    text, _ = UIRenderer.render_extra_class_time_end()
    await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_time_end)

@router.message(ExtraClassStates.waiting_for_time_end)
async def process_time_end(message: Message, state: FSMContext, time_service: TimeService):
    norm_time = time_service.normalize_time(message.text)
    data = await state.get_data()
    
    if not norm_time:
        text, _ = UIRenderer.render_extra_class_invalid_time()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    if not time_service.validate_time_range(data["time_start"], norm_time):
        text, _ = UIRenderer.render_extra_class_invalid_range()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    await state.update_data(time_end=norm_time)
    text, _ = UIRenderer.render_extra_class_title()
    await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_title)

@router.message(ExtraClassStates.waiting_for_title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    text, _ = UIRenderer.render_extra_class_location()
    await message.answer(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_location"), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_location)

@router.callback_query(ExtraClassStates.waiting_for_location, F.data == "skip_location")
async def skip_location(callback: CallbackQuery, state: FSMContext):
    await state.update_data(location=None)
    text, _ = UIRenderer.render_extra_class_reminder()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_reminder"), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_reminder)
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_location)
async def process_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text.strip())
    text, _ = UIRenderer.render_extra_class_reminder()
    await message.answer(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_reminder"), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_reminder)

@router.callback_query(ExtraClassStates.waiting_for_reminder, F.data == "skip_reminder")
async def skip_reminder(callback: CallbackQuery, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    await finalize_extra_class(callback, state, extra_classes_service, profile_service, reminder_minutes=30)
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_reminder)
async def process_reminder(message: Message, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    reminder_text = message.text.strip()
    if not reminder_text.isdigit():
        text, _ = UIRenderer.render_extra_class_invalid_reminder()
        return await message.answer(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_reminder"), parse_mode="HTML")
        
    await finalize_extra_class(message, state, extra_classes_service, profile_service, reminder_minutes=int(reminder_text))

async def finalize_extra_class(event, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService, reminder_minutes: int):
    data = await state.get_data()
    target_id = data["target_user_id"] # Записываем на ребенка
    
    profile_dto = await profile_service.get_user_profile_dto(target_id) 

    response = await extra_classes_service.add_extra_class(
        user_id=target_id,
        family_id=profile_dto.family_id,
        day_of_week=data["day_of_week"],
        time_start=data["time_start"],
        time_end=data["time_end"],
        title=data["title"],
        location=data.get("location"),
        reminder_minutes=reminder_minutes
    )

    is_callback = isinstance(event, CallbackQuery)
    msg_func = event.message.edit_text if is_callback else event.answer

    if not response.success:
        text, _ = UIRenderer.render_extra_class_error()
        return await msg_func(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")

    await state.clear()
    
    # Возврат к меню с правильными правами
    current_user_dto = await profile_service.get_user_profile_dto(event.from_user.id)
    can_edit = True if current_user_dto.role != "child" else getattr(current_user_dto, 'can_edit_extra_classes', True)
    
    text_success, _ = UIRenderer.render_extra_class_success()
    text_menu, _ = UIRenderer.render_extra_classes_menu()
    await msg_func(f"{text_success}\n\n{text_menu}", reply_markup=Keyboards.get_extra_classes_menu(target_id, can_edit), parse_mode="HTML")


# === ИЗМЕНЕНИЕ ЗАНЯТИЯ ===

@router.callback_query(F.data.startswith("extra:edit:"))
async def start_edit_extra(callback: CallbackQuery, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    target_id = int(callback.data.split(":")[2])
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    
    if user_dto.role == "child" and not getattr(user_dto, 'can_edit_extra_classes', True):
        return await callback.answer("🔒 Редактирование занятий запрещено родителем.", show_alert=True)

    dto_list = await extra_classes_service.get_user_extra_classes(target_id)
    
    if not dto_list.items:
        text, _ = UIRenderer.render_extra_class_edit_prompt(dto_list)
        return await callback.message.edit_text(text, reply_markup=Keyboards.get_back_to_extra_menu(target_id), parse_mode="HTML")

    await state.update_data(target_user_id=target_id)
    text, _ = UIRenderer.render_extra_class_edit_prompt(dto_list)
    await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_edit_id)
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_edit_id)
async def process_edit_id(message: Message, state: FSMContext, extra_classes_service: ExtraClassesService):
    data = await state.get_data()
    target_id = data["target_user_id"]
    
    if not message.text.strip().isdigit():
        text, _ = UIRenderer.render_extra_class_not_found()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")

    class_id = int(message.text.strip())
    
    dto_list = await extra_classes_service.get_user_extra_classes(target_id)
    if not any(item.id == class_id for item in dto_list.items):
        text, _ = UIRenderer.render_extra_class_not_found()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")

    await state.update_data(edit_id=class_id)
    text, _ = UIRenderer.render_extra_class_edit_field_select()
    await message.answer(text, reply_markup=Keyboards.get_extra_edit_fields_kb(class_id), parse_mode="HTML")

@router.callback_query(F.data.startswith("edit_ext:"))
async def choose_edit_field(callback: CallbackQuery, state: FSMContext):
    _, field, class_id = callback.data.split(":")
    await state.update_data(edit_field=field)
    
    if field == "time":
        text, _ = UIRenderer.render_extra_class_time_start()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        await state.set_state(ExtraClassStates.waiting_for_edit_value)
    elif field == "loc":
        text, _ = UIRenderer.render_extra_class_location()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_location"), parse_mode="HTML")
        await state.set_state(ExtraClassStates.waiting_for_edit_value)
    elif field == "rem":
        text, _ = UIRenderer.render_extra_class_reminder()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        await state.set_state(ExtraClassStates.waiting_for_edit_value)
    elif field == "day":
        text, _ = UIRenderer.render_extra_class_edit_day()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_day_selection_kb(), parse_mode="HTML")
        await state.set_state(ExtraClassStates.waiting_for_edit_value)
    else:
        text, _ = UIRenderer.render_extra_class_title()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        await state.set_state(ExtraClassStates.waiting_for_edit_value)
    await callback.answer()

@router.callback_query(ExtraClassStates.waiting_for_edit_value, F.data.startswith("extraday:"))
async def process_edit_day(callback: CallbackQuery, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    day_num = int(callback.data.split(":")[1])
    data = await state.get_data()
    target_id = data["target_user_id"]
    class_id = data["edit_id"]

    await extra_classes_service.update_extra_class(user_id=target_id, extra_id=class_id, day_of_week=day_num)
    await state.clear()
    
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    can_edit = True if user_dto.role != "child" else getattr(user_dto, 'can_edit_extra_classes', True)
    
    text_updated, _ = UIRenderer.render_extra_class_updated()
    text_menu, _ = UIRenderer.render_extra_classes_menu()
    await callback.message.edit_text(f"{text_updated}\n\n{text_menu}", reply_markup=Keyboards.get_extra_classes_menu(target_id, can_edit), parse_mode="HTML")
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_edit_value)
async def process_edit_value(message: Message, state: FSMContext, time_service: TimeService, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    data = await state.get_data()
    field = data["edit_field"]
    class_id = data["edit_id"]
    target_id = data["target_user_id"]
    val = message.text.strip()
    kwargs = {}
    
    if field == "time":
        norm_time = time_service.normalize_time(val)
        if not norm_time:
            text, _ = UIRenderer.render_extra_class_invalid_time()
            return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())
        await state.update_data(time_start=norm_time)
        text, _ = UIRenderer.render_extra_class_time_end()
        await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        return await state.set_state(ExtraClassStates.waiting_for_edit_time_end)
        
    elif field == "rem":
        if not val.isdigit():
            text, _ = UIRenderer.render_extra_class_invalid_reminder()
            return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        kwargs["reminder_minutes"] = int(val)
    elif field == "loc":
        kwargs["location"] = val
    else:
        kwargs["title"] = val

    await extra_classes_service.update_extra_class(user_id=target_id, extra_id=class_id, **kwargs)
    await state.clear()
    
    user_dto = await profile_service.get_user_profile_dto(message.from_user.id)
    can_edit = True if user_dto.role != "child" else getattr(user_dto, 'can_edit_extra_classes', True)
    
    text_updated, _ = UIRenderer.render_extra_class_updated()
    text_menu, _ = UIRenderer.render_extra_classes_menu()
    await message.answer(f"{text_updated}\n\n{text_menu}", reply_markup=Keyboards.get_extra_classes_menu(target_id, can_edit), parse_mode="HTML")

@router.message(ExtraClassStates.waiting_for_edit_time_end)
async def process_edit_time_end(message: Message, state: FSMContext, time_service: TimeService, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    data = await state.get_data()
    target_id = data["target_user_id"]
    norm_time = time_service.normalize_time(message.text)
    
    if not norm_time:
        text, _ = UIRenderer.render_extra_class_invalid_time()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())
        
    if not time_service.validate_time_range(data["time_start"], norm_time):
        text, _ = UIRenderer.render_extra_class_invalid_range()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    await extra_classes_service.update_extra_class(
        user_id=target_id, 
        extra_id=data["edit_id"], 
        time_start=data["time_start"], 
        time_end=norm_time
    )
    
    await state.clear()
    user_dto = await profile_service.get_user_profile_dto(message.from_user.id)
    can_edit = True if user_dto.role != "child" else getattr(user_dto, 'can_edit_extra_classes', True)
    
    text_updated, _ = UIRenderer.render_extra_class_updated()
    text_menu, _ = UIRenderer.render_extra_classes_menu()
    await message.answer(f"{text_updated}\n\n{text_menu}", reply_markup=Keyboards.get_extra_classes_menu(target_id, can_edit), parse_mode="HTML")