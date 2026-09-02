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
    waiting_for_day = State()        # <-- НОВЫЙ ЭТАП[cite: 2]
    waiting_for_time_start = State()
    waiting_for_time_end = State()
    waiting_for_title = State()
    waiting_for_location = State()   # <-- НОВЫЙ ЭТАП[cite: 2]
    waiting_for_reminder = State()   # <-- НОВЫЙ ЭТАП[cite: 2]
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
    """Шаг 1: Запрос дня недели."""
    text, _ = UIRenderer.render_extra_class_day()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_day_selection_kb())
    await state.set_state(ExtraClassStates.waiting_for_day)
    await callback.answer()

@router.callback_query(ExtraClassStates.waiting_for_day, F.data.startswith("extraday:"))
async def process_day(callback: CallbackQuery, state: FSMContext):
    """Шаг 2: Обработка дня недели и запрос времени начала[cite: 2]."""
    day_num = int(callback.data.split(":")[1])
    await state.update_data(day_of_week=day_num)
    
    text, _ = UIRenderer.render_extra_class_time_start()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard())
    await state.set_state(ExtraClassStates.waiting_for_time_start)
    await callback.answer()

# ЗАМЕНИТЬ часть файла bot/handlers/extra_classes.py, начиная с process_time_start и до конца:

@router.message(ExtraClassStates.waiting_for_time_start)
async def process_time_start(message: Message, state: FSMContext, time_service: TimeService):
    """Шаг 3: Умная нормализация времени начала."""
    # Используем умный нормализатор вместо строгой проверки
    norm_time = time_service.normalize_time(message.text)
    
    if not norm_time:
        text, _ = UIRenderer.render_extra_class_invalid_time()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    await state.update_data(time_start=norm_time)
    
    text, _ = UIRenderer.render_extra_class_time_end()
    await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_time_end)

@router.message(ExtraClassStates.waiting_for_time_end)
async def process_time_end(message: Message, state: FSMContext, time_service: TimeService):
    """Шаг 4: Умная нормализация времени окончания и проверка диапазона."""
    norm_time = time_service.normalize_time(message.text)
    data = await state.get_data()
    
    if not norm_time:
        text, _ = UIRenderer.render_extra_class_invalid_time()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    if not time_service.validate_time_range(data["time_start"], norm_time):
        text, _ = UIRenderer.render_extra_class_invalid_range()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    await state.update_data(time_end=norm_time)
    
    text, _ = UIRenderer.render_extra_class_title()
    await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_title)

@router.message(ExtraClassStates.waiting_for_title)
async def process_title(message: Message, state: FSMContext):
    """Шаг 5: Обработка названия и запрос локации (с кнопкой пропуска)."""
    title = message.text.strip()
    await state.update_data(title=title)
    
    text, _ = UIRenderer.render_extra_class_location()
    # Добавляем клавиатуру с кнопкой "Пропустить"
    await message.answer(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_location"), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_location)

@router.callback_query(ExtraClassStates.waiting_for_location, F.data == "skip_location")
async def skip_location(callback: CallbackQuery, state: FSMContext):
    """Шаг 6 (Альтернатива): Пропуск ввода локации."""
    await state.update_data(location=None)
    
    text, _ = UIRenderer.render_extra_class_reminder()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_reminder"), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_reminder)
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_location)
async def process_location(message: Message, state: FSMContext):
    """Шаг 6: Обработка текстового ввода локации."""
    location = message.text.strip()
    await state.update_data(location=location)
    
    text, _ = UIRenderer.render_extra_class_reminder()
    await message.answer(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_reminder"), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_reminder)

@router.callback_query(ExtraClassStates.waiting_for_reminder, F.data == "skip_reminder")
async def skip_reminder(callback: CallbackQuery, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    """Шаг 7 (Альтернатива): Пропуск напоминания (используем дефолтные 30 минут)."""
    await finalize_extra_class(callback.message, callback.from_user.id, state, extra_classes_service, profile_service, reminder_minutes=30)
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_reminder)
async def process_reminder(message: Message, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    """Шаг 7: Обработка ручного ввода минут напоминания."""
    reminder_text = message.text.strip()
    
    if not reminder_text.isdigit():
        text, _ = UIRenderer.render_extra_class_invalid_reminder()
        return await message.answer(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_reminder"), parse_mode="HTML")
        
    await finalize_extra_class(message, message.from_user.id, state, extra_classes_service, profile_service, reminder_minutes=int(reminder_text))

async def finalize_extra_class(message, user_id, state, extra_classes_service, profile_service, reminder_minutes):
    """Общая функция финализации сохранения для избежания дублирования кода."""
    data = await state.get_data()
    
    # 1. Получаем DTO профиля[cite: 10]
    profile_dto = await profile_service.get_user_profile_dto(user_id)

    # 2. Вызываем сервис для записи в БД[cite: 12]
    response = await extra_classes_service.add_extra_class(
        user_id=user_id,
        family_id=profile_dto.family_id,
        day_of_week=data["day_of_week"],
        time_start=data["time_start"],
        time_end=data["time_end"],
        title=data["title"],
        location=data.get("location"),
        reminder_minutes=reminder_minutes
    )

    # 3. Маршрутизация ответа[cite: 9]
    if getattr(message, 'edit_text', None):
        # Если вызов пришел из CallbackQuery (skip_reminder)
        msg_func = message.edit_text
    else:
        # Если вызов пришел из обычного сообщения
        msg_func = message.answer

    if not response.success:
        text, _ = UIRenderer.render_extra_class_error()
        await msg_func(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        return

    await state.clear()
    text_success, _ = UIRenderer.render_extra_class_success()
    text_menu, _ = UIRenderer.render_extra_classes_menu()
    await msg_func(
        f"{text_success}\n\n{text_menu}", 
        reply_markup=Keyboards.get_extra_classes_menu(), 
        parse_mode="HTML"
    )