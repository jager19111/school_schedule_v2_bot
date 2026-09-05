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

# Хелпер для проверки прав доступа к доп. занятиям
async def _show_extra_menu_for_target(
    *,
    message_obj: Message,
    actor_user_id: int,
    target_child_id: int,
    extra_classes_service: ExtraClassesService,
    edit_message: bool,
    prefix: str = "",
) -> bool:
    """
    Показывает меню дополнительных занятий конкретного ребёнка.

    Права вычисляются сервисом, а не handler-ом:
    - ребёнок получает собственные занятия;
    - взрослый может только просматривать, если есть parent_child_settings;
    - взрослый может редактировать только при can_manage_extra_classes = 1.
    """
    access = await extra_classes_service.get_access(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
    )

    if not access.can_view:
        return False

    text, _ = UIRenderer.render_extra_classes_menu()

    if prefix:
        text = f"{prefix}\n\n{text}"

    keyboard = Keyboards.get_extra_classes_menu(
        target_user_id=target_child_id,
        can_add=access.can_manage,
        can_edit=access.can_manage,
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
        # Не скрываем бизнес-ошибки выше; здесь защищаем только Telegram UI.
        logger.warning(
            "Unable to render extra classes menu: actor_id=%s target_id=%s error=%s",
            actor_user_id,
            target_child_id,
            exc,
        )

    return True


async def _require_extra_manage_access(
    *,
    actor_user_id: int,
    target_child_id: int,
    extra_classes_service: ExtraClassesService,
) -> bool:
    """
    Проверяет право создавать, изменять или удалять занятия ребёнка.

    Проверка повторяется на каждом критичном шаге FSM, потому что callback
    и FSM-данные нельзя считать доверенными.
    """
    access = await extra_classes_service.get_access(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
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
    extra_classes_service: ExtraClassesService,
) -> None:
    """
    Открывает меню дополнительных занятий.

    Ребёнок открывает собственные занятия.
    Parent/observer выбирает ребёнка из доступных ему связей.
    """
    actor_user_id = message.from_user.id

    actor_dto = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    if actor_dto.role == "child":
        shown = await _show_extra_menu_for_target(
            message_obj=message,
            actor_user_id=actor_user_id,
            target_child_id=actor_user_id,
            extra_classes_service=extra_classes_service,
            edit_message=False,
        )

        if not shown:
            await message.answer(
                "❌ Не удалось определить права на дополнительные занятия."
            )

        return

    if actor_dto.role not in ("parent", "observer"):
        await message.answer(
            "❌ Дополнительные занятия доступны только детям, "
            "родителям и наблюдателям."
        )
        return

    children = await profile_service.get_children_for_parent(
        actor_user_id,
    )

    if not children:
        text, _ = UIRenderer.render_extra_no_children()

        await message.answer(
            text,
            parse_mode="HTML",
        )
        return

    if len(children) == 1:
        shown = await _show_extra_menu_for_target(
            message_obj=message,
            actor_user_id=actor_user_id,
            target_child_id=children[0].user_id,
            extra_classes_service=extra_classes_service,
            edit_message=False,
        )

        if not shown:
            await message.answer(
                "❌ У вас нет доступа к дополнительным занятиям ребёнка."
            )

        return

    text, _ = UIRenderer.render_extra_child_select()

    await message.answer(
        text,
        reply_markup=Keyboards.get_extra_children_select_kb(children),
        parse_mode="HTML",
    )
    
@router.callback_query(F.data.startswith("extra:menu:"))
async def show_extra_menu_cb(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    extra_classes_service: ExtraClassesService,
) -> None:
    """Открывает меню допзанятий выбранного ребёнка."""
    await state.clear()

    try:
        target_child_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer(
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    actor_user_id = callback.from_user.id

    shown = await _show_extra_menu_for_target(
        message_obj=callback.message,
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
        extra_classes_service=extra_classes_service,
        edit_message=True,
    )

    if not shown:
        await callback.answer(
            "У вас нет доступа к занятиям этого ребёнка.",
            show_alert=True,
        )
        return

    await callback.answer()
    

@router.callback_query(F.data == "extra:cancel")
async def cancel_action(
    callback: CallbackQuery,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
) -> None:
    """Отменяет FSM-действие и возвращает к доступному меню занятий."""
    data = await state.get_data()

    target_child_id = data.get(
        "target_user_id",
        callback.from_user.id,
    )

    await state.clear()

    shown = await _show_extra_menu_for_target(
        message_obj=callback.message,
        actor_user_id=callback.from_user.id,
        target_child_id=target_child_id,
        extra_classes_service=extra_classes_service,
        edit_message=True,
        prefix="❌ Действие отменено.",
    )

    if not shown:
        await callback.answer(
            "Меню занятий больше недоступно.",
            show_alert=True,
        )
        return

    await callback.answer()

# === СПИСОК И УДАЛЕНИЕ ===

@router.callback_query(F.data.startswith("extra:list:"))
async def show_extra_list(
    callback: CallbackQuery,
    extra_classes_service: ExtraClassesService,
) -> None:
    """Показывает занятия ребёнка только при наличии view-права."""
    try:
        target_child_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer(
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    response = await extra_classes_service.get_user_extra_classes(
        actor_user_id=callback.from_user.id,
        target_child_id=target_child_id,
    )

    if not response.success:
        await callback.answer(
            "У вас нет доступа к занятиям этого ребёнка.",
            show_alert=True,
        )
        return

    dto_list = response.data

    text, _ = UIRenderer.render_extra_classes_list(dto_list)

    try:
        await callback.message.edit_text(
            text,
            reply_markup=Keyboards.get_back_to_extra_menu(
                target_child_id,
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning(
            "Failed to show extra classes list: actor_id=%s target_id=%s error=%s",
            callback.from_user.id,
            target_child_id,
            exc,
        )

    await callback.answer()

@router.callback_query(F.data.startswith("extra:delete:"))
async def start_delete_extra(
    callback: CallbackQuery,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
) -> None:
    """Запускает удаление занятия при наличии manage-права."""
    try:
        target_child_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer(
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    actor_user_id = callback.from_user.id

    can_manage = await _require_extra_manage_access(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
        extra_classes_service=extra_classes_service,
    )

    if not can_manage:
        await callback.answer(
            "🔒 У вас нет права удалять занятия этого ребёнка.",
            show_alert=True,
        )
        return

    list_response = await extra_classes_service.get_user_extra_classes(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
    )

    if not list_response.success:
        await callback.answer(
            "У вас нет доступа к занятиям ребёнка.",
            show_alert=True,
        )
        return

    dto_list = list_response.data

    if not dto_list.items:
        text, _ = UIRenderer.render_extra_class_delete_prompt(dto_list)

        await callback.message.edit_text(
            text,
            reply_markup=Keyboards.get_back_to_extra_menu(
                target_child_id,
            ),
            parse_mode="HTML",
        )

        await callback.answer()
        return

    await state.update_data(
        target_user_id=target_child_id,
        extra_actor_user_id=actor_user_id,
    )

    text, _ = UIRenderer.render_extra_class_delete_prompt(dto_list)

    await callback.message.edit_text(
        text,
        reply_markup=Keyboards.get_cancel_keyboard(),
        parse_mode="HTML",
    )

    await state.set_state(ExtraClassStates.waiting_for_delete_id)

    await callback.answer()
    
@router.message(ExtraClassStates.waiting_for_delete_id)
async def process_delete_id(
    message: Message,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
) -> None:
    """Финально удаляет занятие с повторной service-проверкой прав."""
    data = await state.get_data()

    actor_user_id = message.from_user.id
    target_child_id = data.get("target_user_id")
    state_actor_id = data.get("extra_actor_user_id")

    if not target_child_id or state_actor_id != actor_user_id:
        await state.clear()

        await message.answer(
            "❌ Состояние удаления устарело. Откройте меню заново."
        )
        return

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
        target_child_id=target_child_id,
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

    shown = await _show_extra_menu_for_target(
        message_obj=message,
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
        extra_classes_service=extra_classes_service,
        edit_message=False,
        prefix=text_deleted,
    )

    if not shown:
        await message.answer(
            text_deleted,
            parse_mode="HTML",
        )
        
# === ДОБАВЛЕНИЕ ЗАНЯТИЯ ===

@router.callback_query(F.data.startswith("extra:add:"))
async def start_add_extra(
    callback: CallbackQuery,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
) -> None:
    """Запускает FSM добавления занятия при наличии manage-права."""
    try:
        target_child_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer(
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    actor_user_id = callback.from_user.id

    can_manage = await _require_extra_manage_access(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
        extra_classes_service=extra_classes_service,
    )

    if not can_manage:
        await callback.answer(
            "🔒 У вас нет права добавлять занятия этому ребёнку.",
            show_alert=True,
        )
        return

    await state.update_data(
        target_user_id=target_child_id,
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

@router.callback_query(ExtraClassStates.waiting_for_day, F.data.startswith("extraday:"))
async def process_day(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    # Защита: отсекаем устаревшие сессии в самом начале цепочки
    if data.get("extra_actor_user_id") != callback.from_user.id:
        await state.clear()
        await callback.answer(
            "❌ Состояние устарело. Откройте меню заново.", 
            show_alert=True
        )
        return

    day_num = int(callback.data.split(":")[1])
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
    await message.answer(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_location"), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_location)

@router.callback_query(ExtraClassStates.waiting_for_location, F.data == "skip_location")
async def skip_location(callback: CallbackQuery, state: FSMContext):
    await state.update_data(location=None)
    text, _ = UIRenderer.render_extra_class_reminder()
    await callback.message.edit_text(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_reminder"), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_reminder)
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_location)
async def process_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text.strip())
    text, _ = UIRenderer.render_extra_class_reminder()
    await message.answer(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_reminder"), parse_mode="HTML")
    await state.set_state(ExtraClassStates.waiting_for_reminder)

@router.callback_query(ExtraClassStates.waiting_for_reminder, F.data == "skip_reminder")
async def skip_reminder(callback: CallbackQuery, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    await finalize_extra_class(
    callback,
    state,
    extra_classes_service,
    reminder_minutes=30,
)
    await callback.answer()

@router.message(ExtraClassStates.waiting_for_reminder)
async def process_reminder(message: Message, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    reminder_text = message.text.strip()
    if not reminder_text.isdigit():
        text, _ = UIRenderer.render_extra_class_invalid_reminder()
        return await message.answer(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_reminder"), parse_mode="HTML")
        
    await finalize_extra_class(
    message,
    state,
    extra_classes_service,
    reminder_minutes=int(reminder_text),
)

async def finalize_extra_class(
    event: Message | CallbackQuery,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
    reminder_minutes: int,
) -> None:
    """
    Финальное создание дополнительного занятия.

    Перед записью сервис повторно проверяет:
        actor_user_id -> target_child_id -> can_manage_extra_classes
    """
    data = await state.get_data()

    actor_user_id = event.from_user.id
    target_child_id = data.get("target_user_id")
    state_actor_id = data.get("extra_actor_user_id")

    if not target_child_id or state_actor_id != actor_user_id:
        await state.clear()

        if isinstance(event, CallbackQuery):
            await event.answer(
                "❌ Состояние добавления устарело. Откройте меню заново.",
                show_alert=True,
            )
        else:
            await event.answer(
                "❌ Состояние добавления устарело. "
                "Откройте меню дополнительных занятий заново."
            )

        return

    response = await extra_classes_service.add_extra_class(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
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
        shown = await _show_extra_menu_for_target(
            message_obj=event.message,
            actor_user_id=actor_user_id,
            target_child_id=target_child_id,
            extra_classes_service=extra_classes_service,
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

    shown = await _show_extra_menu_for_target(
        message_obj=event,
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
        extra_classes_service=extra_classes_service,
        edit_message=False,
        prefix=text_success,
    )

    if not shown:
        await event.answer(
            text_success,
            parse_mode="HTML",
        )
        
# === ИЗМЕНЕНИЕ ЗАНЯТИЯ ===

@router.callback_query(F.data.startswith("extra:edit:"))
async def start_edit_extra(
    callback: CallbackQuery,
    state: FSMContext,
    extra_classes_service: ExtraClassesService,
) -> None:
    """Запускает редактирование занятия при наличии manage-права."""
    try:
        target_child_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer(
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    actor_user_id = callback.from_user.id

    can_manage = await _require_extra_manage_access(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
        extra_classes_service=extra_classes_service,
    )

    if not can_manage:
        await callback.answer(
            "🔒 У вас нет права редактировать занятия этого ребёнка.",
            show_alert=True,
        )
        return

    list_response = await extra_classes_service.get_user_extra_classes(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
    )

    if not list_response.success:
        await callback.answer(
            "У вас нет доступа к занятиям ребёнка.",
            show_alert=True,
        )
        return

    dto_list = list_response.data

    if not dto_list.items:
        text, _ = UIRenderer.render_extra_class_edit_prompt(dto_list)

        await callback.message.edit_text(
            text,
            reply_markup=Keyboards.get_back_to_extra_menu(
                target_child_id,
            ),
            parse_mode="HTML",
        )

        await callback.answer()
        return

    await state.update_data(
        target_user_id=target_child_id,
        extra_actor_user_id=actor_user_id,
    )

    text, _ = UIRenderer.render_extra_class_edit_prompt(dto_list)

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
    может устареть, а target_user_id нельзя считать доверенным.
    """
    data = await state.get_data()

    actor_user_id = message.from_user.id
    target_child_id = data.get("target_user_id")
    state_actor_id = data.get("extra_actor_user_id")

    if not target_child_id or state_actor_id != actor_user_id:
        await state.clear()

        await message.answer(
            "❌ Состояние редактирования устарело. "
            "Откройте меню дополнительных занятий заново."
        )
        return

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

    list_response = await extra_classes_service.get_user_extra_classes(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
    )

    if not list_response.success:
        await state.clear()

        await message.answer(
            "🔒 У вас больше нет доступа к занятиям этого ребёнка."
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
        target_child_id=target_child_id,
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
    
@router.callback_query(F.data.startswith("edit_ext:"))
async def choose_edit_field(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    # 1. Защита от старых кнопок и подмены FSM
    actor_user_id = callback.from_user.id
    target_child_id = data.get("target_user_id")
    state_actor_id = data.get("extra_actor_user_id")

    if not target_child_id or state_actor_id != actor_user_id:
        await state.clear()
        await callback.answer(
            "❌ Меню устарело. Начните редактирование заново.", 
            show_alert=True
        )
        return

    _, field, cb_class_id = callback.data.split(":")
    
    # 2. Дополнительная проверка, что редактируется тот же ID, что сохранен в FSM
    fsm_edit_id = data.get("edit_id")
    if fsm_edit_id and str(fsm_edit_id) != cb_class_id:
        await callback.answer("❌ Ошибка: несовпадение занятия.", show_alert=True)
        return

    await state.update_data(edit_field=field)
    
    if field == "time":
        text, _ = UIRenderer.render_extra_class_time_start()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_cancel_keyboard(), parse_mode="HTML")
        await state.set_state(ExtraClassStates.waiting_for_edit_value)
    elif field == "loc":
        text, _ = UIRenderer.render_extra_class_location()
        await callback.message.edit_text(text, reply_markup=Keyboards.get_skip_cancel_keyboard("skip_location"), parse_mode="HTML")
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

@router.callback_query(ExtraClassStates.waiting_for_edit_value, F.data.startswith("extraday:"))
async def process_edit_day(callback: CallbackQuery, state: FSMContext, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    day_num = int(callback.data.split(":")[1])
    data = await state.get_data()
    
    actor_user_id = callback.from_user.id
    target_child_id = data.get("target_user_id")
    state_actor_id = data.get("extra_actor_user_id")

    if not target_child_id or state_actor_id != actor_user_id:
        await state.clear()
        await callback.answer(
            "❌ Состояние редактирования устарело. Откройте меню заново.",
            show_alert=True,
        )
        return

    class_id = data["edit_id"]

    response = await extra_classes_service.update_extra_class(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
        extra_id=class_id,
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
    
    shown = await _show_extra_menu_for_target(
        message_obj=callback.message,
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
        extra_classes_service=extra_classes_service,
        edit_message=True,
        prefix=text_updated,
    )
    
    if not shown:
        await callback.message.edit_text(text_updated, parse_mode="HTML")

    await callback.answer()


@router.message(ExtraClassStates.waiting_for_edit_value)
async def process_edit_value(message: Message, state: FSMContext, time_service: TimeService, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    data = await state.get_data()
    
    actor_user_id = message.from_user.id
    target_child_id = data.get("target_user_id")
    state_actor_id = data.get("extra_actor_user_id")

    if not target_child_id or state_actor_id != actor_user_id:
        await state.clear()
        await message.answer(
            "❌ Состояние редактирования устарело. "
            "Откройте меню дополнительных занятий заново."
        )
        return

    field = data["edit_field"]
    class_id = data["edit_id"]
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
        kwargs["location"] = val
    else:
        kwargs["title"] = val

    response = await extra_classes_service.update_extra_class(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
        extra_id=class_id,
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
    
    shown = await _show_extra_menu_for_target(
        message_obj=message,
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
        extra_classes_service=extra_classes_service,
        edit_message=False,
        prefix=text_updated,
    )
    
    if not shown:
        await message.answer(text_updated, parse_mode="HTML")


@router.message(ExtraClassStates.waiting_for_edit_time_end)
async def process_edit_time_end(message: Message, state: FSMContext, time_service: TimeService, extra_classes_service: ExtraClassesService, profile_service: ProfileService):
    data = await state.get_data()
    
    actor_user_id = message.from_user.id
    target_child_id = data.get("target_user_id")
    state_actor_id = data.get("extra_actor_user_id")

    if not target_child_id or state_actor_id != actor_user_id:
        await state.clear()
        await message.answer(
            "❌ Состояние редактирования устарело. "
            "Откройте меню дополнительных занятий заново."
        )
        return
        
    norm_time = time_service.normalize_time(message.text)
    
    if not norm_time:
        text, _ = UIRenderer.render_extra_class_invalid_time()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())
        
    if not time_service.validate_time_range(data["time_start"], norm_time):
        text, _ = UIRenderer.render_extra_class_invalid_range()
        return await message.answer(text, reply_markup=Keyboards.get_cancel_keyboard())

    response = await extra_classes_service.update_extra_class(
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
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
    
    shown = await _show_extra_menu_for_target(
        message_obj=message,
        actor_user_id=actor_user_id,
        target_child_id=target_child_id,
        extra_classes_service=extra_classes_service,
        edit_message=False,
        prefix=text_updated,
    )
    
    if not shown:
        await message.answer(text_updated, parse_mode="HTML")
        
        
