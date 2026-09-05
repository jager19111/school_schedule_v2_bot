import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.keyboard import Keyboards
from bot.utils.ui_renderer import UIRenderer
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService

logger = logging.getLogger(__name__)
router = Router()


async def _safe_edit_schedule_message(
    callback: CallbackQuery,
    text: str,
    keyboard,
) -> None:
    """
    Безопасно обновляет schedule-message.

    TelegramBadRequest «message is not modified» не является ошибкой
    бизнес-логики и не должен ломать navigation flow.
    """
    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        logger.debug(
            "Schedule message edit skipped: %s",
            exc,
        )


async def _get_schedule_target(
    *,
    actor_user_id: int,
    target_user_id: int,
    profile_service: ProfileService,
):
    """
    Возвращает DTO целевого ребёнка после проверки доступа.

    - ребёнок может открыть только себя;
    - parent/observer может открыть только ребёнка из parent_child_settings.
    """
    actor_dto = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    if actor_user_id == target_user_id:
        if actor_dto.role != "child":
            return None

        return actor_dto

    if actor_dto.role not in ("parent", "observer"):
        return None

    has_access = await profile_service.parent_can_access_child(
        parent_user_id=actor_user_id,
        child_user_id=target_user_id,
    )

    if not has_access:
        return None

    target_dto = await profile_service.get_user_profile_dto(
        target_user_id,
    )

    if target_dto.role != "child":
        return None

    return target_dto


async def _has_multiple_children(
    *,
    actor_user_id: int,
    profile_service: ProfileService,
) -> bool:
    actor_dto = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    if actor_dto.role not in ("parent", "observer"):
        return False

    children = await profile_service.get_children_for_parent(
        actor_user_id,
    )

    return len(children) > 1


async def _render_day(
    *,
    actor_user_id: int,
    target_user_id: int,
    date_iso: str,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
):
    """
    Возвращает готовые text и keyboard для дневного экрана.
    """
    target_dto = await _get_schedule_target(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        profile_service=profile_service,
    )

    if target_dto is None or not target_dto.class_id:
        return None, None

    day_dto = await schedule_service.get_daily_schedule_for_child(
        class_id=target_dto.class_id,
        group_id=target_dto.group_id,
        date_iso=date_iso,
        user_id=target_user_id,
    )

    child_name = (
        target_dto.name
        if target_user_id != actor_user_id
        else None
    )

    rendered = UIRenderer.render_child_day_schedule(
        day_dto,
        child_name,
    )

    text = rendered[0] if isinstance(rendered, tuple) else rendered

    keyboard = Keyboards.get_schedule_day_kb(
        current_date_iso=date_iso,
        show_child_switch=await _has_multiple_children(
            actor_user_id=actor_user_id,
            profile_service=profile_service,
        ),
    )

    return text, keyboard


async def _render_week(
    *,
    actor_user_id: int,
    target_user_id: int,
    week_start_iso: str,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    is_full: bool,
):
    """
    Возвращает готовые text и keyboard для краткой или полной недели.
    """
    target_dto = await _get_schedule_target(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        profile_service=profile_service,
    )

    if target_dto is None or not target_dto.class_id:
        return None, None

    if is_full:
        dto = await schedule_service.get_full_week_schedule(
            class_id=target_dto.class_id,
            group_id=target_dto.group_id,
            week_start_iso=week_start_iso,
            user_id=target_user_id,
        )

        rendered = UIRenderer.render_full_week_schedule(dto)
    else:
        dto = await schedule_service.get_week_schedule_summary(
            class_id=target_dto.class_id,
            group_id=target_dto.group_id,
            week_start_iso=week_start_iso,
            user_id=target_user_id,
        )

        rendered = UIRenderer.render_week_summary(dto)

    text = rendered[0] if isinstance(rendered, tuple) else rendered

    if target_user_id != actor_user_id and target_dto.name:
        text = (
            f"👤 <b>{UIRenderer.escape_html(target_dto.name)}</b>\n\n"
            f"{text}"
        )

    keyboard = Keyboards.get_schedule_week_kb(
        week_start_iso=week_start_iso,
        show_child_switch=await _has_multiple_children(
            actor_user_id=actor_user_id,
            profile_service=profile_service,
        ),
        is_full=is_full,
    )

    return text, keyboard


async def _open_schedule_children_selector(
    *,
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает взрослому список детей для Schedule Hub.
    """
    children = await profile_service.get_children_for_parent(
        callback.from_user.id,
    )

    if not children:
        await callback.answer(
            "У вас нет привязанных детей.",
            show_alert=True,
        )
        return

    text = (
        "👥 <b>Выберите ребёнка для просмотра расписания</b>"
    )

    keyboard = Keyboards.get_schedule_children_kb(
        children,
    )

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()


@router.message(F.text == "📅 Моё расписание")
async def open_schedule_hub(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Единственная точка входа в личное расписание.

    Ребёнок открывает собственное расписание.
    Parent/observer с одним ребёнком открывает его сразу.
    Parent/observer с несколькими детьми выбирает ребёнка.
    """
    actor_user_id = message.from_user.id

    actor_dto = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    if actor_dto.role == "child":
        if not actor_dto.class_id:
            await message.answer(
                UIRenderer.render_unregistered_error()
            )
            return

        target_user_id = actor_user_id

    elif actor_dto.role in ("parent", "observer"):
        children = await profile_service.get_children_for_parent(
            actor_user_id,
        )

        if not children:
            await message.answer(
                "У вас нет привязанных детей. "
                "Добавьте ребёнка через настройки семьи."
            )
            return

        if len(children) > 1:
            await state.update_data(
                schedule_actor_user_id=actor_user_id,
                schedule_target_user_id=None,
            )

            await message.answer(
                "👥 <b>Выберите ребёнка для просмотра расписания</b>",
                reply_markup=Keyboards.get_schedule_children_kb(
                    children,
                ),
                parse_mode="HTML",
            )
            return

        target_user_id = children[0].user_id

    else:
        await message.answer(
            "Расписание для этой роли пока недоступно."
        )
        return

    target_dto = await _get_schedule_target(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        profile_service=profile_service,
    )

    if target_dto is None or not target_dto.class_id:
        await message.answer(
            "Профиль ребёнка ещё не настроен: не выбран класс."
        )
        return

    await state.update_data(
        schedule_actor_user_id=actor_user_id,
        schedule_target_user_id=target_user_id,
    )

    target_date_iso = await schedule_service.get_smart_target_date(
        class_id=target_dto.class_id,
        group_id=target_dto.group_id,
        user_id=target_user_id,
    )

    text, keyboard = await _render_day(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        date_iso=target_date_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
    )

    if text is None:
        await message.answer(
            "Не удалось открыть расписание."
        )
        return

    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("sched:child:"))
async def select_schedule_child(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Взрослый выбирает ребёнка для единого Schedule Hub.
    """
    try:
        target_user_id = int(
            callback.data.split(":")[2]
        )
    except (IndexError, ValueError):
        await callback.answer(
            "Некорректный идентификатор ребёнка.",
            show_alert=True,
        )
        return

    actor_user_id = callback.from_user.id

    target_dto = await _get_schedule_target(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        profile_service=profile_service,
    )

    if target_dto is None or not target_dto.class_id:
        await callback.answer(
            "У вас нет доступа к ребёнку или его профиль не настроен.",
            show_alert=True,
        )
        return

    await state.update_data(
        schedule_actor_user_id=actor_user_id,
        schedule_target_user_id=target_user_id,
    )

    target_date_iso = await schedule_service.get_smart_target_date(
        class_id=target_dto.class_id,
        group_id=target_dto.group_id,
        user_id=target_user_id,
    )

    text, keyboard = await _render_day(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        date_iso=target_date_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
    )

    if text is None:
        await callback.answer(
            "Не удалось открыть расписание ребёнка.",
            show_alert=True,
        )
        return

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()


async def _get_fsm_schedule_target(
    *,
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
):
    """
    Возвращает target_user_id из FSM и подтверждает доступ.

    Нельзя доверять только FSM: пользователь мог сменить роль, выйти
    из семьи или потерять доступ к ребёнку между нажатиями кнопок.
    """
    data = await state.get_data()

    actor_user_id = callback.from_user.id

    state_actor_user_id = data.get(
        "schedule_actor_user_id"
    )

    target_user_id = data.get(
        "schedule_target_user_id"
    )

    if state_actor_user_id != actor_user_id or not target_user_id:
        return None

    target_dto = await _get_schedule_target(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        profile_service=profile_service,
    )

    if target_dto is None or not target_dto.class_id:
        return None

    return target_user_id


@router.callback_query(F.data == "sched:children")
async def switch_schedule_child(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    """Открывает выбор ребёнка из любого schedule-экрана."""
    await _open_schedule_children_selector(
        callback=callback,
        profile_service=profile_service,
    )

    await state.update_data(
        schedule_actor_user_id=callback.from_user.id,
        schedule_target_user_id=None,
    )


@router.callback_query(F.data == "sched:smart_day")
async def go_to_smart_day(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """Возвращает к ближайшему актуальному дню расписания."""
    target_user_id = await _get_fsm_schedule_target(
        callback=callback,
        state=state,
        profile_service=profile_service,
    )

    if target_user_id is None:
        await callback.answer(
            "Сессия просмотра устарела. Откройте расписание заново.",
            show_alert=True,
        )
        return

    actor_user_id = callback.from_user.id

    target_dto = await _get_schedule_target(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        profile_service=profile_service,
    )

    target_date_iso = await schedule_service.get_smart_target_date(
        class_id=target_dto.class_id,
        group_id=target_dto.group_id,
        user_id=target_user_id,
    )

    text, keyboard = await _render_day(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        date_iso=target_date_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
    )

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()


@router.callback_query(F.data.startswith("sched:day:"))
async def show_schedule_day(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """Показывает выбранный день расписания."""
    try:
        date_iso = callback.data.split(":")[2]
    except IndexError:
        await callback.answer(
            "Некорректная дата.",
            show_alert=True,
        )
        return

    target_user_id = await _get_fsm_schedule_target(
        callback=callback,
        state=state,
        profile_service=profile_service,
    )

    if target_user_id is None:
        await callback.answer(
            "Сессия просмотра устарела. Откройте расписание заново.",
            show_alert=True,
        )
        return

    text, keyboard = await _render_day(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        date_iso=date_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
    )

    if text is None:
        await callback.answer(
            "Не удалось открыть расписание.",
            show_alert=True,
        )
        return

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()


@router.callback_query(F.data.startswith("sched:week:"))
async def show_schedule_week(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """Показывает краткое недельное расписание."""
    try:
        week_start_iso = callback.data.split(":")[2]
    except IndexError:
        await callback.answer(
            "Некорректная дата недели.",
            show_alert=True,
        )
        return

    target_user_id = await _get_fsm_schedule_target(
        callback=callback,
        state=state,
        profile_service=profile_service,
    )

    if target_user_id is None:
        await callback.answer(
            "Сессия просмотра устарела. Откройте расписание заново.",
            show_alert=True,
        )
        return

    text, keyboard = await _render_week(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        week_start_iso=week_start_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
        is_full=False,
    )

    if text is None:
        await callback.answer(
            "Не удалось открыть недельное расписание.",
            show_alert=True,
        )
        return

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()


@router.callback_query(F.data.startswith("sched:full_week:"))
async def show_full_schedule_week(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """Показывает подробное расписание всей недели."""
    try:
        week_start_iso = callback.data.split(":")[2]
    except IndexError:
        await callback.answer(
            "Некорректная дата недели.",
            show_alert=True,
        )
        return

    target_user_id = await _get_fsm_schedule_target(
        callback=callback,
        state=state,
        profile_service=profile_service,
    )

    if target_user_id is None:
        await callback.answer(
            "Сессия просмотра устарела. Откройте расписание заново.",
            show_alert=True,
        )
        return

    text, keyboard = await _render_week(
        actor_user_id=callback.from_user.id,
        target_user_id=target_user_id,
        week_start_iso=week_start_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
        is_full=True,
    )

    if text is None:
        await callback.answer(
            "Не удалось открыть подробное расписание.",
            show_alert=True,
        )
        return

    if len(text) > 3900:
        await callback.answer(
            "Подробная неделя слишком длинная. Используйте просмотр по дням.",
            show_alert=True,
        )
        return

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()