# Путь: bot/handlers/settings_watch.py
# Описание: Управление отслеживаемыми классами (Watch Targets): добавление, просмотр, удаление и настройка уведомлений для них.

import logging
from dataclasses import replace
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot import callbacks
from bot.callbacks import (
    WatchChangesCD,
    WatchClassCD,
    WatchDeleteCD,
    WatchDeleteConfirmCD,
    WatchDetailsCD,
    WatchGroupCD,
    WatchToggleCD,
)
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from services.watch_targets_service import WatchTargetsService
from services.schedule_service import ScheduleService
from bot.utils.fsm_guard import validate_fsm_session
from bot.utils.safe_send import _safe_edit_text, _safe_callback_answer
from bot.handlers.settings import SettingsStates

logger = logging.getLogger(__name__)
router = Router()

# Меню watch targets    
@router.callback_query(F.data == callbacks.WATCH_MENU)
async def show_watch_targets_menu(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Показывает самостоятельные отслеживаемые классы пользователя.
    """
    targets = await watch_targets_service.get_targets(
        owner_user_id=callback.from_user.id,
    )
    
    # 1. Запрашиваем справочники школы единым запросом
    dicts_dto = await schedule_service.get_school_dictionaries()
    
    view_models = WatchTargetsService.build_view_models(
        targets,
        dicts_dto,
    )
    text = UIRenderer.render_watch_targets_menu(view_models)
    keyboard = Keyboards.get_watch_targets_menu_kb(view_models)

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

@router.callback_query(F.data == callbacks.WATCH_ADD)
async def start_add_watch_target(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    """
    Запускает выбор класса для direct watch target.
    """
    # 1. Забираем справочники школы за один запрос
    dicts_dto = await schedule_service.get_school_dictionaries()

    if not dicts_dto.classes:
        await _safe_callback_answer(
            callback,
            "Расписание школы ещё не загружено. "
            "Попробуйте позже.",
            show_alert=True,
        )
        return

    text = (
        "🎓 <b>Добавить отслеживаемый класс</b>\n\n"
        "Выберите класс, расписание которого хотите отслеживать."
    )

    # 2. Передаем ClassListDTO через вспомогательное свойство as_class_list
    keyboard = Keyboards.get_watch_class_selection_kb(
        dicts_dto.as_class_list,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await state.set_state(
        SettingsStates.waiting_for_watch_group,
    )

    await state.update_data(
        watch_target_owner_id=callback.from_user.id,
        watch_target_stage="class",
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    SettingsStates.waiting_for_watch_group,
    WatchClassCD.filter(),
)
async def select_watch_target_class(
    callback: CallbackQuery,
    callback_data: WatchClassCD,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    class_id = callback_data.class_id

    if not await validate_fsm_session(
        callback,
        state,
        expected={"watch_target_owner_id": callback.from_user.id},
    ):
        return

    groups_dto = await schedule_service.get_groups_list()

    await state.update_data(
        watch_target_class_id=class_id,
        watch_target_stage="group",
    )

    text = (
        "👥 <b>Выберите группу</b>\n\n"
        "Если группа неизвестна или класс не делится на группы, "
        "выберите «Весь класс»."
    )

    keyboard = Keyboards.get_watch_group_selection_kb(
        groups_dto,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    SettingsStates.waiting_for_watch_group,
    WatchGroupCD.filter(),
)
async def select_watch_target_group(
    callback: CallbackQuery,
    callback_data: WatchGroupCD,
    state: FSMContext,
    schedule_service: ScheduleService,
    watch_targets_service: WatchTargetsService,
) -> None:
    group_id = callback_data.group_id

    if not await validate_fsm_session(
        callback,
        state,
        expected={"watch_target_owner_id": callback.from_user.id},
    ):
        return

    data = await state.get_data()
    owner_user_id = data.get("watch_target_owner_id")
    class_id = data.get("watch_target_class_id")

    if not class_id:
        await state.clear()

        await _safe_callback_answer(
            callback,
            "Состояние добавления устарело.",
            show_alert=True,
        )
        return

    # 1. Запрашиваем справочники школы единым запросом
    dicts_dto = await schedule_service.get_school_dictionaries()

    # 2. Получаем читаемое название класса через хелпер DTO
    title = dicts_dto.get_readable_class(class_id)

    response = await watch_targets_service.add_target(
        owner_user_id=owner_user_id,
        class_id=class_id,
        group_id=group_id,
        title=title,
    )

    await state.clear()

    if not response.success:
        if response.error_code == "duplicate":
            error_text = (
                "⚠️ Этот класс и группа уже добавлены "
                "в отслеживание."
            )
        elif response.error_code == "limit_reached":
            error_text = (
                "⚠️ Достигнут лимит отслеживаемых классов "
                "(10)."
            )
        else:
            error_text = (
                "❌ Не удалось добавить отслеживаемый класс."
            )

        await _safe_callback_answer(
            callback,
            error_text,
            show_alert=True,
        )
        return

    targets = await watch_targets_service.get_targets(
        owner_user_id=owner_user_id,
    )
    
    # 1. Запрашиваем справочники школы единым запросом
    dicts_dto = await schedule_service.get_school_dictionaries()

    view_models = WatchTargetsService.build_view_models(
        targets,
        dicts_dto,
    )
    text = (
        "✅ <b>Класс добавлен в отслеживание.</b>\n\n"
        + UIRenderer.render_watch_targets_menu(view_models)
    )

    keyboard = Keyboards.get_watch_targets_menu_kb(view_models)

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(
        callback,
        "Класс добавлен.",
    )
    
@router.callback_query(
    WatchDetailsCD.filter()
)
async def show_watch_target_details(
    callback: CallbackQuery,
    callback_data: WatchDetailsCD,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService,
) -> None:
    target_id = callback_data.target_id

    targets = await watch_targets_service.get_targets(
        owner_user_id=callback.from_user.id,
    )

    target = next(
        (
            item
            for item in targets
            if item.id == target_id
        ),
        None,
    )

    if target is None:
        await _safe_callback_answer(
            callback,
            "Класс не найден или у вас нет доступа.",
            show_alert=True,
        )
        return

    # 1. Запрашиваем справочники школы единым запросом через новый сервис
    dicts_dto = await schedule_service.get_school_dictionaries()

    vm = WatchTargetsService.build_view_model(target, dicts_dto)
    text = UIRenderer.render_watch_target_details(vm)
    keyboard = Keyboards.get_watch_target_details_kb(vm)

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

@router.callback_query(
    WatchToggleCD.filter()
)
async def toggle_watch_target(
    callback: CallbackQuery,
    callback_data: WatchToggleCD,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService
) -> None:
    target_id = callback_data.target_id

    targets = await watch_targets_service.get_targets(
        owner_user_id=callback.from_user.id,
    )

    target = next(
        (
            item
            for item in targets
            if item.id == target_id
        ),
        None,
    )

    if target is None:
        await _safe_callback_answer(
            callback,
            "Класс не найден.",
            show_alert=True,
        )
        return

    response = await watch_targets_service.set_target_enabled(
        owner_user_id=callback.from_user.id,
        target_id=target_id,
        is_enabled=not target.is_enabled,
    )

    if not response.success:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить состояние класса.",
            show_alert=True,
        )
        return

    await _safe_callback_answer(
        callback,
        "Отслеживание обновлено.",
    )

    refreshed_target = replace(
        target,
        is_enabled=not target.is_enabled,
    )

    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = WatchTargetsService.build_view_model(refreshed_target, dicts_dto)
    text = UIRenderer.render_watch_target_details(vm)
    keyboard = Keyboards.get_watch_target_details_kb(vm)

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )  

@router.callback_query(
    WatchChangesCD.filter()
)
async def toggle_watch_target_schedule_changes(
    callback: CallbackQuery,
    callback_data: WatchChangesCD,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Включает или выключает уведомления об изменениях
    только для одного watch target.
    """
    target_id = callback_data.target_id

    target = await watch_targets_service.get_target(
        owner_user_id=callback.from_user.id,
        target_id=target_id,
    )

    if target is None:
        await _safe_callback_answer(
            callback,
            "Класс не найден или у вас нет доступа.",
            show_alert=True,
        )
        return

    response = await watch_targets_service.set_target_receive_schedule_changes(
        owner_user_id=callback.from_user.id,
        target_id=target_id,
        receive_schedule_changes=(
            not target.receive_schedule_changes
        ),
    )

    if not response.success:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить настройки уведомлений.",
            show_alert=True,
        )
        return

    refreshed_target = replace(
        target,
        receive_schedule_changes=not target.receive_schedule_changes,
    )

    # 1. Запрашиваем справочники школы единым запросом через новый сервис
    dicts_dto = await schedule_service.get_school_dictionaries()

    vm = WatchTargetsService.build_view_model(
        refreshed_target,
        dicts_dto,
    )
    text = UIRenderer.render_watch_target_details(vm)
    keyboard = Keyboards.get_watch_target_details_kb(vm)

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    state_text = (
        "включены"
        if refreshed_target.receive_schedule_changes
        else "выключены"
    )

    await _safe_callback_answer(
        callback,
        f"Уведомления об изменениях {state_text}.",
    )
    
@router.callback_query(
    WatchDeleteCD.filter()
)
async def confirm_delete_watch_target(
    callback: CallbackQuery,
    callback_data: WatchDeleteCD,
    watch_targets_service: WatchTargetsService,
) -> None:
    target_id = callback_data.target_id

    targets = await watch_targets_service.get_targets(
        owner_user_id=callback.from_user.id,
    )

    target = next(
        (
            item
            for item in targets
            if item.id == target_id
        ),
        None,
    )

    if target is None:
        await _safe_callback_answer(
            callback,
            "Класс не найден.",
            show_alert=True,
        )
        return

    title = target.title or f"Класс {target.class_id}"

    text = (
        "⚠️ <b>Удалить отслеживаемый класс?</b>\n\n"
        f"Класс: <b>{UIRenderer.escape_html(title)}</b>\n\n"
        "Расписание школы не будет удалено. "
        "Будет удалена только ваша личная цель отслеживания."
    )

    keyboard = Keyboards.get_watch_target_delete_confirmation_kb(
        target_id,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    WatchDeleteConfirmCD.filter()
)
async def delete_watch_target(
    callback: CallbackQuery,
    callback_data: WatchDeleteConfirmCD,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService,
) -> None:
    target_id = callback_data.target_id

    response = await watch_targets_service.delete_target(
        owner_user_id=callback.from_user.id,
        target_id=target_id,
    )

    if not response.success:
        await _safe_callback_answer(
            callback,
            "Класс не найден или уже удалён.",
            show_alert=True,
        )
        return

    targets = await watch_targets_service.get_targets(
        owner_user_id=callback.from_user.id,
    )
    
    # 1. Запрашиваем справочники школы единым запросом
    dicts_dto = await schedule_service.get_school_dictionaries()
    
    view_models = WatchTargetsService.build_view_models(
        targets,
        dicts_dto,
    )
    text = (
        "✅ <b>Отслеживаемый класс удалён.</b>\n\n"
        + UIRenderer.render_watch_targets_menu(view_models)
    )

    keyboard = Keyboards.get_watch_targets_menu_kb(view_models)

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(
        callback,
        "Класс удалён.",
    )