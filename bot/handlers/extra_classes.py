# bot/handlers/extra_classes.py (фрагмент)
import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from services.time_service import TimeService
from core.repository.extra_classes_repository import ExtraClassesRepository
from services.profiles_service import ProfileService
from bot.utils.ui_renderer import UIRenderer

logger = logging.getLogger(__name__)
router = Router()

class ExtraClassStates(StatesGroup):
    waiting_for_time_start = State()
    waiting_for_time_end = State()
    waiting_for_title = State()

@router.message(ExtraClassStates.waiting_for_time_start)
async def process_time_start(message: Message, state: FSMContext, time_service: TimeService):
    time_str = message.text.strip()
    if not time_service.validate_time_format(time_str):
        return await message.answer("❌ Неверный формат! Введите время в формате ЧЧ:ММ (например, 15:30).")

    await state.update_data(time_start=time_str)
    await message.answer("Введите время окончания занятия (ЧЧ:ММ):")
    await state.set_state(ExtraClassStates.waiting_for_time_end)

@router.message(ExtraClassStates.waiting_for_time_end)
async def process_time_end(message: Message, state: FSMContext, time_service: TimeService):
    time_str = message.text.strip()
    if not time_service.validate_time_format(time_str):
        return await message.answer("❌ Неверный формат! Введите время в формате ЧЧ:ММ (например, 16:15).")

    await state.update_data(time_end=time_str)
    await message.answer("Введите название занятия (например, \"Футбол\"):")
    await state.set_state(ExtraClassStates.waiting_for_title)

@router.message(ExtraClassStates.waiting_for_title)
async def process_title(
    message: Message,
    state: FSMContext,
    extra_classes_repo: ExtraClassesRepository,
    profile_service: ProfileService,
    time_service: TimeService,
):
    data = await state.get_data()
    title = message.text.strip()

    # Профиль пользователя: берём user_id / family_id / class_id
    profile = await profile_service.get_user_profile(message.from_user.id)
    family_id = profile.get("family_id")
    user_id = message.from_user.id

    # Текущий день недели по базовой таймзоне (1..7)
    now = time_service.get_now_base()
    day_of_week = now.isoweekday()

    await extra_classes_repo.create_extra_class(
        user_id=user_id,
        family_id=family_id,
        day_of_week=day_of_week,
        time_start=data["time_start"],
        time_end=data["time_end"],
        title=title,
        location=None,
        reminder_minutes=30,  # либо взять из настроек профиля
    )

    await message.answer("✅ Доп. занятие сохранено и будет учитываться в расписании.")
    await state.clear()