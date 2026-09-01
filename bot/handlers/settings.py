import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from services.profiles import ProfileService
from core.repository.schedule_repository import ScheduleRepository

logger = logging.getLogger(__name__)
router = Router()

@router.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message, profile_service: ProfileService):
    user = await profile_service.get_user_profile(message.from_user.id)
    if not user:
        return await message.answer("Сначала пройдите регистрацию (/start).")
    
    kb_lines = [
        [InlineKeyboardButton(text="🎓 Сменить класс", callback_data="settings:change_class")],
        [InlineKeyboardButton(text="📚 Сменить группу", callback_data="settings:change_group")]
    ]
    
    # Блокировка настроек уведомлений для ребенка, если включен родительский контроль[cite: 7]
    if not (user['role'] == 'child' and user['parent_control_notifications'] == 1):
        kb_lines.append([InlineKeyboardButton(text="🔔 Настройки уведомлений", callback_data="settings:notifications")])
        
    await message.answer("⚙️ Меню настроек:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_lines))

@router.callback_query(F.data == "settings:change_class")
async def change_class_start(callback: CallbackQuery, schedule_repo: ScheduleRepository):
    # Динамическая подгрузка классов из базы/парсера без хардкода[cite: 7]
    metadata = await schedule_repo.get_metadata()
    classes = metadata.get('classes', {})
    
    buttons = []
    row = []
    for c_id, c_data in classes.items():
        row.append(InlineKeyboardButton(text=c_data.name, callback_data=f"set_class:{c_id}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    
    await callback.message.edit_text("Выберите новый класс:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))