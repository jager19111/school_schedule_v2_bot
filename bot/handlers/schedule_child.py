import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from core.models.dto import ChildrenListDTO

logger = logging.getLogger(__name__)
router = Router()

# ================= 1. ТОЧКИ ВХОДА (ИЗ ГЛАВНОГО МЕНЮ) =================

@router.message(F.text == "📅 Мое расписание")
async def show_smart_today(message: Message, state: FSMContext, profile_service: ProfileService, schedule_service: ScheduleService):
    user_id = message.from_user.id
    user_dto = await profile_service.get_user_profile_dto(user_id)
    
    target_class = user_dto.class_id
    target_group = user_dto.group_id
    target_id = user_id
    child_name = None

    if user_dto.role in ('parent', 'observer'):
        children = await profile_service.get_children_for_parent(user_id)
        if not children:
            return await message.answer("У вас нет привязанных детей. Добавьте ребенка через 'Настройки' -> 'Управление семьей'.")
        
        # Если детей > 1, просим выбрать
        if len(children) > 1:
            list_dto = ChildrenListDTO(children=children, action="today")
            # Безопасное получение текста (защита от ошибки распаковки)
            res = UIRenderer.render_parent_children_menu(list_dto)
            text = res[0] if isinstance(res, tuple) else res
            kb = Keyboards.get_parent_children_menu(list_dto)
            return await message.answer(text, reply_markup=kb, parse_mode="HTML")
        
        active_child = children[0]
        target_class = active_child.class_id
        target_group = active_child.group_id
        target_id = active_child.user_id
        child_name = active_child.name

    # Сохраняем target_id в FSM для кнопок пагинации (Вперед/Назад)
    await state.update_data(schedule_target_id=target_id)

    if not target_class:
        res = UIRenderer.render_unregistered_error()
        text = res[0] if isinstance(res, tuple) else res
        return await message.answer(text)
    
    target_date_iso = await schedule_service.get_smart_target_date(
        class_id=target_class, group_id=target_group, user_id=target_id
    )
    
    day_dto = await schedule_service.get_daily_schedule_for_child(
        class_id=target_class, group_id=target_group, 
        date_iso=target_date_iso, user_id=target_id
    )
    
    res = UIRenderer.render_child_day_schedule(day_dto, child_name)
    text = res[0] if isinstance(res, tuple) else res
    kb = Keyboards.get_day_nav_kb(target_date_iso)
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(F.text == "📆 Моя неделя")
async def show_smart_week(message: Message, state: FSMContext, profile_service: ProfileService, schedule_service: ScheduleService):
    user_id = message.from_user.id
    user_dto = await profile_service.get_user_profile_dto(user_id)
    
    target_class = user_dto.class_id
    target_group = user_dto.group_id
    target_id = user_id

    if user_dto.role in ('parent', 'observer'):
        children = await profile_service.get_children_for_parent(user_id)
        if not children:
            return await message.answer("У вас нет привязанных детей. Добавьте ребенка через 'Настройки' -> 'Управление семьей'.")
        
        if len(children) > 1:
            list_dto = ChildrenListDTO(children=children, action="week")
            res = UIRenderer.render_parent_children_menu(list_dto)
            text = res[0] if isinstance(res, tuple) else res
            kb = Keyboards.get_parent_children_menu(list_dto)
            return await message.answer(text, reply_markup=kb, parse_mode="HTML")
        
        active_child = children[0]
        target_class = active_child.class_id
        target_group = active_child.group_id
        target_id = active_child.user_id

    await state.update_data(schedule_target_id=target_id)

    if not target_class:
        res = UIRenderer.render_unregistered_error()
        text = res[0] if isinstance(res, tuple) else res
        return await message.answer(text)
    
    week_start_iso = await schedule_service.get_smart_week_start()
    
    week_dto = await schedule_service.get_week_schedule_summary(
        class_id=target_class, 
        group_id=target_group, 
        week_start_iso=week_start_iso, 
        user_id=target_id
    )
    
    res = UIRenderer.render_week_summary(week_dto)
    text = res[0] if isinstance(res, tuple) else res
    kb = Keyboards.get_week_nav_kb(week_start_iso, is_full=False)
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# ================= 1.5. КОЛЛБЭКИ ВЫБОРА РЕБЕНКА (ДЛЯ РОДИТЕЛЯ) =================

@router.callback_query(F.data.startswith("p_today:"))
async def cb_select_child_today(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService, schedule_service: ScheduleService):
    target_id = int(callback.data.split(":")[1])
    await state.update_data(schedule_target_id=target_id)
    
    target_dto = await profile_service.get_user_profile_dto(target_id)
    if not target_dto or not target_dto.class_id:
        return await callback.answer("Профиль ребенка не настроен.", show_alert=True)
        
    target_date_iso = await schedule_service.get_smart_target_date(
        class_id=target_dto.class_id, group_id=target_dto.group_id, user_id=target_id
    )
    
    day_dto = await schedule_service.get_daily_schedule_for_child(
        class_id=target_dto.class_id, group_id=target_dto.group_id, 
        date_iso=target_date_iso, user_id=target_id
    )
    
    res = UIRenderer.render_child_day_schedule(day_dto, target_dto.name)
    text = res[0] if isinstance(res, tuple) else res
    kb = Keyboards.get_day_nav_kb(target_date_iso)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("p_week:"))
async def cb_select_child_week(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService, schedule_service: ScheduleService):
    target_id = int(callback.data.split(":")[1])
    await state.update_data(schedule_target_id=target_id)
    
    target_dto = await profile_service.get_user_profile_dto(target_id)
    if not target_dto or not target_dto.class_id:
        return await callback.answer("Профиль ребенка не настроен.", show_alert=True)
        
    week_start_iso = await schedule_service.get_smart_week_start()
    
    week_dto = await schedule_service.get_week_schedule_summary(
        class_id=target_dto.class_id, group_id=target_dto.group_id, 
        week_start_iso=week_start_iso, user_id=target_id
    )
    
    res = UIRenderer.render_week_summary(week_dto)
    text = res[0] if isinstance(res, tuple) else res
    kb = Keyboards.get_week_nav_kb(week_start_iso, is_full=False)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ================= 2. КОЛЛБЭКИ ПАГИНАЦИИ (СДВИГ) =================

@router.callback_query(F.data.startswith("sched:day:"))
async def nav_day_schedule(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService, schedule_service: ScheduleService):
    target_date_iso = callback.data.split(":")[2]
    
    data = await state.get_data()
    target_id = data.get("schedule_target_id", callback.from_user.id)
    
    target_dto = await profile_service.get_user_profile_dto(target_id)
    child_name = target_dto.name if target_id != callback.from_user.id else None
    
    day_dto = await schedule_service.get_daily_schedule_for_child(
        class_id=target_dto.class_id, group_id=target_dto.group_id, 
        date_iso=target_date_iso, user_id=target_id
    )
    
    res = UIRenderer.render_child_day_schedule(day_dto, child_name)
    text = res[0] if isinstance(res, tuple) else res
    kb = Keyboards.get_day_nav_kb(target_date_iso)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("sched:week:"))
async def nav_week_summary(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService, schedule_service: ScheduleService):
    week_start_iso = callback.data.split(":")[2]
    
    data = await state.get_data()
    target_id = data.get("schedule_target_id", callback.from_user.id)
    target_dto = await profile_service.get_user_profile_dto(target_id)
    
    week_dto = await schedule_service.get_week_schedule_summary(
        class_id=target_dto.class_id, group_id=target_dto.group_id, 
        week_start_iso=week_start_iso, user_id=target_id
    )
    
    res = UIRenderer.render_week_summary(week_dto)
    text = res[0] if isinstance(res, tuple) else res
    kb = Keyboards.get_week_nav_kb(week_start_iso, is_full=False)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("sched:full_week:"))
async def nav_full_week(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService, schedule_service: ScheduleService):
    week_start_iso = callback.data.split(":")[2]
    
    data = await state.get_data()
    target_id = data.get("schedule_target_id", callback.from_user.id)
    target_dto = await profile_service.get_user_profile_dto(target_id)
    
    full_dto = await schedule_service.get_full_week_schedule(
        class_id=target_dto.class_id, group_id=target_dto.group_id, 
        week_start_iso=week_start_iso, user_id=target_id
    )
    
    res = UIRenderer.render_full_week_schedule(full_dto)
    text = res[0] if isinstance(res, tuple) else res
    kb = Keyboards.get_week_nav_kb(week_start_iso, is_full=True)
    
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка вывода полной недели: {e}")
        await callback.answer("Ошибка: текст слишком длинный", show_alert=True)
        
    await callback.answer()