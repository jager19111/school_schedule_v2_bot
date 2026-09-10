# bot/handlers/search.py
#
# ЭТАП 4: изменения.
#
# 1. Парсинг callback_data через bot/callbacks.py:
#    search:*, srch_cls:*, srch_tch:*, sch_c*, sch_t*.
#    Формат строк на проводе не изменён.
#
# 2. Умная дата (после 19:00 — завтра, воскресенье пропускаем)
#    переезжает из двух копипаст-блоков в
#    TimeService.get_smart_view_datetime().
#
# 3. Раньше `_, class_id, date_iso = split(":")` без try/except
#    роняло хендлер на битой строке — теперь parse-методы
#    возвращают None и пользователь получает alert.

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from datetime import timedelta

from bot import callbacks
from bot.callbacks import (
    SearchClassCD,
    SearchClassDayCD,
    SearchClassFullWeekCD,
    SearchClassWeekCD,
    SearchTeacherCD,
    SearchTeacherDayCD,
    SearchTeacherFullWeekCD,
    SearchTeacherWeekCD,
)
from services.schedule_service import ScheduleService
from core.repository.schedule_repository import ScheduleRepository
from services.time_service import TimeService
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from core.models.dto import ClassListDTO, TeacherListDTO

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == callbacks.SEARCH_BACK)
async def search_back(callback: CallbackQuery):
    text = UIRenderer.render_school_search_menu()
    kb = Keyboards.get_school_search_kb()
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == callbacks.SEARCH_CLASSES)
async def search_classes(callback: CallbackQuery, schedule_repo: ScheduleRepository):
    metadata = await schedule_repo.get_metadata()
    classes_dict = {k: v.name if hasattr(v, 'name') else v for k, v in metadata.get('classes', {}).items()}
    class_dto = ClassListDTO(classes=classes_dict)
    text = UIRenderer.render_search_class_select()
    kb = Keyboards.get_search_classes_kb(class_dto)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == callbacks.SEARCH_TEACHERS)
async def search_teachers(callback: CallbackQuery, schedule_repo: ScheduleRepository):
    metadata = await schedule_repo.get_metadata()
    teachers_dict = {k: v.name if hasattr(v, 'name') else v for k, v in metadata.get('teachers', {}).items()}
    teacher_dto = TeacherListDTO(teachers=teachers_dict)
    text = UIRenderer.render_search_teacher_select()
    kb = Keyboards.get_search_teachers_kb(teacher_dto)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(SearchClassCD.filter())
async def select_class_day(callback: CallbackQuery, callback_data: SearchClassCD, schedule_repo: ScheduleRepository, schedule_service: ScheduleService, time_service: TimeService):
    class_id = callback_data.class_id
    metadata = await schedule_repo.get_metadata()
    cls_obj = metadata.get('classes', {}).get(class_id)
    class_name = cls_obj.name if hasattr(cls_obj, 'name') else "Класс"
    # Этап 4: умная дата — в TimeService (была копипастой здесь).
    target_date = time_service.get_smart_view_datetime()
    date_iso = target_date.date().isoformat()
    # Сразу выводим расписание дня
    day_dto = await schedule_service.get_daily_schedule_for_class(class_id, date_iso)
    text, _ = UIRenderer.render_child_day_schedule(day_dto)
    text = f"🎓 <b>Расписание: {class_name}</b>\n" + text
    monday = target_date - timedelta(days=target_date.isoweekday() - 1)
    kb = Keyboards.get_search_days_kb(class_id, False, monday.date().isoformat())
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(SearchTeacherCD.filter())
async def select_teacher_day(callback: CallbackQuery, callback_data: SearchTeacherCD, schedule_repo: ScheduleRepository, schedule_service: ScheduleService, time_service: TimeService):
    teacher_id = callback_data.teacher_id
    metadata = await schedule_repo.get_metadata()
    tch_obj = metadata.get('teachers', {}).get(teacher_id)
    teacher_name = tch_obj.name if hasattr(tch_obj, 'name') else "Преподаватель"
    # Этап 4: умная дата — в TimeService (была копипастой здесь).
    target_date = time_service.get_smart_view_datetime()
    date_iso = target_date.date().isoformat()
    day_dto = await schedule_service.get_daily_schedule_for_teacher(teacher_id, date_iso)
    text, _ = UIRenderer.render_child_day_schedule(day_dto)
    text = f"👨‍🏫 <b>Расписание: {teacher_name}</b>\n" + text
    monday = target_date - timedelta(days=target_date.isoweekday() - 1)
    kb = Keyboards.get_search_days_kb(teacher_id, True, monday.date().isoformat())
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# === ПАГИНАЦИЯ НЕДЕЛЬ ===

@router.callback_query(SearchClassWeekCD.filter())
async def nav_class_week(callback: CallbackQuery, callback_data: SearchClassWeekCD, schedule_repo: ScheduleRepository):
    class_id, week_start_iso = callback_data.class_id, callback_data.week_start_iso
    metadata = await schedule_repo.get_metadata()
    cls_obj = metadata.get('classes', {}).get(class_id)
    class_name = cls_obj.name if hasattr(cls_obj, 'name') else "Класс"
    text = UIRenderer.render_search_day_select(class_name)
    kb = Keyboards.get_search_days_kb(class_id, False, week_start_iso)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(SearchTeacherWeekCD.filter())
async def nav_teacher_week(callback: CallbackQuery, callback_data: SearchTeacherWeekCD, schedule_repo: ScheduleRepository):
    teacher_id, week_start_iso = callback_data.teacher_id, callback_data.week_start_iso
    metadata = await schedule_repo.get_metadata()
    tch_obj = metadata.get('teachers', {}).get(teacher_id)
    teacher_name = tch_obj.name if hasattr(tch_obj, 'name') else "Преподаватель"
    text = UIRenderer.render_search_day_select(teacher_name)
    kb = Keyboards.get_search_days_kb(teacher_id, True, week_start_iso)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# === ВЫВОД РАСПИСАНИЯ ===

@router.callback_query(SearchClassDayCD.filter())
async def show_class_schedule(callback: CallbackQuery, callback_data: SearchClassDayCD, schedule_service: ScheduleService, schedule_repo: ScheduleRepository):
    class_id, date_iso = callback_data.class_id, callback_data.date_iso
    day_dto = await schedule_service.get_daily_schedule_for_class(class_id, date_iso)
    metadata = await schedule_repo.get_metadata()
    cls_obj = metadata.get('classes', {}).get(class_id)
    class_name = cls_obj.name if hasattr(cls_obj, 'name') else "Класс"
    text, _ = UIRenderer.render_child_day_schedule(day_dto)
    text = f"🎓 <b>Расписание: {class_name}</b>\n" + text
    date_obj = TimeService.date_from_iso(date_iso)
    monday = date_obj - timedelta(days=date_obj.isoweekday() - 1)
    kb = Keyboards.get_search_days_kb(class_id, False, monday.isoformat())
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(SearchTeacherDayCD.filter())
async def show_teacher_schedule(callback: CallbackQuery, callback_data: SearchTeacherDayCD, schedule_service: ScheduleService, schedule_repo: ScheduleRepository):
    teacher_id, date_iso = callback_data.teacher_id, callback_data.date_iso
    day_dto = await schedule_service.get_daily_schedule_for_teacher(teacher_id, date_iso)
    metadata = await schedule_repo.get_metadata()
    tch_obj = metadata.get('teachers', {}).get(teacher_id)
    teacher_name = tch_obj.name if hasattr(tch_obj, 'name') else "Преподаватель"
    text, _ = UIRenderer.render_child_day_schedule(day_dto)
    text = f"👨‍🏫 <b>Расписание: {teacher_name}</b>\n" + text
    date_obj = TimeService.date_from_iso(date_iso)
    monday = date_obj - timedelta(days=date_obj.isoweekday() - 1)
    kb = Keyboards.get_search_days_kb(teacher_id, True, monday.isoformat())
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# === ПОЛНАЯ НЕДЕЛЯ ===

@router.callback_query(SearchClassFullWeekCD.filter())
async def show_class_full_week(callback: CallbackQuery, callback_data: SearchClassFullWeekCD, schedule_service: ScheduleService, schedule_repo: ScheduleRepository):
    class_id, week_start_iso = callback_data.class_id, callback_data.week_start_iso
    metadata = await schedule_repo.get_metadata()
    cls_obj = metadata.get('classes', {}).get(class_id)
    class_name = cls_obj.name if hasattr(cls_obj, 'name') else "Класс"
    full_dto = await schedule_service.get_full_week_schedule_for_class(class_id, week_start_iso)
    text, _ = UIRenderer.render_full_week_schedule(full_dto)
    text = f"🎓 <b>Вся неделя: {class_name}</b>\n\n" + text
    kb = Keyboards.get_search_days_kb(class_id, False, week_start_iso, is_full=True)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(SearchTeacherFullWeekCD.filter())
async def show_teacher_full_week(callback: CallbackQuery, callback_data: SearchTeacherFullWeekCD, schedule_service: ScheduleService, schedule_repo: ScheduleRepository):
    teacher_id, week_start_iso = callback_data.teacher_id, callback_data.week_start_iso
    metadata = await schedule_repo.get_metadata()
    tch_obj = metadata.get('teachers', {}).get(teacher_id)
    teacher_name = tch_obj.name if hasattr(tch_obj, 'name') else "Преподаватель"
    full_dto = await schedule_service.get_full_week_schedule_for_teacher(teacher_id, week_start_iso)
    text, _ = UIRenderer.render_full_week_schedule(full_dto)
    text = f"👨‍🏫 <b>Вся неделя: {teacher_name}</b>\n\n" + text
    kb = Keyboards.get_search_days_kb(teacher_id, True, week_start_iso, is_full=True)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()
