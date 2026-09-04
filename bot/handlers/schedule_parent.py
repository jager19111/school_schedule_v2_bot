import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.time_service import TimeService
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from core.models.dto import ChildrenListDTO

logger = logging.getLogger(__name__)
router = Router()

@router.message(F.text == "👨‍👩‍👧 Расписание детей")
async def parent_schedule_menu(message: Message, profile_service: ProfileService):
    """Точка входа для родителей: выбор ребенка из списка."""
    user_dto = await profile_service.get_user_profile_dto(message.from_user.id)
    if not user_dto or user_dto.role not in ('parent', 'observer'):
        return await message.answer(UIRenderer.render_access_denied())
        
    children_dtos = await profile_service.get_children_for_parent(message.from_user.id)
    if not children_dtos:
        return await message.answer("У вас нет привязанных детей. Добавьте ребенка через меню 'Настройки' -> 'Управление семьей'.")
        
    list_dto = ChildrenListDTO(children=children_dtos, action="sched")
    
    text, kb = UIRenderer.render_parent_children_menu(list_dto)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("p_sched:"))
async def show_child_schedule_today(
    callback: CallbackQuery, 
    profile_service: ProfileService, 
    schedule_service: ScheduleService, 
    time_service: TimeService
):
    """Отображение расписания выбранного ребенка для родителя."""
    child_user_id = int(callback.data.split(":")[1])
    child_dto = await profile_service.get_user_profile_dto(child_user_id)
    
    if not child_dto or not child_dto.class_id:
        return await callback.answer("Профиль ребенка не настроен или не выбран класс.", show_alert=True)
        
    today_iso = time_service.get_now_base().date().isoformat()
    
    # Запрашиваем расписание с учетом группы и доп. занятий ребенка
    day_dto = await schedule_service.get_daily_schedule_for_child(
        class_id=child_dto.class_id, 
        group_id=child_dto.group_id, 
        date_iso=today_iso,
        user_id=child_user_id
    )
    
    text, _ = UIRenderer.render_child_day_schedule(day_dto, child_dto.name)
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()