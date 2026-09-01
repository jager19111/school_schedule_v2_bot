import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import aiosqlite

logger = logging.getLogger(__name__)
router = Router()

class ExtraClassStates(StatesGroup):
    waiting_for_time_start = State()
    waiting_for_time_end = State()
    waiting_for_title = State()

def validate_time(time_str: str) -> bool:
    """Строгая валидация ввода времени для защиты базы данных."""
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except ValueError:
        return False

@router.message(ExtraClassStates.waiting_for_time_start)
async def process_time_start(message: Message, state: FSMContext):
    time_str = message.text.strip()
    if not validate_time(time_str):
        return await message.answer("❌ Неверный формат! Введите время в формате ЧЧ:ММ (например, 15:30).")
    
    await state.update_data(time_start=time_str)
    await message.answer("Введите время окончания занятия (ЧЧ:ММ):")
    await state.set_state(ExtraClassStates.waiting_for_time_end)