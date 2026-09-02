import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from bot.utils.ui_renderer import UIRenderer
from services.time_service import TimeService

logger = logging.getLogger(__name__)
router = Router()

class ExtraClassStates(StatesGroup):
    waiting_for_time_start = State()
    waiting_for_time_end = State()
    waiting_for_title = State()

@router.message(ExtraClassStates.waiting_for_time_start)
async def process_time_start(message: Message, state: FSMContext, time_service: TimeService):
    time_str = message.text.strip()
    
    # Делегирование проверки сервису времени (Правило 8/9)[cite: 1]
    is_valid = time_service.validate_time_format(time_str) 
    
    if not is_valid:
        return await message.answer(UIRenderer.render_extra_class_invalid_time())
    
    await state.update_data(time_start=time_str)
    await message.answer(UIRenderer.render_extra_class_time_end())
    await state.set_state(ExtraClassStates.waiting_for_time_end)