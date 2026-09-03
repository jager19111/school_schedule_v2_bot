import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from services.profiles_service import ProfileService
from core.repository.schedule_repository import ScheduleRepository
from services.schedule_service import ScheduleService
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from core.models.dto import ClassListDTO, GroupListDTO, FamilyCreatedDTO

logger = logging.getLogger(__name__)
router = Router()

class RegistrationStates(StatesGroup):
    waiting_for_role = State()
    waiting_for_name = State()
    waiting_for_family_action = State()
    waiting_for_family_code = State()
    waiting_for_class = State()
    waiting_for_group = State()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, profile_service: ProfileService):
    await profile_service.register_user_initial(message.from_user.id)
    
    user_dto = await profile_service.get_user_profile_dto(message.from_user.id)
    
    if user_dto.is_fully_registered:
        text = UIRenderer.render_already_registered(user_dto.name)
        kb = Keyboards.get_main_menu()
        await message.answer(text, reply_markup=kb)
        await state.clear()
        return
        
    text = UIRenderer.render_role_selection()
    kb = Keyboards.get_role_selection()
    await message.answer(text, reply_markup=kb)
    await state.set_state(RegistrationStates.waiting_for_role)

@router.callback_query(RegistrationStates.waiting_for_role, F.data.startswith("role:"))
async def process_role(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService):
    role = callback.data.split(":")[1]
    await state.update_data(role=role)
    await profile_service.update_user_role(callback.from_user.id, role)
    
    text = UIRenderer.render_name_prompt()
    await callback.message.edit_text(text)
    await state.set_state(RegistrationStates.waiting_for_name)

@router.message(RegistrationStates.waiting_for_name)
async def process_name(message: Message, state: FSMContext, profile_service: ProfileService):
    name = message.text.strip()
    await profile_service.update_user_name(message.from_user.id, name)
    
    data = await state.get_data()
    role = data.get('role')
    
    if role == 'parent':
        text = UIRenderer.render_parent_family_action()
        kb = Keyboards.get_parent_family_action()
        await message.answer(text, reply_markup=kb)
        await state.set_state(RegistrationStates.waiting_for_family_action)
        
    elif role == 'child':
        text = UIRenderer.render_child_family_action()
        kb = Keyboards.get_child_family_action()
        await message.answer(text, reply_markup=kb)
        await state.set_state(RegistrationStates.waiting_for_family_action)
        
    elif role == 'observer':
        text = UIRenderer.render_family_code_prompt()
        await message.answer(text)
        await state.set_state(RegistrationStates.waiting_for_family_code)

@router.callback_query(RegistrationStates.waiting_for_family_action, F.data == "family:create")
async def process_family_create(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService):
    user_id = callback.from_user.id
    family_code = await profile_service.create_family_and_link(admin_user_id=user_id)
    dto = FamilyCreatedDTO(family_code=family_code)
    
    # Получаем DTO, чтобы вытащить имя
    user_dto = await profile_service.get_user_profile_dto(user_id)
    
    text = UIRenderer.render_family_created(dto, user_dto.name)
    await callback.message.edit_text(text, parse_mode="HTML")
    await state.clear()

@router.callback_query(RegistrationStates.waiting_for_family_action, F.data == "family:join")
async def process_family_join_btn(callback: CallbackQuery, state: FSMContext):
    text = UIRenderer.render_family_code_prompt()
    await callback.message.edit_text(text)
    await state.set_state(RegistrationStates.waiting_for_family_code)

@router.callback_query(RegistrationStates.waiting_for_family_action, F.data == "family:skip")
async def process_family_skip_btn(callback: CallbackQuery, state: FSMContext, schedule_service: ScheduleService):
    class_dto = await schedule_service.get_classes_list()
    
    text = UIRenderer.render_class_selection(class_dto)
    kb = Keyboards.get_class_selection(class_dto)
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(RegistrationStates.waiting_for_class)

@router.message(RegistrationStates.waiting_for_family_code)
async def process_family_code_input(message: Message, state: FSMContext, profile_service: ProfileService, schedule_service: ScheduleService):
    code = message.text.strip().upper()
    data = await state.get_data()
    role = data.get('role', 'parent')
    user_id = message.from_user.id
    
    success = await profile_service.link_child_to_parent(user_id=user_id, family_code=code, role=role)
    
    if not success:
        text = UIRenderer.render_error_join()
        return await message.answer(text)

    # Получаем DTO для имени
    user_dto = await profile_service.get_user_profile_dto(user_id)

    if role == 'child':
        text_success = UIRenderer.render_success_join(user_dto.name)
        await message.answer(text_success, parse_mode="HTML")
        
        class_dto = await schedule_service.get_classes_list()
        
        text = UIRenderer.render_class_selection(class_dto)
        kb = Keyboards.get_class_selection(class_dto)
        await message.answer(text, reply_markup=kb)
        await state.set_state(RegistrationStates.waiting_for_class)
    else:
        text = UIRenderer.render_success_join(user_dto.name)
        menu_text = UIRenderer.render_main_menu()
        menu_kb = Keyboards.get_main_menu()
        
        await message.answer(text, parse_mode="HTML")
        await message.answer(menu_text, reply_markup=menu_kb)
        await state.clear()

@router.callback_query(RegistrationStates.waiting_for_class, F.data.startswith("class:"))
async def process_class(callback: CallbackQuery, state: FSMContext, schedule_service: ScheduleService):
    class_id = callback.data.split(":")[1]
    await state.update_data(class_id=class_id)
    
    group_dto = await schedule_service.get_groups_list()
    
    text = UIRenderer.render_group_selection()
    kb = Keyboards.get_group_selection(group_dto)
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(RegistrationStates.waiting_for_group)

@router.callback_query(RegistrationStates.waiting_for_group, F.data.startswith("group:"))
async def process_group(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService):
    group_id = callback.data.split(":")[1]
    data = await state.get_data()
    user_id = callback.from_user.id
    
    await profile_service.set_child_class_and_group(user_id, data['class_id'], group_id)
    
    user_dto = await profile_service.get_user_profile_dto(user_id)
    
    text = UIRenderer.render_final_success(user_dto.name)
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="HTML")
    
    menu_text = UIRenderer.render_main_menu()
    menu_kb = Keyboards.get_main_menu()
    await callback.message.answer(menu_text, reply_markup=menu_kb)
    await state.clear()