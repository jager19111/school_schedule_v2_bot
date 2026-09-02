import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from services.profiles_service import ProfileService
from core.repository.schedule_repository import ScheduleRepository
from core.models.dto import ClassListDTO
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards

logger = logging.getLogger(__name__)
router = Router()

@router.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message, profile_service: ProfileService):
    user_dto = await profile_service.get_user_profile_dto(message.from_user.id)
    if not user_dto or not user_dto.is_fully_registered:
        return await message.answer(UIRenderer.render_unregistered_error())
    
    text = UIRenderer.render_settings_menu()
    kb = Keyboards.get_settings_menu(user_dto)
    await message.answer(text, reply_markup=kb)

@router.callback_query(F.data == "settings:change_class")
async def change_class_start(callback: CallbackQuery, schedule_repo: ScheduleRepository):
    metadata = await schedule_repo.get_metadata()
    class_dto = ClassListDTO(classes={k: v.name for k, v in metadata.get('classes', {}).items()})
    
    text = UIRenderer.render_class_selection(class_dto)
    kb = Keyboards.get_class_selection(class_dto)
    await callback.message.edit_text(text, reply_markup=kb)