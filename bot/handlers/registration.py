import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from services.profiles import ProfileService
from core.repository.schedule_repository import ScheduleRepository

logger = logging.getLogger(__name__)
router = Router()

class RegistrationStates(StatesGroup):
    waiting_for_role = State()
    waiting_for_family_code = State()
    waiting_for_class = State()
    waiting_for_group = State()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, profile_service: ProfileService):
    """Начало регистрации и обновление активности[cite: 5, 7]."""
    await profile_service.update_last_active(message.from_user.id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👶 Ребёнок", callback_data="role:child")],
        [InlineKeyboardButton(text="👨‍👩‍👧 Родитель", callback_data="role:parent")],
        [InlineKeyboardButton(text="👁 Наблюдатель", callback_data="role:observer")]
    ])
    await message.answer("Добро пожаловать! Выберите вашу роль:", reply_markup=kb)
    await state.set_state(RegistrationStates.waiting_for_role)

@router.callback_query(RegistrationStates.waiting_for_role, F.data.startswith("role:"))
async def process_role(callback: CallbackQuery, state: FSMContext, schedule_repo: ScheduleRepository):
    role = callback.data.split(":")[1]
    await state.update_data(role=role)
    
    if role in ('parent', 'observer'):
        await callback.message.edit_text("Введите код семьи (family_code) для подключения:")
        await state.set_state(RegistrationStates.waiting_for_family_code)
    else:
        # Для ребёнка загружаем список всех доступных классов из NIKA[cite: 6, 7]
        metadata = await schedule_repo.get_metadata()
        classes = metadata.get('classes', {})
        
        buttons = []
        row = []
        for c_id, c_data in classes.items():
            row.append(InlineKeyboardButton(text=c_data.name, callback_data=f"class:{c_id}"))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
            
        await callback.message.edit_text("Выберите ваш класс:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await state.set_state(RegistrationStates.waiting_for_class)

@router.callback_query(RegistrationStates.waiting_for_class, F.data.startswith("class:"))
async def process_class(callback: CallbackQuery, state: FSMContext, schedule_repo: ScheduleRepository):
    class_id = callback.data.split(":")[1]
    await state.update_data(class_id=class_id)
    
    # Загружаем группы из метаданных[cite: 5]
    metadata = await schedule_repo.get_metadata()
    groups = metadata.get('groups', {})
    
    buttons = [[InlineKeyboardButton(text="Весь класс (без групп)", callback_data="group:ALL")]]
    for g_id, g_name in groups.items():
        buttons.append([InlineKeyboardButton(text=g_name, callback_data=f"group:{g_id}")])
        
    await callback.message.edit_text("Выберите вашу группу (или 'Весь класс'):", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(RegistrationStates.waiting_for_group)

@router.callback_query(RegistrationStates.waiting_for_group, F.data.startswith("group:"))
async def process_group(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService):
    group_id = callback.data.split(":")[1]
    data = await state.get_data()
    user_id = callback.from_user.id
    
    # Сохраняем профиль в БД[cite: 7]
    await profile_service.create_or_update_user(
        user_id=user_id, 
        role=data['role'], 
        class_id=data['class_id'], 
        group_id=group_id
    )
    
    await callback.message.edit_text("✅ Регистрация успешно завершена! Расписание доступно через меню.")
    await state.clear()