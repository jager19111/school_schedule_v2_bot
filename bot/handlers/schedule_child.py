import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards

logger = logging.getLogger(__name__)
router = Router()

# ================= 1. ТОЧКИ ВХОДА (ИЗ ГЛАВНОГО МЕНЮ) =================

@router.message(F.text == "📅 Мое расписание")
async def show_smart_today(message: Message, profile_service: ProfileService, schedule_service: ScheduleService):
    user_id = message.from_user.id
    user_dto = await profile_service.get_user_profile_dto(user_id)
    
    target_class = user_dto.class_id
    target_group = user_dto.group_id
    target_id = user_id
    child_name = None

    # Если родитель — перехватываем и берем данные ребенка
    if user_dto.role in ('parent', 'observer'):
        children = await profile_service.get_children_for_parent(user_id)
        if not children:
            return await message.answer("У вас нет привязанных детей. Добавьте ребенка через 'Настройки' -> 'Управление семьей'.")
        
        active_child = children[0] # Пока берем первого, потом можно добавить выбор активного
        target_class = active_child.class_id
        target_group = active_child.group_id
        target_id = active_child.user_id
        child_name = active_child.name

    if not target_class:
        return await message.answer(UIRenderer.render_unregistered_error())
    
    # 1. Получаем умную дату (если вечер - будет завтра)
    target_date_iso = await schedule_service.get_smart_target_date(
        class_id=target_class, group_id=target_group, user_id=target_id
    )
    
    # 2. Рендерим день
    day_dto = await schedule_service.get_daily_schedule_for_child(
        class_id=target_class, group_id=target_group, 
        date_iso=target_date_iso, user_id=target_id
    )
    
    text, _ = UIRenderer.render_child_day_schedule(day_dto, child_name)
    kb = Keyboards.get_day_nav_kb(target_date_iso)
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(F.text == "📆 Моя неделя")
async def show_smart_week(message: Message, profile_service: ProfileService, schedule_service: ScheduleService):
    user_id = message.from_user.id
    user_dto = await profile_service.get_user_profile_dto(user_id)
    
    target_class = user_dto.class_id
    target_group = user_dto.group_id
    target_id = user_id

    # Если родитель — перехватываем и берем данные ребенка
    if user_dto.role in ('parent', 'observer'):
        children = await profile_service.get_children_for_parent(user_id)
        if not children:
            return await message.answer("У вас нет привязанных детей. Добавьте ребенка через 'Настройки' -> 'Управление семьей'.")
        
        active_child = children[0] # Пока берем первого
        target_class = active_child.class_id
        target_group = active_child.group_id
        target_id = active_child.user_id

    if not target_class:
        return await message.answer(UIRenderer.render_unregistered_error())
    
    # 1. Получаем дату понедельника нужной недели (без передачи аргументов)[cite: 3]
    week_start_iso = await schedule_service.get_smart_week_start()
    
    # 2. Используем правильный аргумент week_start_iso[cite: 3]
    week_dto = await schedule_service.get_week_schedule_summary(
        class_id=target_class, 
        group_id=target_group, 
        week_start_iso=week_start_iso, 
        user_id=target_id
    )
    
    # 3. Убран лишний аргумент child_name[cite: 4]
    text, _ = UIRenderer.render_week_summary(week_dto)
    kb = Keyboards.get_week_nav_kb(week_start_iso, is_full=False)
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

# ================= 2. КОЛЛБЭКИ ПАГИНАЦИИ (СДВИГ) =================

@router.callback_query(F.data.startswith("sched:day:"))
async def nav_day_schedule(callback: CallbackQuery, profile_service: ProfileService, schedule_service: ScheduleService):
    target_date_iso = callback.data.split(":")[2]
    user_id = callback.from_user.id
    user_dto = await profile_service.get_user_profile_dto(user_id)
    
    day_dto = await schedule_service.get_daily_schedule_for_child(
        class_id=user_dto.class_id, group_id=user_dto.group_id, 
        date_iso=target_date_iso, user_id=user_id
    )
    
    text, _ = UIRenderer.render_child_day_schedule(day_dto)
    kb = Keyboards.get_day_nav_kb(target_date_iso)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("sched:week:"))
async def nav_week_summary(callback: CallbackQuery, profile_service: ProfileService, schedule_service: ScheduleService):
    week_start_iso = callback.data.split(":")[2]
    user_id = callback.from_user.id
    user_dto = await profile_service.get_user_profile_dto(user_id)
    
    week_dto = await schedule_service.get_week_schedule_summary(
        class_id=user_dto.class_id, group_id=user_dto.group_id, 
        week_start_iso=week_start_iso, user_id=user_id
    )
    
    text, _ = UIRenderer.render_week_summary(week_dto)
    kb = Keyboards.get_week_nav_kb(week_start_iso, is_full=False)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("sched:fullweek:"))
async def nav_full_week(callback: CallbackQuery, profile_service: ProfileService, schedule_service: ScheduleService):
    week_start_iso = callback.data.split(":")[2]
    user_id = callback.from_user.id
    user_dto = await profile_service.get_user_profile_dto(user_id)
    
    full_dto = await schedule_service.get_full_week_schedule(
        class_id=user_dto.class_id, group_id=user_dto.group_id, 
        week_start_iso=week_start_iso, user_id=user_id
    )
    
    text, _ = UIRenderer.render_full_week_schedule(full_dto)
    kb = Keyboards.get_week_nav_kb(week_start_iso, is_full=True)
    
    # Telegram имеет лимит на 4096 символов. Если расписание очень длинное, лучше резать, 
    # но для недели обычно хватает 2500-3500 символов.
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка вывода полной недели (возможно превышен лимит символов): {e}")
        await callback.answer("Ошибка: текст слишком длинный", show_alert=True)
        
    await callback.answer()