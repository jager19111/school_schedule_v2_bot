# bot/handlers/schedule_teacher.py
#
# ЭТАП 4: парсинг callback_data через bot/callbacks.py
# (teacher_sched:*). Формат строк на проводе не изменён.
#
# Ручная проверка len(text) > 3900 помечена TODO — её закроет
# общий хелпер длины сообщений (следующий подэтап).

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from bot import callbacks
from bot.keyboards.keyboard import Keyboards
from bot.utils.ui_renderer import UIRenderer
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from bot.utils.safe_send import send_or_edit_long

logger = logging.getLogger(__name__)
router = Router()


async def _safe_edit_teacher_schedule(
    callback: CallbackQuery,
    text: str,
    keyboard,
) -> None:
    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        logger.debug(
            "Teacher schedule edit skipped: %s",
            exc,
        )


async def _get_teacher_profile(
    *,
    user_id: int,
    profile_service: ProfileService,
):
    """
    Возвращает teacher user profile только при корректной регистрации.
    """
    user = await profile_service.get_user_profile_dto(
        user_id,
    )
    if user.role != "teacher":
        return None
    if not user.teacher_id:
        return None
    return user


async def _teacher_name(
    *,
    teacher_id: str,
    schedule_service: ScheduleService,
    fallback: str,
) -> str:
    """
    Получает имя учителя из metadata NIKA.
    """
    teachers_dto = await schedule_service.get_teachers_list()
    return str(
        teachers_dto.teachers.get(
            teacher_id,
            fallback,
        )
    )


async def _render_teacher_day(
    *,
    teacher_id: str,
    date_iso: str,
    teacher_name: str,
    schedule_service: ScheduleService,
) -> tuple[str, object]:
    """
    Рендерит дневное расписание teacher profile.
    """
    day_dto = await schedule_service.get_daily_schedule_for_teacher(
        teacher_id=teacher_id,
        date_iso=date_iso,
    )
    rendered = UIRenderer.render_child_day_schedule(
        day_dto,
        None,
    )
    text = (
        rendered[0]
        if isinstance(rendered, tuple)
        else rendered
    )
    text = (
        "👨‍🏫 <b>Расписание учителя</b>\n"
        f"👤 {UIRenderer.escape_html(teacher_name)}\n\n"
        f"{text}"
    )
    keyboard = Keyboards.get_teacher_schedule_day_kb(
        current_date_iso=date_iso,
    )
    return text, keyboard


async def _render_teacher_week(
    *,
    teacher_id: str,
    week_start_iso: str,
    teacher_name: str,
    schedule_service: ScheduleService,
    is_full: bool,
) -> tuple[str, object]:
    """
    Рендерит краткую или полную неделю teacher profile.
    """
    if is_full:
        dto = await schedule_service.get_full_week_schedule_for_teacher(
            teacher_id=teacher_id,
            week_start_iso=week_start_iso,
        )
        rendered = UIRenderer.render_full_week_schedule(
            dto,
        )
    else:
        dto = await schedule_service.get_teacher_week_schedule_summary(
            teacher_id=teacher_id,
            week_start_iso=week_start_iso,
        )
        rendered = UIRenderer.render_week_summary(
            dto,
        )
    text = (
        rendered[0]
        if isinstance(rendered, tuple)
        else rendered
    )
    text = (
        "👨‍🏫 <b>Расписание учителя</b>\n"
        f"👤 {UIRenderer.escape_html(teacher_name)}\n\n"
        f"{text}"
    )
    keyboard = Keyboards.get_teacher_schedule_week_kb(
        week_start_iso=week_start_iso,
        is_full=is_full,
    )
    return text, keyboard


async def open_teacher_schedule_for_message(
    *,
    message: Message,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> bool:
    """
    Открывает personal Schedule Hub учителя.

    Это helper, а не aiogram message handler.
    Единственная точка входа «📅 Моё расписание»
    находится в schedule_child.py и dispatch-ит по role.
    """
    teacher = await _get_teacher_profile(
        user_id=message.from_user.id,
        profile_service=profile_service,
    )
    if teacher is None:
        return False
    teacher_name = await _teacher_name(
        teacher_id=teacher.teacher_id,
        schedule_service=schedule_service,
        fallback=teacher.name or "Учитель",
    )
    target_date_iso = (
        await schedule_service.get_smart_teacher_target_date(
            teacher_id=teacher.teacher_id,
        )
    )
    text, keyboard = await _render_teacher_day(
        teacher_id=teacher.teacher_id,
        date_iso=target_date_iso,
        teacher_name=teacher_name,
        schedule_service=schedule_service,
    )
    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return True


@router.callback_query(
    F.data == callbacks.TEACHER_SCHED_SMART_DAY
)
async def teacher_schedule_smart_day(
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    teacher = await _get_teacher_profile(
        user_id=callback.from_user.id,
        profile_service=profile_service,
    )
    if teacher is None:
        await callback.answer(
            "Сессия учителя недоступна. "
            "Откройте расписание заново.",
            show_alert=True,
        )
        return
    teacher_name = await _teacher_name(
        teacher_id=teacher.teacher_id,
        schedule_service=schedule_service,
        fallback=teacher.name or "Учитель",
    )
    target_date_iso = (
        await schedule_service.get_smart_teacher_target_date(
            teacher_id=teacher.teacher_id,
        )
    )
    text, keyboard = await _render_teacher_day(
        teacher_id=teacher.teacher_id,
        date_iso=target_date_iso,
        teacher_name=teacher_name,
        schedule_service=schedule_service,
    )
    await _safe_edit_teacher_schedule(
        callback,
        text,
        keyboard,
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith(callbacks.TEACHER_SCHED_DAY_PREFIX)
)
async def teacher_schedule_day(
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    # Этап 4: парсинг — в callbacks.parse_teacher_sched_day.
    date_iso = callbacks.parse_teacher_sched_day(callback.data)
    if date_iso is None:
        await callback.answer(
            "Некорректная дата.",
            show_alert=True,
        )
        return
    teacher = await _get_teacher_profile(
        user_id=callback.from_user.id,
        profile_service=profile_service,
    )
    if teacher is None:
        await callback.answer(
            "Сессия учителя недоступна.",
            show_alert=True,
        )
        return
    teacher_name = await _teacher_name(
        teacher_id=teacher.teacher_id,
        schedule_service=schedule_service,
        fallback=teacher.name or "Учитель",
    )
    text, keyboard = await _render_teacher_day(
        teacher_id=teacher.teacher_id,
        date_iso=date_iso,
        teacher_name=teacher_name,
        schedule_service=schedule_service,
    )
    await _safe_edit_teacher_schedule(
        callback,
        text,
        keyboard,
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith(callbacks.TEACHER_SCHED_WEEK_PREFIX)
)
async def teacher_schedule_week(
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    # Этап 4: парсинг — в callbacks.parse_teacher_sched_week.
    week_start_iso = callbacks.parse_teacher_sched_week(callback.data)
    if week_start_iso is None:
        await callback.answer(
            "Некорректная дата недели.",
            show_alert=True,
        )
        return
    teacher = await _get_teacher_profile(
        user_id=callback.from_user.id,
        profile_service=profile_service,
    )
    if teacher is None:
        await callback.answer(
            "Сессия учителя недоступна.",
            show_alert=True,
        )
        return
    teacher_name = await _teacher_name(
        teacher_id=teacher.teacher_id,
        schedule_service=schedule_service,
        fallback=teacher.name or "Учитель",
    )
    text, keyboard = await _render_teacher_week(
        teacher_id=teacher.teacher_id,
        week_start_iso=week_start_iso,
        teacher_name=teacher_name,
        schedule_service=schedule_service,
        is_full=False,
    )
    await _safe_edit_teacher_schedule(
        callback,
        text,
        keyboard,
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith(callbacks.TEACHER_SCHED_FULL_WEEK_PREFIX)
)
async def teacher_schedule_full_week(
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    week_start_iso = callbacks.parse_teacher_sched_full_week(callback.data)
    if week_start_iso is None:
        await callback.answer(
            "Некорректная дата недели.",
            show_alert=True,
        )
        return

    teacher = await _get_teacher_profile(
        user_id=callback.from_user.id,
        profile_service=profile_service,
    )
    if teacher is None:
        await callback.answer(
            "Сессия учителя недоступна.",
            show_alert=True,
        )
        return

    teacher_name = await _teacher_name(
        teacher_id=teacher.teacher_id,
        schedule_service=schedule_service,
        fallback=teacher.name or "Учитель",
    )

    text, keyboard = await _render_teacher_week(
        teacher_id=teacher.teacher_id,
        week_start_iso=week_start_iso,
        teacher_name=teacher_name,
        schedule_service=schedule_service,
        is_full=True,
    )

    # Этап 4.6: авторазбиение вместо отказа
    delivered = await send_or_edit_long(
        callback=callback,
        text=text,
        keyboard=keyboard,
    )
    if not delivered:
        logger.warning(
            "Teacher full week delivery failed: "
            "teacher_id=%s week=%s",
            teacher.teacher_id,
            week_start_iso,
        )

    await callback.answer()
