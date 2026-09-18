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
from services.time_service import TimeService
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from core.models.dto import ClassListDTO, TeacherListDTO, DayScheduleDTO

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == callbacks.SEARCH_BACK)
async def search_back(callback: CallbackQuery):
    text = UIRenderer.render_school_search_menu()
    kb = Keyboards.get_school_search_kb()
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == callbacks.SEARCH_CLASSES)
async def search_classes(
    callback: CallbackQuery,
    schedule_service: ScheduleService,
):
    class_dto: ClassListDTO = (
        await schedule_service.get_classes_list()
    )

    text = UIRenderer.render_search_class_select()
    kb = Keyboards.get_search_classes_kb(class_dto)

    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(F.data == callbacks.SEARCH_TEACHERS)
async def search_teachers(
    callback: CallbackQuery,
    schedule_service: ScheduleService,
):
    teacher_dto: TeacherListDTO = (
        await schedule_service.get_teachers_list()
    )

    text = UIRenderer.render_search_teacher_select()
    kb = Keyboards.get_search_teachers_kb(teacher_dto)

    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(SearchClassCD.filter())
async def select_class_day(
    callback: CallbackQuery,
    callback_data: SearchClassCD,
    schedule_service: ScheduleService,
    time_service: TimeService,
):
    class_id = callback_data.class_id
    class_name = await schedule_service.get_class_name(class_id)

    # 1. Умная дата (запрашивает сервис с проверкой реальных уроков)
    date_iso = await schedule_service.get_smart_target_date(
        class_id=class_id,
        group_id="ALL",
    )
    target_date = TimeService.date_from_iso(date_iso)

    # 2. Получаем расписание на найденный день
    day_dto = await schedule_service.get_daily_schedule_for_class(
        class_id,
        date_iso,
    )

    text, _ = UIRenderer.render_day_schedule(day_dto)
    text = f"🎓 <b>Расписание: {class_name}</b>\n" + text

    # 3. Проверяем наличие замен
    has_changes = any(
        lesson.is_exchange or lesson.is_cancelled
        for lesson in day_dto.lessons
    )

    monday = target_date - timedelta(
        days=target_date.isoweekday() - 1,
    )

    # 4. ИСПРАВЛЕНИЕ: monday уже date, просто вызываем isoformat()
    kb = Keyboards.get_search_days_kb(
        target_id=class_id,
        is_teacher=False,
        week_start_iso=monday.isoformat(),
        is_full=False,
        has_changes=has_changes,
        date_iso=date_iso,
    )

    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(SearchTeacherCD.filter())
async def select_teacher_day(
    callback: CallbackQuery,
    callback_data: SearchTeacherCD,
    schedule_service: ScheduleService,
    time_service: TimeService,
):
    teacher_id = callback_data.teacher_id
    teacher_name = await schedule_service.get_teacher_name(teacher_id)

    # 1. Умная дата: запрашиваем через специальный метод сервиса для учителя
    date_iso = await schedule_service.get_smart_teacher_target_date(
        teacher_id=teacher_id
    )
    target_date = TimeService.date_from_iso(date_iso)

    # 2. Получаем расписание на найденный день
    day_dto = (
        await schedule_service.get_daily_schedule_for_teacher(
            teacher_id,
            date_iso,
        )
    )

    text, _ = UIRenderer.render_day_schedule(day_dto)
    text = f"👨‍🏫 <b>Расписание: {teacher_name}</b>\n{text}"

    # 3. Проверяем наличие замен
    has_changes = any(
        lesson.is_exchange or lesson.is_cancelled
        for lesson in day_dto.lessons
    )

    monday = target_date - timedelta(days=target_date.isoweekday() - 1)

    # 4. ИСПРАВЛЕНИЕ: monday уже date, просто вызываем isoformat()
    kb = Keyboards.get_search_days_kb(
        target_id=teacher_id,
        is_teacher=True,
        week_start_iso=monday.isoformat(),
        is_full=False,
        has_changes=has_changes,
        date_iso=date_iso,
    )

    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()

# === ПАГИНАЦИЯ НЕДЕЛЬ ===

@router.callback_query(SearchClassWeekCD.filter())
async def nav_class_week(
    callback: CallbackQuery,
    callback_data: SearchClassWeekCD,
    schedule_service: ScheduleService,
):
    class_id = callback_data.class_id
    week_start_iso = callback_data.week_start_iso

    class_name = await schedule_service.get_class_name(class_id)

    text = UIRenderer.render_search_day_select(class_name)

    kb = Keyboards.get_search_days_kb(
        target_id=class_id,
        is_teacher=False,
        week_start_iso=week_start_iso,
    )

    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(SearchTeacherWeekCD.filter())
async def nav_teacher_week(
    callback: CallbackQuery,
    callback_data: SearchTeacherWeekCD,
    schedule_service: ScheduleService,
):
    teacher_id = callback_data.teacher_id
    week_start_iso = callback_data.week_start_iso

    teacher_name = await schedule_service.get_teacher_name(
        teacher_id,
    )

    text = UIRenderer.render_search_day_select(teacher_name)

    kb = Keyboards.get_search_days_kb(
        target_id=teacher_id,
        is_teacher=True,
        week_start_iso=week_start_iso,
    )

    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


# === ВЫВОД РАСПИСАНИЯ ===

@router.callback_query(SearchClassDayCD.filter())
async def show_class_schedule(
    callback: CallbackQuery,
    callback_data: SearchClassDayCD,
    schedule_service: ScheduleService,
):
    class_id = callback_data.class_id
    date_iso = callback_data.date_iso

    day_dto = await schedule_service.get_daily_schedule_for_class(
        class_id,
        date_iso,
    )

    class_name = await schedule_service.get_class_name(class_id)

    text, _ = UIRenderer.render_day_schedule(day_dto)
    text = f"🎓 <b>Расписание: {class_name}</b>\n" + text

    has_changes = any(
        lesson.is_exchange or lesson.is_cancelled
        for lesson in day_dto.lessons
    )

    date_obj = TimeService.date_from_iso(date_iso)
    monday = date_obj - timedelta(
        days=date_obj.isoweekday() - 1,
    )

    kb = Keyboards.get_search_days_kb(
        target_id=class_id,
        is_teacher=False,
        week_start_iso=monday.isoformat(),
        is_full=False,
        has_changes=has_changes,
        date_iso=date_iso,
    )

    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(SearchTeacherDayCD.filter())
async def show_teacher_schedule(
    callback: CallbackQuery,
    callback_data: SearchTeacherDayCD,
    schedule_service: ScheduleService,
) -> None:
    teacher_id = callback_data.teacher_id
    date_iso = callback_data.date_iso

    day_dto = (
        await schedule_service.get_daily_schedule_for_teacher(
            teacher_id,
            date_iso,
        )
    )

    teacher_name = await schedule_service.get_teacher_name(
        teacher_id,
    )

    text, _ = UIRenderer.render_day_schedule(day_dto)
    text = f"👨‍🏫 <b>Расписание: {teacher_name}</b>\n" + text

    has_changes = any(
        lesson.is_exchange or lesson.is_cancelled
        for lesson in day_dto.lessons
    )

    date_obj = TimeService.date_from_iso(date_iso)
    monday = date_obj - timedelta(
        days=date_obj.isoweekday() - 1,
    )

    kb = Keyboards.get_search_days_kb(
        target_id=teacher_id,
        is_teacher=True,
        week_start_iso=monday.isoformat(),
        is_full=False,
        has_changes=has_changes,
        date_iso=date_iso,
    )

    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()

# === ПОЛНАЯ НЕДЕЛЯ ===

@router.callback_query(SearchClassFullWeekCD.filter())
async def show_class_full_week(
    callback: CallbackQuery,
    callback_data: SearchClassFullWeekCD,
    schedule_service: ScheduleService,
):
    class_id = callback_data.class_id
    week_start_iso = callback_data.week_start_iso

    class_name = await schedule_service.get_class_name(class_id)

    full_dto = (
        await schedule_service.get_full_week_schedule_for_class(
            class_id,
            week_start_iso,
        )
    )

    text, _ = UIRenderer.render_full_week_schedule(full_dto)
    text = f"🎓 <b>Вся неделя: {class_name}</b>\n\n{text}"

    kb = Keyboards.get_search_days_kb(
        target_id=class_id,
        is_teacher=False,
        week_start_iso=week_start_iso,
        is_full=True,
    )

    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(SearchTeacherFullWeekCD.filter())
async def show_teacher_full_week(
    callback: CallbackQuery,
    callback_data: SearchTeacherFullWeekCD,
    schedule_service: ScheduleService,
):
    teacher_id = callback_data.teacher_id
    week_start_iso = callback_data.week_start_iso

    teacher_name = await schedule_service.get_teacher_name(
        teacher_id,
    )

    full_dto = (
        await schedule_service.get_full_week_schedule_for_teacher(
            teacher_id,
            week_start_iso,
        )
    )

    text, _ = UIRenderer.render_full_week_schedule(full_dto)
    text = (
        f"👨‍🏫 <b>Вся неделя: {teacher_name}</b>\n\n"
        f"{text}"
    )

    kb = Keyboards.get_search_days_kb(
        target_id=teacher_id,
        is_teacher=True,
        week_start_iso=week_start_iso,
        is_full=True,
    )

    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()