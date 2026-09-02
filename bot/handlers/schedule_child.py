import logging
from aiogram import Router, F
from aiogram.types import Message
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.time_service import TimeService
from bot.utils.ui_renderer import UIRenderer

logger = logging.getLogger(__name__)
router = Router()

@router.message(F.text == "📅 Сегодня")
async def show_today(message: Message, profile_service: ProfileService, schedule_service: ScheduleService, time_service: TimeService):
    user_dto = await profile_service.get_user_profile_dto(message.from_user.id)
    if not user_dto or not user_dto.class_id:
        return await message.answer(UIRenderer.render_unregistered_error())
    
    # Правило 5: Работаем с временем только через TimeService[cite: 1]
    today_iso = time_service.get_now_base().date().isoformat()
    
    # Сервис возвращает готовый DTO[cite: 1]
    day_dto = await schedule_service.get_daily_schedule_for_child(
        class_id=user_dto.class_id, 
        group_id=user_dto.group_id, 
        date_iso=today_iso,
        user_id=message.from_user.id,
    )
    
    # Рендерер формирует текст расписания[cite: 1]
    text = UIRenderer.render_child_day_schedule(day_dto)
    await message.answer(text, parse_mode="HTML")