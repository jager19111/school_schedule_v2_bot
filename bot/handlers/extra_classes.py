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
    waiting_for_time_start = State()
    waiting_for_time_end = State()
    waiting_for_title = State()
    waiting_for_delete_id = State()

# === ГЛАВНОЕ МЕНЮ И ОТМЕНА ===

@router.message(F.text == "➕ Доп. занятия")
async def show_extra_menu(message: Message):
    text, _ = UIRenderer.render_extra_classes_menu()
    await message.answer(text, reply_markup=Keyboards.get_extra_classes_menu(), parse_mode="HTML")

@router.callback_query(F.data == "extra:menu")
async def show_extra_menu_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text, _ = UIRenderer.render_extra_classes_menu()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_extra_classes_menu(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "extra:cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text, _ = UIRenderer.render_extra_classes_menu()
    await callback.message.edit_text(f"❌ Действие отменено.\n\n{text}", reply_markup=Keyboards.get_extra_classes_menu(), parse_mode="HTML")
    await callback.answer()


# === СПИСОК ЗАНЯТИЙ ===

@router.callback_query(F.data == "extra:list")
async def show_extra_list(callback: CallbackQuery, extra_classes_service: ExtraClassesService):
    dto_list = await extra_classes_service.get_user_extra_classes(callback.from_user.id)
    text, _ = UIRenderer.render_extra_classes_list(dto_list)
    await callback.message.edit_text(text, reply_markup=Keyboards.get_back_to_extra_menu(), parse_mode="HTML")
    await callback.answer()


# === УДАЛЕНИЕ ЗАНЯТИЯ ===

@router.callback_query(F.data == "extra:delete")
async def start_delete_extra(callback: CallbackQuery, state: FSMContext, extra_classes_service: ExtraClassesService):
    dto_list = await extra_classes_service.get_user_extra_classes(callback.from_user.id)
    
    # Если список пуст, рендерим возврат
    if not dto_list.items:
        text, _ = UIRenderer.render_extra_class_delete_prompt(dto_list)
        await callback.message.edit_text(text, reply_markup=Keyboards.get_back_to_extra_menu(), parse_mode="HTML")
        return await callback.answer()

    text, _ = UIRenderer.render_extra_class_delete_prompt(dto_list)
    await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_delete_id)
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_delete_id)
async def process_delete_id(message: Message, state: FSMContext, extra_classes_service: ExtraClassesService):
    if not message.text.strip().isdigit():
        text, _ = UIRenderer.render_extra_class_not_found()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")

    class_id = int(message.text.strip())
    response = await extra_classes_service.delete_extra_class(user_id=message.from_user.id, extra_id=class_id)

    if not response.success:
        text, _ = UIRenderer.render_extra_class_not_found()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")

    await state.clear()
    text_deleted, _ = UIRenderer.render_extra_class_deleted()
    text_menu, _ = UIRenderer.render_extra_classes_menu()
    await message.answer(f"{text_deleted}\n\n{text_menu}", reply_markup=Keyboards.get_extra_classes_menu(), parse_mode="HTML")


# === ДОБАВЛЕНИЕ ЗАНЯТИЯ ===

@router.callback_query(F.data == "extra:add")
async def start_add_extra(callback: CallbackQuery, state: FSMContext):
    text, _ = UIRenderer.render_extra_class_time_start()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard())
    await state.set_state(ExtraClassStates.waiting_for_time_start)
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_time_start)
async def process_time_start(message: Message, state: FSMContext, time_service: TimeService):
    time_str = message.text.strip()
    
    if not time_service.validate_time_format(time_str):
        text, _ = UIRenderer.render_extra_class_invalid_time()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    await state.update_data(time_start=time_str)
    
    text, _ = UIRenderer.render_extra_class_time_end()
    await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())
    await state.set_state(ExtraClassStates.waiting_for_time_end)

@router.message(ExtraClassStates.waiting_for_time_end)
async def process_time_end(message: Message, state: FSMContext, time_service: TimeService):
    time_end = message.text.strip()
    data = await state.get_data()
    
    # 1. Проверка правильного формата
    if not time_service.validate_time_format(time_end):
        text, _ = UIRenderer.render_extra_class_invalid_time()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    # 2. Проверка диапазона (начало строго раньше конца)
    if not time_service.validate_time_range(data["time_start"], time_end):
        text, _ = UIRenderer.render_extra_class_invalid_range()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    await state.update_data(time_end=time_end)
    
    text, _ = UIRenderer.render_extra_class_title()
    await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())
    await state.set_state(ExtraClassStates.waiting_for_title)

@router.message(ExtraClassStates.waiting_for_title)
async def process_title(
    message: Message,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
    profile_service: ProfileService,
):
    data = await state.get_data()
    title = message.text.strip()
    user_id = message.from_user.id

    profile_dto = await profile_service.get_user_profile_dto(user_id)
    response = await extra_classes_service.add_extra_class(
        user_id=user_id,
        family_id=profile_dto.family_id,
        time_start=data["time_start"],
        time_end=data["time_end"],
        title=title
    )

    if not response.success:
        if response.error_code == "invalid_time":
            text, _ = UIRenderer.render_extra_class_invalid_time()
        else:
            text, _ = UIRenderer.render_extra_class_error()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    await state.clear()
    text_success, _ = UIRenderer.render_extra_class_success()
    text_menu, _ = UIRenderer.render_extra_classes_menu()
    await message.answer(f"{text_success}\n\n{text_menu}", reply_markup=Keyboards.get_extra_classes_menu(), parse_mode="HTML")