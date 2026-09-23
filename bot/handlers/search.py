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
from datetime import timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot import callbacks
from bot.callbacks import (
    SearchClassCD, SearchRoomCD, SearchRoomWeekCD, SearchRoomDayCD,
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
from core.models.dto import ClassListDTO, TeacherListDTO
from bot.utils.safe_send import send_or_edit_long

logger = logging.getLogger(__name__)
router = Router()


# ==========================================================
# ПОИСК: МЕНЮ И СПИСКИ
# ==========================================================

@router.callback_query(F.data == callbacks.SEARCH_BACK)
async def search_back(callback: CallbackQuery):
    text = UIRenderer.render_school_search_menu()
    kb = Keyboards.get_school_search_kb()
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


@router.callback_query(F.data == callbacks.SEARCH_CLASSES)
async def search_classes(callback: CallbackQuery, schedule_service: ScheduleService):
    class_dto: ClassListDTO = await schedule_service.get_classes_list()
    text = UIRenderer.render_search_class_select()
    kb = Keyboards.get_search_classes_kb(class_dto)
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


@router.callback_query(F.data == callbacks.SEARCH_TEACHERS)
async def search_teachers(callback: CallbackQuery, schedule_service: ScheduleService):
    teacher_dto: TeacherListDTO = await schedule_service.get_teachers_list()
    text = UIRenderer.render_search_teacher_select()
    kb = Keyboards.get_search_teachers_kb(teacher_dto)
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()

@router.callback_query(callbacks.SearchTeacherPageCD.filter())
async def paginate_teachers_list(
    callback: CallbackQuery, 
    callback_data: callbacks.SearchTeacherPageCD,
    schedule_service: ScheduleService):
    """Тонкий хендлер для перелистывания страниц учителей"""
    teacher_dto = await schedule_service.get_teachers_list()
    text = UIRenderer.render_search_teacher_select()
    kb = Keyboards.get_search_teachers_kb(teacher_dto, page=callback_data.page)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == callbacks.IGNORE_ACTION)
async def ignore_pagination_counter(callback: CallbackQuery):
    """Гасит нажатие на центральную информационную кнопку пагинации [ 1 / 5 ]."""
    await callback.answer()
    
# ==========================================================
# ПОИСК: ВЫБОР ЦЕЛИ (УМНЫЕ ДНИ)
# ==========================================================

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
    target_date = time_service.date_from_iso(date_iso)
    # 2. Получаем расписание на найденный день    
    day_dto = await schedule_service.get_daily_schedule_for_class(class_id, date_iso)

    text, _ = UIRenderer.render_day_schedule(day_dto)
    text = f"🎓 <b>Расписание: {class_name}</b>\n" + text

    # 3. Проверяем наличие замен
    has_changes = any(lesson.is_exchange or lesson.is_cancelled for lesson in day_dto.lessons)

    # 4. ИСПРАВЛЕНИЕ: monday уже date, просто вызываем isoformat()
    kb = Keyboards.get_search_day_kb(
        target_id=class_id,
        is_teacher=False,
        current_date_iso=date_iso,
        has_changes=has_changes,
    )
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
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

    date_iso = await schedule_service.get_smart_teacher_target_date(teacher_id=teacher_id)
    target_date = time_service.date_from_iso(date_iso)
    day_dto = await schedule_service.get_daily_schedule_for_teacher(teacher_id, date_iso)

    text, _ = UIRenderer.render_day_schedule(day_dto)
    text = f"👨‍🏫 <b>Расписание: {teacher_name}</b>\n{text}"

    has_changes = any(lesson.is_exchange or lesson.is_cancelled for lesson in day_dto.lessons)

    kb = Keyboards.get_search_day_kb(
        target_id=teacher_id,
        is_teacher=True,
        current_date_iso=date_iso,
        has_changes=has_changes,
    )
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


# ==========================================================
# ПАГИНАЦИЯ НЕДЕЛЬ
# ==========================================================

@router.callback_query(SearchClassWeekCD.filter())
async def nav_class_week(
    callback: CallbackQuery,
    callback_data: SearchClassWeekCD,
    schedule_service: ScheduleService,
):
    class_id = callback_data.class_id
    week_start_iso = callback_data.week_start_iso
    class_name = await schedule_service.get_class_name(class_id)

    # Запрашиваем сводку и рендерим
    summary_dto = await schedule_service.get_class_week_schedule_summary(class_id, week_start_iso)
    text, _ = UIRenderer.render_week_summary(summary_dto)
    text = f"🎓 <b>{class_name}</b>\n{text}"
    
    kb = Keyboards.get_search_days_kb(
        target_id=class_id,
        is_teacher=False,
        week_start_iso=week_start_iso,
    )

    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


@router.callback_query(SearchTeacherWeekCD.filter())
async def nav_teacher_week(
    callback: CallbackQuery,
    callback_data: SearchTeacherWeekCD,
    schedule_service: ScheduleService,
):
    teacher_id = callback_data.teacher_id
    week_start_iso = callback_data.week_start_iso
    teacher_name = await schedule_service.get_teacher_name(teacher_id)
    # Запрашиваем сводку и рендерим
    summary_dto = await schedule_service.get_teacher_week_schedule_summary(
        teacher_id=teacher_id, week_start_iso=week_start_iso
    )
    text, _ = UIRenderer.render_week_summary(summary_dto)
    text = f"👨‍🏫 <b>{teacher_name}</b>\n{text}"
    kb = Keyboards.get_search_days_kb(
        target_id=teacher_id,
        is_teacher=True,
        week_start_iso=week_start_iso,
    )

    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


# ==========================================================
# ВЫВОД РАСПИСАНИЯ ДНЯ
# ==========================================================

@router.callback_query(SearchClassDayCD.filter())
async def show_class_schedule(
    callback: CallbackQuery,
    callback_data: SearchClassDayCD,
    schedule_service: ScheduleService,
    time_service: TimeService,
):
    class_id = callback_data.class_id
    date_iso = callback_data.date_iso

    day_dto = await schedule_service.get_daily_schedule_for_class(class_id, date_iso)
    class_name = await schedule_service.get_class_name(class_id)

    text, _ = UIRenderer.render_day_schedule(day_dto)
    text = f"🎓 <b>Расписание: {class_name}</b>\n" + text

    has_changes = any(lesson.is_exchange or lesson.is_cancelled for lesson in day_dto.lessons)
    date_obj = time_service.date_from_iso(date_iso)

    kb = Keyboards.get_search_day_kb(
        target_id=class_id,
        is_teacher=False,
        current_date_iso=date_iso,
        has_changes=has_changes,
    )
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


@router.callback_query(SearchTeacherDayCD.filter())
async def show_teacher_schedule(
    callback: CallbackQuery,
    callback_data: SearchTeacherDayCD,
    schedule_service: ScheduleService,
    time_service: TimeService,
) -> None:
    teacher_id = callback_data.teacher_id
    date_iso = callback_data.date_iso

    day_dto = await schedule_service.get_daily_schedule_for_teacher(teacher_id, date_iso)
    teacher_name = await schedule_service.get_teacher_name(teacher_id)

    text, _ = UIRenderer.render_day_schedule(day_dto)
    text = f"👨‍🏫 <b>Расписание: {teacher_name}</b>\n" + text

    has_changes = any(lesson.is_exchange or lesson.is_cancelled for lesson in day_dto.lessons)
    date_obj = time_service.date_from_iso(date_iso)

    kb = Keyboards.get_search_day_kb(
        target_id=teacher_id,
        is_teacher=True,
        current_date_iso=date_iso,
        has_changes=has_changes,
    )
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


# ==========================================================
# ПОЛНАЯ НЕДЕЛЯ
# ==========================================================

@router.callback_query(SearchClassFullWeekCD.filter())
async def show_class_full_week(
    callback: CallbackQuery,
    callback_data: SearchClassFullWeekCD,
    schedule_service: ScheduleService,
):
    class_id = callback_data.class_id
    week_start_iso = callback_data.week_start_iso

    class_name = await schedule_service.get_class_name(class_id)
    full_dto = await schedule_service.get_full_week_schedule_for_class(class_id, week_start_iso)

    text, _ = UIRenderer.render_full_week_schedule(full_dto)
    text = f"🎓 <b>Вся неделя: {class_name}</b>\n\n{text}"

    kb = Keyboards.get_search_days_kb(
        target_id=class_id,
        is_teacher=False,
        week_start_iso=week_start_iso,
        is_full=True,
    )

    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


@router.callback_query(SearchTeacherFullWeekCD.filter())
async def show_teacher_full_week(
    callback: CallbackQuery,
    callback_data: SearchTeacherFullWeekCD,
    schedule_service: ScheduleService,
):
    teacher_id = callback_data.teacher_id
    week_start_iso = callback_data.week_start_iso

    teacher_name = await schedule_service.get_teacher_name(teacher_id)
    full_dto = await schedule_service.get_full_week_schedule_for_teacher(teacher_id, week_start_iso)

    text, _ = UIRenderer.render_full_week_schedule(full_dto)
    text = f"👨‍🏫 <b>Вся неделя: {teacher_name}</b>\n\n{text}"

    kb = Keyboards.get_search_days_kb(
        target_id=teacher_id,
        is_teacher=True,
        week_start_iso=week_start_iso,
        is_full=True,
    )

    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


# ==========================================================
# ПОИСК КАБИНЕТОВ
# ==========================================================

@router.callback_query(F.data == callbacks.SEARCH_ROOMS_MENU)
async def search_rooms_menu(callback: CallbackQuery):
    text = UIRenderer.render_rooms_main_menu()
    kb = Keyboards.get_search_rooms_menu_kb()
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


@router.callback_query(F.data == callbacks.FREE_ROOMS_NOW)
async def show_free_rooms_now(callback: CallbackQuery, schedule_service: ScheduleService):
    status_dto, free_rooms = await schedule_service.get_currently_free_rooms()
    text = UIRenderer.render_free_rooms_now(status_dto, free_rooms)
    kb = Keyboards.get_free_rooms_now_kb(free_rooms)
    
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()
    

@router.callback_query(F.data == callbacks.SEARCH_ROOMS_GRID)
async def search_rooms_grid(callback: CallbackQuery, schedule_service: ScheduleService):
    room_dto = await schedule_service.get_rooms_list()
    text = UIRenderer.render_search_room_select()
    kb = Keyboards.get_search_rooms_grid_kb(room_dto)
    
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


@router.callback_query(SearchRoomCD.filter())
async def select_room_day(
    callback: CallbackQuery, 
    callback_data: SearchRoomCD, 
    schedule_service: ScheduleService, 
    time_service: TimeService
):
    room_id = callback_data.room_id
    
    date_iso = await schedule_service.get_smart_room_target_date(room_id)
    target_date = time_service.date_from_iso(date_iso)
    day_dto = await schedule_service.get_daily_schedule_for_room(room_id, date_iso)

    text = UIRenderer.render_room_day_schedule(day_dto, target_date.strftime('%d.%m'))

    kb = Keyboards.get_search_day_kb(
        target_id=room_id, 
        is_teacher=False, 
        is_room=True, 
        current_date_iso=date_iso,
        return_to=callback_data.return_to
    )
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


@router.callback_query(SearchRoomDayCD.filter())
async def show_room_schedule(
    callback: CallbackQuery,
    callback_data: SearchRoomDayCD,
    schedule_service: ScheduleService,
    time_service: TimeService
):
    room_id, date_iso = callback_data.room_id, callback_data.date_iso
    target_date = time_service.date_from_iso(date_iso)
    
    day_dto = await schedule_service.get_daily_schedule_for_room(room_id, date_iso)
    text = UIRenderer.render_room_day_schedule(day_dto, target_date.strftime('%d.%m'))
    
    kb = Keyboards.get_search_day_kb(
        target_id=room_id, 
        is_teacher=False, 
        is_room=True, 
        current_date_iso=date_iso,
        return_to=callback_data.return_to
    )
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()


@router.callback_query(SearchRoomWeekCD.filter())
async def nav_room_week(
    callback: CallbackQuery, 
    callback_data: SearchRoomWeekCD,
    schedule_service: ScheduleService
):
    room_id = callback_data.room_id
    room_name = await schedule_service.get_room_name(room_id)

    # Запрашиваем сводку и рендерим
    summary_dto = await schedule_service.get_room_week_schedule_summary(room_id, callback_data.week_start_iso)
    text, _ = UIRenderer.render_week_summary(summary_dto)
    text = f"🚪 <b>Кабинет {room_name}</b>\n{text}"
    kb = Keyboards.get_search_days_kb(
        target_id=room_id, 
        is_teacher=False, 
        week_start_iso=callback_data.week_start_iso,
        is_room=True,
        return_to=callback_data.return_to
    )
    
    await send_or_edit_long(callback=callback, text=text, keyboard=kb)
    await callback.answer()