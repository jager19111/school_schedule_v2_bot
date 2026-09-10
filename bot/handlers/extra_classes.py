# bot/handlers/extra_classes.py
#
# ЭТАП 7: нативный aiogram CallbackData (Extra*CD).
# Формат строк на проводе изменён: xm/xl/xa/xe/xd/xy/xf.
#
# Дополнительно: process_day/process_edit_day/choose_edit_field раньше
# парсили аргументы без try/except (битая строка роняла хендлер);
# теперь parse-методы возвращают None и пользователь получает alert.

import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest

from bot import callbacks
from bot.callbacks import (
    ExtraAddCD,
    ExtraDayCD,
    ExtraDeleteCD,
    ExtraEditCD,
    ExtraEditFieldCD,
    ExtraListCD,
    ExtraMenuCD,
)
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from services.time_service import TimeService
from services.extra_classes_service import ExtraClassesService
from services.profiles_service import ProfileService
from services.students_service import StudentsService
from services.schedule_service import ScheduleService
from bot.utils.fsm_guard import validate_fsm_session
from services.extra_classes_service import ExtraClassesService
from core.models.dto import ExtraClassViewModel
       
logger = logging.getLogger(__name__)
router = Router()


# Хелпер для проверки прав доступа к доп. занятиям
async def _show_extra_menu_for_student(
    *,
    message_obj: Message,
    actor_user_id: int,
    target_student_id: int,
    extra_classes_service: ExtraClassesService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
    edit_message: bool,
    prefix: str = "",
) -> bool:
    """
    Показывает меню дополнительных занятий student profile.

    Service проверяет actor access. Handler дополнительно получает
    student profile только для корректного отображения имени, класса
    и Telegram-статуса.
    """
    access = await extra_classes_service.get_access(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
    )
    if not access.can_view:
        return False

    student = None
    actor_access = await students_service.get_student_for_adult(
        adult_user_id=actor_user_id,
        student_id=target_student_id,
    )
    if actor_access is not None:
        student, _student_access = actor_access
        # Parent / observer: может перейти к selector своих учеников.
        can_switch_student = True
    else:
        student = await students_service.get_student_by_telegram_user_id(
            telegram_user_id=actor_user_id,
        )
        if (
            student is None
            or student.id != target_student_id
            or not student.is_active
        ):
            return False
        # Child: только собственный student_profile.
        can_switch_student = False

    # Запрашиваем справочники школы единым запросом через ScheduleServiceV2
    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = StudentsService.build_student_view_model(student, dicts_dto)
    text, _ = UIRenderer.render_student_extra_classes_menu(vm)
    
    if prefix:
        text = f"{prefix}\n\n{text}"

    keyboard = Keyboards.get_extra_classes_menu(
        target_student_id=target_student_id,
        can_add=access.can_manage,
        can_edit=access.can_manage,
        can_switch_student=can_switch_student,
    )

    try:
        if edit_message:
            await message_obj.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await message_obj.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
    except Exception as exc:
        logger.warning(
            "Unable to render extra menu: "
            "actor_id=%s student_id=%s error=%s",
            actor_user_id,
            target_student_id,
            exc,
        )

    return True


async def _require_extra_manage_access(
    *,
    actor_user_id: int,
    target_student_id: int,
    extra_classes_service: ExtraClassesService,
) -> bool:
    """
    Проверяет право редактировать допзанятия конкретного ученика.
    """
    access = await extra_classes_service.get_access(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
    )
    return access.can_manage


class ExtraClassStates(StatesGroup):
    waiting_for_day = State()
    waiting_for_time_start = State()
    waiting_for_time_end = State()
    waiting_for_title = State()
    waiting_for_location = State()
    waiting_for_reminder = State()
    waiting_for_delete_id = State()
    waiting_for_edit_id = State()
    waiting_for_edit_value = State()
    waiting_for_edit_time_end = State()


# === ГЛАВНОЕ МЕНЮ И УМНАЯ МАРШРУТИЗАЦИЯ ===

@router.message(F.text == "➕ Доп. занятия")
async def show_extra_menu(
    message: Message,
    profile_service: ProfileService,
    students_service: StudentsService,
    extra_classes_service: ExtraClassesService,
    schedule_service: ScheduleService,
) -> None:
    """
    Открывает допзанятия.

    child:
    - открывает только свой связанный student profile.
    parent/observer:
    - выбирает любой доступный student profile,
      включая virtual student.
    """
    actor_user_id = message.from_user.id
    actor = await profile_service.get_user_profile_dto(
        actor_user_id,
    )
    # Защита
    if not actor.is_fully_registered:
        await message.answer(UIRenderer.render_unregistered_error())
        return

    if actor.role == "child":
        student = (
            await students_service.get_student_by_telegram_user_id(
                telegram_user_id=actor_user_id,
            )
        )
        if student is None or not student.is_active:
            await message.answer(
                "❌ Для вашего Telegram-профиля не найден "
                "активный профиль ученика."
            )
            return
        shown = await _show_extra_menu_for_student(
            message_obj=message,
            actor_user_id=actor_user_id,
            target_student_id=student.id,
            extra_classes_service=extra_classes_service,
            students_service=students_service,
            schedule_service=schedule_service,
            edit_message=False,
        )
        if not shown:
            await message.answer(
                "❌ Не удалось определить доступ "
                "к дополнительным занятиям."
            )
        return

    if actor.role not in ("parent", "observer"):
        await message.answer(
            "❌ Дополнительные занятия доступны детям, "
            "родителям и наблюдателям."
        )
        return

    students = await students_service.get_students_for_adult(
        adult_user_id=actor_user_id,
    )
    if not students:
        text, _ = UIRenderer.render_extra_no_children()
        await message.answer(
            text,
            parse_mode="HTML",
        )
        return

    if len(students) == 1:
        shown = await _show_extra_menu_for_student(
            message_obj=message,
            actor_user_id=actor_user_id,
            target_student_id=students[0].id,
            extra_classes_service=extra_classes_service,
            students_service=students_service,
            schedule_service=schedule_service,
            edit_message=False,
        )
        if not shown:
            await message.answer(
                "❌ У вас нет доступа к занятиям ученика."
            )
        return

    # 1. Запрашиваем справочники школы единым запросом
    dicts_dto = await schedule_service.get_school_dictionaries()
    view_models = StudentsService.build_student_view_models(
        students,
        dicts_dto,
    )
    text, _ = UIRenderer.render_extra_student_select()
    keyboard = Keyboards.get_extra_students_select_kb(
        view_models,
    )
    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(F.data == callbacks.EXTRA_STUDENTS)
async def show_extra_students(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Показывает selector student profiles взрослого.

    Ребёнок не выбирает чужие профили: для него selector не нужен.
    """
    await state.clear()
    actor_user_id = callback.from_user.id
    actor = await profile_service.get_user_profile_dto(
        actor_user_id,
    )
    if actor.role not in ("parent", "observer"):
        await callback.answer(
            "Смена ученика доступна только взрослым.",
            show_alert=True,
        )
        return
    students = await students_service.get_students_for_adult(
        adult_user_id=actor_user_id,
    )
    if not students:
        text, _ = UIRenderer.render_extra_no_children()
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
        )
        await callback.answer()
        return
    # 1. Запрашиваем справочники школы единым запросом
    dicts_dto = await schedule_service.get_school_dictionaries()
    view_models = StudentsService.build_student_view_models(
        students,
        dicts_dto,
    )
    text, _ = UIRenderer.render_extra_student_select()
    keyboard = Keyboards.get_extra_students_select_kb(
        view_models,
    )
    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(ExtraMenuCD.filter())
async def show_extra_menu_cb(
    callback: CallbackQuery,
    callback_data: ExtraMenuCD,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Открывает меню занятий выбранного student profile.
    """
    await state.clear()
    target_student_id = callback_data.student_id
    shown = await _show_extra_menu_for_student(
        message_obj=callback.message,
        actor_user_id=callback.from_user.id,
        target_student_id=target_student_id,
        extra_classes_service=extra_classes_service,
        students_service=students_service,
        schedule_service=schedule_service,
        edit_message=True,
    )
    if not shown:
        await callback.answer(
            "У вас нет доступа к занятиям этого ученика.",
            show_alert=True,
        )
        return
    await callback.answer()


@router.callback_query(F.data == callbacks.EXTRA_CANCEL)
async def cancel_action(
    callback: CallbackQuery,
    state: FSMContext,
    students_service: StudentsService,
    extra_classes_service: ExtraClassesService,
    schedule_service: ScheduleService,
) -> None:
    """Отменяет FSM-действие и возвращает к меню (или безопасно гасит карточку)."""
    data = await state.get_data()
    target_student_id = data.get("target_student_id")
    
    # Безусловно чистим состояние
    await state.clear()
    
    # СЦЕНАРИЙ 1: FSM уже был пуст (сессия устарела)
    if not target_student_id:
        # Убираем всплывающий алерт. Просто гасим сообщение.
        try:
            await callback.message.edit_text(
                "❌ Действие отменено.\n\n"
                "<i>Откройте меню дополнительных занятий заново.</i>",
                reply_markup=None,
                parse_mode="HTML"
            )
        except Exception:
            pass # Игнорируем, если сообщение уже удалено
            
        await callback.answer() # Тихий ответ без show_alert=True
        return

    # СЦЕНАРИЙ 2: FSM был жив, возвращаем меню ученика
    shown = await _show_extra_menu_for_student(
        message_obj=callback.message,
        actor_user_id=callback.from_user.id,
        target_student_id=target_student_id,
        extra_classes_service=extra_classes_service,
        students_service=students_service,
        schedule_service=schedule_service,
        edit_message=True,
        prefix="❌ Действие отменено.",
    )
    
    # СЦЕНАРИЙ 3: Меню недоступно (например, убрали права доступа)
    if not shown:
        try:
            await callback.message.edit_text(
                "❌ Действие отменено. Меню занятий больше недоступно.",
                reply_markup=None,
                parse_mode="HTML"
            )
        except Exception:
            pass
            
    await callback.answer() # Тихий ответ во всех случаях


# === СПИСОК И УДАЛЕНИЕ ===

@router.callback_query(ExtraListCD.filter())
async def show_extra_list(
    callback: CallbackQuery,
    callback_data: ExtraListCD,
    extra_classes_service: ExtraClassesService,
) -> None:
    """Показывает занятия ребёнка только при наличии view-права."""
    target_student_id = callback_data.student_id
    response = await extra_classes_service.get_student_extra_classes(
        actor_user_id=callback.from_user.id,
        target_student_id=target_student_id,
    )
    if not response.success:
        await callback.answer(
            "У вас нет доступа к занятиям этого ученика.",
            show_alert=True,
        )
        return
    view_models = ExtraClassesService.build_view_models(
        response.data.items,
    )
    text, _ = UIRenderer.render_extra_classes_list(view_models)
    try:
        await callback.message.edit_text(
            text,
            reply_markup=Keyboards.get_back_to_extra_menu(
                target_student_id,
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning(
            "Failed to show extra classes list: actor_id=%s target_id=%s error=%s",
            callback.from_user.id,
            target_student_id,
            exc,
        )
    await callback.answer()


@router.callback_query(ExtraDeleteCD.filter())
async def start_delete_extra(
    callback: CallbackQuery,
    callback_data: ExtraDeleteCD,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
) -> None:
    """Запускает удаление занятия при наличии manage-права."""
    target_student_id = callback_data.student_id
    actor_user_id = callback.from_user.id
    can_manage = await _require_extra_manage_access(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_classes_service=extra_classes_service,
    )
    if not can_manage:
        await callback.answer(
            "🔒 У вас нет права удалять занятия этого ученика.",
            show_alert=True,
        )
        return
    list_response = await extra_classes_service.get_student_extra_classes(
        actor_user_id=callback.from_user.id,
        target_student_id=target_student_id,
    )
    if not list_response.success:
        await callback.answer(
            "У вас нет доступа к занятиям ребёнка.",
            show_alert=True,
        )
        return
    view_models = ExtraClassesService.build_view_models(
        list_response.data.items,
    )
    if not view_models:
        text, _ = UIRenderer.render_extra_class_delete_prompt(view_models)
        await callback.message.edit_text(
            text,
            reply_markup=Keyboards.get_back_to_extra_menu(
                target_student_id,
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    await state.update_data(
        target_student_id=target_student_id,
        extra_actor_user_id=actor_user_id,
    )
    text, _ = UIRenderer.render_extra_class_delete_prompt(view_models)
    await callback.message.edit_text(
        text,
        reply_markup=Keyboards.get_cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(ExtraClassStates.waiting_for_delete_id)
    await callback.answer()


@router.callback_query(F.data == callbacks.EXTRA_BACK)
async def close_extra_menu(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Закрывает личное меню допзанятий ребёнка.

    Нижнее ReplyKeyboardMarkup уже постоянно показано в чате,
    поэтому после закрытия ребёнок возвращается к главному меню.
    """
    await state.clear()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        # Например, если сообщение уже удалено или недоступно.
        pass
    await callback.answer()


@router.message(ExtraClassStates.waiting_for_delete_id)
async def process_delete_id(
    message: Message,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """Финально удаляет занятие с повторной service-проверкой прав."""
    if not await validate_fsm_session(
        message,
        state,
        expected={"extra_actor_user_id": message.from_user.id},
        required=["target_student_id"],
    ):
        return
    data = await state.get_data()
    actor_user_id = message.from_user.id
    target_student_id = data.get("target_student_id")
    raw_extra_id = message.text.strip()
    if not raw_extra_id.isdigit():
        text, _ = UIRenderer.render_extra_class_not_found()
        await message.answer(
            text,
            reply_markup=Keyboards.get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return
    response = await extra_classes_service.delete_extra_class(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_id=int(raw_extra_id),
    )
    if not response.success:
        if response.error_code == "access_denied":
            await state.clear()
            await message.answer(
                "🔒 У вас больше нет права удалять занятия ребёнка."
            )
            return
        text, _ = UIRenderer.render_extra_class_not_found()
        await message.answer(
            text,
            reply_markup=Keyboards.get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return
    await state.clear()
    text_deleted, _ = UIRenderer.render_extra_class_deleted()
    shown = await _show_extra_menu_for_student(
        message_obj=message,
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_classes_service=extra_classes_service,
        students_service=students_service,
        schedule_service=schedule_service,
        edit_message=False,
        prefix=text_deleted,
    )
    if not shown:
        await message.answer(
            text_deleted,
            parse_mode="HTML",
        )


# === ДОБАВЛЕНИЕ ЗАНЯТИЯ ===

@router.callback_query(ExtraAddCD.filter())
async def start_add_extra(
    callback: CallbackQuery,
    callback_data: ExtraAddCD,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
) -> None:
    """Запускает FSM добавления занятия при наличии manage-права."""
    target_student_id = callback_data.student_id
    actor_user_id = callback.from_user.id
    can_manage = await _require_extra_manage_access(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_classes_service=extra_classes_service,
    )
    if not can_manage:
        await callback.answer(
            "🔒 У вас нет права добавлять занятия этому ребёнку.",
            show_alert=True,
        )
        return
    await state.update_data(
        target_student_id=target_student_id,
        extra_actor_user_id=actor_user_id,
    )
    text, _ = UIRenderer.render_extra_class_day()
    await callback.message.edit_text(
        text,
        reply_markup=Keyboards.get_day_selection_kb(),
        parse_mode="HTML",
    )
    await state.set_state(ExtraClassStates.waiting_for_day)
    await callback.answer()


@router.callback_query(
    ExtraClassStates.waiting_for_day,
    ExtraDayCD.filter(),
)
async def process_day(
    callback: CallbackQuery,
    callback_data: ExtraDayCD,
    state: FSMContext,
):
    if not await validate_fsm_session(
        callback,
        state,
        expected={"extra_actor_user_id": callback.from_user.id},
    ):
        return
    day_num = callback_data.day_of_week
    await state.update_data(day_of_week=day_num)
    text, _ = UIRenderer.render_extra_class_time_start()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard())
    await state.set_state(ExtraClassStates.waiting_for_time_start)
    await callback.answer()


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
    await state.update_data(title=message.text.strip())
    text, _ = UIRenderer.render_extra_class_location()
    await message.answer(text, reply_markup=Keyboards.get_skip_cancel_keyboard(callbacks.EXTRA_SKIP_LOCATION), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_location)


@router.callback_query(ExtraClassStates.waiting_for_location,  F.data == callbacks.EXTRA_SKIP_LOCATION,)
async def skip_location(callback: CallbackQuery, state: FSMContext):
    await state.update_data(location=None)
    text, _ = UIRenderer.render_extra_class_reminder()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_skip_cancel_keyboard(callbacks.EXTRA_SKIP_REMINDER), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_reminder)
    await callback.answer()


@router.message(ExtraClassStates.waiting_for_location)
async def process_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text.strip())
    text, _ = UIRenderer.render_extra_class_reminder()
    await message.answer(text, reply_markup=Keyboards.get_skip_cancel_keyboard(callbacks.EXTRA_SKIP_REMINDER), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_reminder)


@router.callback_query(
    ExtraClassStates.waiting_for_reminder,
    F.data == callbacks.EXTRA_SKIP_REMINDER,
)
async def skip_reminder(
    callback: CallbackQuery,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Берёт default reminder у инициатора действия.

    Virtual student не имеет Telegram users.user_id, поэтому нельзя
    читать global_extra_reminder у самого student profile.
    """
    actor_profile = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )
    reminder_minutes = actor_profile.global_extra_reminder or 30
    await finalize_extra_class(
        event=callback,
        state=state,
        extra_classes_service=extra_classes_service,
        students_service=students_service,
        schedule_service=schedule_service,
        reminder_minutes=reminder_minutes,
    )
    await callback.answer()


@router.message(ExtraClassStates.waiting_for_reminder)
async def process_reminder(
    message: Message,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
):
    reminder_text = message.text.strip()
    if not reminder_text.isdigit():
        text, _ = UIRenderer.render_extra_class_invalid_reminder()
        return await message.answer(
            text,
            reply_markup=Keyboards.get_skip_cancel_keyboard(callbacks.EXTRA_SKIP_REMINDER),
            parse_mode="HTML",
        )
    await finalize_extra_class(
        message,
        state,
        extra_classes_service,
        students_service=students_service,
        schedule_service=schedule_service,
        reminder_minutes=int(reminder_text),
    )


async def finalize_extra_class(
    event: Message | CallbackQuery,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
    reminder_minutes: int,
) -> None:
    """
    Финальное создание дополнительного занятия.

    Перед записью сервис повторно проверяет:
        actor_user_id -> target_student_id -> can_manage_extra_classes
    """
    if not await validate_fsm_session(
        event,
        state,
        expected={"extra_actor_user_id": event.from_user.id},
        required=["target_student_id"],
    ):
        return
    data = await state.get_data()
    actor_user_id = event.from_user.id
    target_student_id = data.get("target_student_id")

    response = await extra_classes_service.add_extra_class(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        day_of_week=data["day_of_week"],
        time_start=data["time_start"],
        time_end=data["time_end"],
        title=data["title"],
        location=data.get("location"),
        reminder_minutes=reminder_minutes,
    )
    if not response.success:
        await state.clear()
        if response.error_code == "access_denied":
            error_text = (
                "🔒 У вас больше нет права добавлять занятия этому ребёнку."
            )
        elif response.error_code == "invalid_time_range":
            error_text = (
                "❌ Время окончания должно быть позже времени начала."
            )
        elif response.error_code == "invalid_target":
            error_text = (
                "❌ Нельзя создать занятие для выбранного профиля."
            )
        else:
            error_text = (
                "❌ Не удалось сохранить дополнительное занятие. "
                "Попробуйте ещё раз."
            )
        if isinstance(event, CallbackQuery):
            await event.message.answer(
                error_text,
                parse_mode="HTML",
            )
            await event.answer()
        else:
            await event.answer(
                error_text,
                parse_mode="HTML",
            )
        return

    await state.clear()
    text_success, _ = UIRenderer.render_extra_class_success()

    if isinstance(event, CallbackQuery):
        shown = await _show_extra_menu_for_student(
            message_obj=event.message,
            actor_user_id=actor_user_id,
            target_student_id=target_student_id,
            extra_classes_service=extra_classes_service,
            students_service=students_service,
            schedule_service=schedule_service,
            edit_message=False,
            prefix=text_success,
        )
        if not shown:
            await event.message.answer(
                text_success,
                parse_mode="HTML",
            )
        await event.answer()
        return

    shown = await _show_extra_menu_for_student(
        message_obj=(
            event.message
            if isinstance(event, CallbackQuery)
            else event
        ),
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_classes_service=extra_classes_service,
        students_service=students_service,
        schedule_service=schedule_service,
        edit_message=isinstance(event, CallbackQuery),
        prefix=text_success,
    )
    if not shown:
        await event.answer(
            text_success,
            parse_mode="HTML",
        )


# === ИЗМЕНЕНИЕ ЗАНЯТИЯ ===

@router.callback_query(ExtraEditCD.filter())
async def start_edit_extra(
    callback: CallbackQuery,
    callback_data: ExtraEditCD,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
) -> None:
    """Запускает редактирование занятия при наличии manage-права."""
    target_student_id = callback_data.student_id
    actor_user_id = callback.from_user.id
    can_manage = await _require_extra_manage_access(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_classes_service=extra_classes_service,
    )
    if not can_manage:
        await callback.answer(
            "🔒 У вас нет права редактировать занятия этого ученика.",
            show_alert=True,
        )
        return
    list_response = await extra_classes_service.get_student_extra_classes(
        actor_user_id=callback.from_user.id,
        target_student_id=target_student_id,
    )
    if not list_response.success:
        await callback.answer(
            "У вас нет доступа к занятиям ребёнка.",
            show_alert=True,
        )
        return
    view_models = ExtraClassesService.build_view_models(
        list_response.data.items,
    )
    if not view_models:
        text, _ = UIRenderer.render_extra_class_edit_prompt(view_models)
        await callback.message.edit_text(
            text,
            reply_markup=Keyboards.get_back_to_extra_menu(
                target_student_id,
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    await state.update_data(
        target_student_id=target_student_id,
        extra_actor_user_id=actor_user_id,
    )
    text, _ = UIRenderer.render_extra_class_edit_prompt(view_models)
    await callback.message.edit_text(
        text,
        reply_markup=Keyboards.get_cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(ExtraClassStates.waiting_for_edit_id)
    await callback.answer()


@router.message(ExtraClassStates.waiting_for_edit_id)
async def process_edit_id(
    message: Message,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
) -> None:
    """
    Принимает ID занятия для редактирования.

    Повторно проверяет права через service, потому что FSM-состояние
    может устареть, а target_student_id нельзя считать доверенным.
    """
    if not await validate_fsm_session(
        message,
        state,
        expected={"extra_actor_user_id": message.from_user.id},
        required=["target_student_id"],
    ):
        return
    data = await state.get_data()
    actor_user_id = message.from_user.id
    target_student_id = data.get("target_student_id")
    raw_extra_id = message.text.strip()
    if not raw_extra_id.isdigit():
        text, _ = UIRenderer.render_extra_class_not_found()
        await message.answer(
            text,
            reply_markup=Keyboards.get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return
    extra_id = int(raw_extra_id)
    list_response = await extra_classes_service.get_student_extra_classes(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
    )
    if not list_response.success:
        await state.clear()
        await message.answer(
            "🔒 У вас больше нет доступа к занятиям этого ученика."
        )
        return
    dto_list = list_response.data
    if not any(item.id == extra_id for item in dto_list.items):
        text, _ = UIRenderer.render_extra_class_not_found()
        await message.answer(
            text,
            reply_markup=Keyboards.get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return
    can_manage = await _require_extra_manage_access(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_classes_service=extra_classes_service,
    )
    if not can_manage:
        await state.clear()
        await message.answer(
            "🔒 У вас больше нет права редактировать занятия ребёнка."
        )
        return
    await state.update_data(edit_id=extra_id)
    text, _ = UIRenderer.render_extra_class_edit_field_select()
    await message.answer(
        text,
        reply_markup=Keyboards.get_extra_edit_fields_kb(extra_id),
        parse_mode="HTML",
    )


@router.callback_query(ExtraEditFieldCD.filter())
async def choose_edit_field(
    callback: CallbackQuery,
    callback_data: ExtraEditFieldCD,
    state: FSMContext,
):
    if not await validate_fsm_session(
        callback,
        state,
        expected={"extra_actor_user_id": callback.from_user.id},
        required=["target_student_id"],
    ):
        return
    data = await state.get_data()
    actor_user_id = callback.from_user.id
    target_student_id = data.get("target_student_id")
    field = callback_data.field
    cb_extra_id = callback_data.extra_id
    # 2. Дополнительная проверка, что редактируется тот же ID,
    #    что сохранён в FSM
    fsm_edit_id = data.get("edit_id")
    if fsm_edit_id and str(fsm_edit_id) != str(cb_extra_id):
        await callback.answer("❌ Ошибка: несовпадение занятия.", show_alert=True)
        return
    await state.update_data(edit_field=field)
    if field == "time":
        text, _ = UIRenderer.render_extra_class_time_start()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        await state.set_state(ExtraClassStates.waiting_for_edit_value)
    elif field == "loc":
        text, _ = UIRenderer.render_extra_class_edit_location()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        await state.set_state(ExtraClassStates.waiting_for_edit_value)
    elif field == "rem":
        text, _ = UIRenderer.render_extra_class_reminder()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        await state.set_state(ExtraClassStates.waiting_for_edit_value)
    elif field == "day":
        text, _ = UIRenderer.render_extra_class_edit_day()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_day_selection_kb(), parse_mode="HTML")
        await state.set_state(ExtraClassStates.waiting_for_edit_value)
    else:
        text, _ = UIRenderer.render_extra_class_title()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        await state.set_state(ExtraClassStates.waiting_for_edit_value)
    await callback.answer()


@router.callback_query(
    ExtraClassStates.waiting_for_edit_value,
    ExtraDayCD.filter(),
)
async def process_edit_day(
    callback: CallbackQuery,
    callback_data: ExtraDayCD,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
):
    day_num = callback_data.day_of_week
    if not await validate_fsm_session(
        callback,
        state,
        expected={"extra_actor_user_id": callback.from_user.id},
        required=["target_student_id"],
    ):
        return
    data = await state.get_data()
    actor_user_id = callback.from_user.id
    target_student_id = data.get("target_student_id")
    extra_id = data["edit_id"]
    response = await extra_classes_service.update_extra_class(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_id=extra_id,
        day_of_week=day_num,
    )
    if not response.success:
        await state.clear()
        await callback.answer(
            "🔒 Не удалось изменить занятие.",
            show_alert=True,
        )
        return
    await state.clear()
    text_updated, _ = UIRenderer.render_extra_class_updated()
    shown = await _show_extra_menu_for_student(
        message_obj=callback.message,
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_classes_service=extra_classes_service,
        students_service=students_service,
        schedule_service=schedule_service,
        edit_message=True,
        prefix=text_updated,
    )
    if not shown:
        await callback.message.edit_text(text_updated, parse_mode="HTML")
    await callback.answer()


@router.message(ExtraClassStates.waiting_for_edit_value)
async def process_edit_value(
    message: Message,
    state: FSMContext,
    time_service: TimeService,
    extra_classes_service: ExtraClassesService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
):
    if not await validate_fsm_session(
        message,
        state,
        expected={"extra_actor_user_id": message.from_user.id},
        required=["target_student_id"],
    ):
        return
    data = await state.get_data()
    actor_user_id = message.from_user.id
    target_student_id = data.get("target_student_id")
    field = data["edit_field"]
    extra_id = data["edit_id"]
    val = message.text.strip()
    kwargs = {}
    if field == "time":
        norm_time = time_service.normalize_time(val)
        if not norm_time:
            text, _ = UIRenderer.render_extra_class_invalid_time()
            return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())
        await state.update_data(time_start=norm_time)
        text, _ = UIRenderer.render_extra_class_time_end()
        await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        return await state.set_state(ExtraClassStates.waiting_for_edit_time_end)
    elif field == "rem":
        if not val.isdigit():
            text, _ = UIRenderer.render_extra_class_invalid_reminder()
            return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        kwargs["reminder_minutes"] = int(val)
    elif field == "loc":
        kwargs["location"] = (
            None
            if val in {"", "-"}
            else val
        )
    else:
        kwargs["title"] = val
    response = await extra_classes_service.update_extra_class(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_id=extra_id,
        **kwargs
    )
    if not response.success:
        if response.error_code == "access_denied":
            await state.clear()
            await message.answer(
                "🔒 У вас больше нет права изменять занятия ребёнка."
            )
            return
        await message.answer("❌ Не удалось изменить занятие.")
        return
    await state.clear()
    text_updated, _ = UIRenderer.render_extra_class_updated()
    shown = await _show_extra_menu_for_student(
        message_obj=message,
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_classes_service=extra_classes_service,
        students_service=students_service,
        schedule_service=schedule_service,
        edit_message=False,
        prefix=text_updated
    )
    if not shown:
        await message.answer(text_updated, parse_mode="HTML")


@router.message(ExtraClassStates.waiting_for_edit_time_end)
async def process_edit_time_end(
    message: Message,
    state: FSMContext,
    time_service: TimeService,
    extra_classes_service: ExtraClassesService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
):
    if not await validate_fsm_session(
        message,
        state,
        expected={"extra_actor_user_id": message.from_user.id},
        required=["target_student_id"],
    ):
        return
    data = await state.get_data()
    actor_user_id = message.from_user.id
    target_student_id = data.get("target_student_id")
    norm_time = time_service.normalize_time(message.text)
    if not norm_time:
        text, _ = UIRenderer.render_extra_class_invalid_time()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())
    if not time_service.validate_time_range(data["time_start"], norm_time):
        text, _ = UIRenderer.render_extra_class_invalid_range()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())
    response = await extra_classes_service.update_extra_class(
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_id=data["edit_id"],
        time_start=data["time_start"],
        time_end=norm_time
    )
    if not response.success:
        if response.error_code == "access_denied":
            await state.clear()
            await message.answer(
                "🔒 У вас больше нет права изменять занятия ребёнка."
            )
            return
        await message.answer("❌ Не удалось изменить занятие.")
        return
    await state.clear()
    text_updated, _ = UIRenderer.render_extra_class_updated()
    shown = await _show_extra_menu_for_student(
        message_obj=message,
        actor_user_id=actor_user_id,
        target_student_id=target_student_id,
        extra_classes_service=extra_classes_service,
        students_service=students_service,
        schedule_service=schedule_service,
        edit_message=False,
        prefix=text_updated,
    )
    if not shown:
        await message.answer(text_updated, parse_mode="HTML")