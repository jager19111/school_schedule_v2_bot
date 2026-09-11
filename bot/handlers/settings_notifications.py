# Путь: bot/handlers/settings_notifications.py
# Описание: Глобальные настройки уведомлений пользователя, настройка времени утренней сводки и подписки родителей на уведомления детей (PSN).

import logging
import contextlib
from dataclasses import replace
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from bot import callbacks
from bot.callbacks import ParentStudentSettingsCD, ParentStudentToggleCD
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.students_service import StudentsService
from services.time_service import TimeService
from bot.utils.fsm_guard import validate_fsm_session
from bot.utils.safe_send import _safe_edit_text, _safe_callback_answer
from bot.handlers.settings import SettingsStates, _show_settings_menu

logger = logging.getLogger(__name__)
router = Router()

async def _require_own_notification_settings_access(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> bool:
    """
    Проверяет, что пользователь может менять собственные уведомления.

    Для ребёнка учитывается блокировка, заданная администратором семьи.
    Parent и observer всегда меняют только свои настройки.
    """
    allowed = await profile_service.can_user_change_own_notification_settings(
        user_id=callback.from_user.id,
    )

    if allowed:
        return True

    await _safe_callback_answer(
        callback,
        "🔒 Ваши настройки уведомлений заблокированы "
        "администратором семьи.",
        show_alert=True,
    )

    return False

@router.callback_query(
    F.data == callbacks.SETTINGS_CHILDREN_NOTIFICATIONS
)
async def show_children_notification_settings(
    callback: CallbackQuery,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Открывает selector student profiles для personal adult subscriptions.

    Показывает:
    - virtual students;
    - Telegram-linked students;
    - только student profiles, доступные текущему adult.
    """
    adult_user_id = callback.from_user.id

    adult_dto = await profile_service.get_user_profile_dto(
        adult_user_id,
    )

    if adult_dto.role not in ("parent", "observer"):
        await _safe_callback_answer(
            callback,
            "Раздел доступен только родителям и наблюдателям.",
            show_alert=True,
        )
        return

    students = await students_service.get_students_for_adult(
        adult_user_id=adult_user_id,
    )

    if not students:
        await _safe_edit_text(
            callback.message,
            (
                "🔔 <b>Уведомления по ученикам</b>\n\n"
                "У вас пока нет доступных профилей учеников."
            ),
            reply_markup=Keyboards.get_settings_main_kb(
                adult_dto,
            ),
        )

        await _safe_callback_answer(callback)
        return
    
    dicts_dto = await schedule_service.get_school_dictionaries()
    view_models = StudentsService.build_student_view_models(
        students,
        dicts_dto,
    )
    text = UIRenderer.render_parent_student_notification_menu()

    keyboard = Keyboards.get_student_notification_select_kb(
        view_models,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

# Настройки самого родителя
@router.callback_query(F.data == callbacks.SETTINGS_MY_NOTIFICATIONS)
async def toggle_my_notifications(
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Пользователь меняет собственный глобальный флаг уведомлений.

    Для ребёнка операция запрещается, если settings заблокированы
    администратором семьи.
    """
    changed = await profile_service.toggle_own_notifications_enabled(
        user_id=callback.from_user.id,
    )

    if not changed:
        await callback.answer(
            "🔒 Ваши настройки уведомлений заблокированы "
            "администратором семьи.",
            show_alert=True,
        )
        return

    await _show_settings_menu(
        message_obj=callback.message,
        user_id=callback.from_user.id,
        profile_service=profile_service,
        schedule_service=schedule_service,
        is_callback=True,
    )

    await callback.answer("Настройки уведомлений обновлены.")

# ================= 5. ВВОД ВРЕМЕНИ СВОДКИ (FSM) =================

@router.callback_query(F.data == callbacks.SETTINGS_MY_SUMMARY_TIME)
async def prompt_my_summary_time(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    """
    Запрашивает время личной утренней сводки.

    Если ребёнок заблокирован администратором семьи, изменение запрещено.
    Parent и observer всегда настраивают свои сводки независимо.
    """
    if not await _require_own_notification_settings_access(
        callback=callback,
        profile_service=profile_service,
    ):
        return

    text = UIRenderer.render_summary_time_prompt()

    keyboard = Keyboards.get_summary_time_prompt_kb()

    await state.clear()

    await state.update_data(
        my_summary_time_user_id=callback.from_user.id,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await state.set_state(
        SettingsStates.waiting_for_my_time,
    )

    await _safe_callback_answer(callback)

@router.callback_query(
    SettingsStates.waiting_for_my_time,
    F.data == callbacks.SET_TIME_OFF,
)
async def disable_my_summary_time(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Выключает личную утреннюю сводку пользователя.

    morning_summary_time = NULL означает, что сводка отключена.
    """
    if not await validate_fsm_session(
        callback,
        state,
        expected={"my_summary_time_user_id": callback.from_user.id},
    ):
        return

    # Повторяем access check: пользователь мог потерять доступ
    # между открытием prompt и нажатием кнопки.
    if not await _require_own_notification_settings_access(
        callback=callback,
        profile_service=profile_service,
    ):
        await state.clear()
        return

    changed = await profile_service.update_own_morning_summary_time(
        user_id=callback.from_user.id,
        time_str=None,
    )

    await state.clear()

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось отключить утреннюю сводку.",
            show_alert=True,
        )
        return

    await _show_settings_menu(
        message_obj=callback.message,
        user_id=callback.from_user.id,
        profile_service=profile_service,
        schedule_service=schedule_service,
        is_callback=True,
    )

    await _safe_callback_answer(
        callback,
        "🔕 Утренняя сводка отключена.",
    )

@router.callback_query(
    SettingsStates.waiting_for_my_time,
    F.data == callbacks.SETTINGS_CANCEL_INPUT,
)
async def cancel_my_summary_time_input(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Отменяет ввод времени утренней сводки.

    БД не изменяется. Возвращаем пользователя в Settings.
    """
    if not await validate_fsm_session(
        callback,
        state,
        expected={"my_summary_time_user_id": callback.from_user.id},
    ):
        return

    await state.clear()

    await _show_settings_menu(
        message_obj=callback.message,
        user_id=callback.from_user.id,
        profile_service=profile_service,
        schedule_service=schedule_service,
        is_callback=True,
    )

    await _safe_callback_answer(callback)
        
@router.message(SettingsStates.waiting_for_my_time)
async def process_my_time(
    message: Message,
    state: FSMContext,
    time_service: TimeService,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Сохраняет личное время утренней сводки пользователя.
    """
    if not await validate_fsm_session(
        message,
        state,
        expected={"my_summary_time_user_id": message.from_user.id},
    ):
        return
    
    norm_time = time_service.normalize_time(message.text)

    if not norm_time:
        await message.answer(
            UIRenderer.render_invalid_time_format(),
            reply_markup=Keyboards.get_summary_time_prompt_kb(),
            parse_mode="HTML",
        )
        return

    changed = await profile_service.update_own_morning_summary_time(
        user_id=message.from_user.id,
        time_str=norm_time,
    )

    if not changed:
        await message.answer(
            "🔒 Ваши настройки уведомлений заблокированы "
            "администратором семьи."
        )
        return

    await state.clear()

    await _show_settings_menu(
        message_obj=message,
        user_id=message.from_user.id,
        profile_service=profile_service,
        schedule_service=schedule_service,
        is_callback=False,
    )
        

   
    
# ================= НАСТРОЙКИ УВЕДОМЛЕНИЙ =================
@router.callback_query(F.data == callbacks.SETTINGS_NOTIFICATIONS)
async def show_notifications_menu(callback: CallbackQuery, profile_service: ProfileService):
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    text = UIRenderer.render_notifications_menu(user_dto)
    kb = Keyboards.get_notifications_kb(user_dto)

# Глушим ошибку TelegramBadRequest, если меню не изменилось 
    # (например, при быстром двойном клике)
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        
    await callback.answer()
   
@router.callback_query(F.data == callbacks.SET_NOTIF_CHANGES)
async def toggle_changes_notif(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    if not await _require_own_notification_settings_access(
        callback=callback,
        profile_service=profile_service,
    ):
        return

    changed = await profile_service.toggle_own_boolean_notification_setting(
        user_id=callback.from_user.id,
        field_name="receive_schedule_changes",
    )
    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить настройки уведомлений.",
            show_alert=True,
        )
        return

    await show_notifications_menu(
        callback=callback,
        profile_service=profile_service,
    )

@router.callback_query(F.data == callbacks.SET_NOTIF_PRELESSON)
async def toggle_prelesson_notif(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    if not await _require_own_notification_settings_access(
        callback=callback,
        profile_service=profile_service,
    ):
        return

    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    new_value = (
        0
        if user_dto.pre_lesson_offset_minutes > 0
        else 10
    )

    changed = await profile_service.update_own_integer_notification_setting(
        user_id=callback.from_user.id,
        field_name="pre_lesson_offset_minutes",
        value=new_value,
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить настройку предурочных уведомлений.",
            show_alert=True,
        )
        return

    await show_notifications_menu(
        callback=callback,
        profile_service=profile_service,
    )    

@router.callback_query(F.data == callbacks.SET_NOTIF_EXTRA)
async def toggle_extra_notif(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    if not await _require_own_notification_settings_access(
        callback=callback,
        profile_service=profile_service,
    ):
        return

    changed = await profile_service.toggle_own_boolean_notification_setting(
        user_id=callback.from_user.id,
        field_name="receive_extra_class_reminders",
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить настройку дополнительных занятий.",
            show_alert=True,
        )
        return

    await show_notifications_menu(
        callback=callback,
        profile_service=profile_service,
    )

#PSN

@router.callback_query(
    ParentStudentSettingsCD.filter()
)
async def show_parent_student_notification_settings(
    callback: CallbackQuery,
    callback_data: ParentStudentSettingsCD,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Показывает настройки текущего взрослого
    для выбранного student profile.
    """
    student_id = callback_data.student_id

    dto = await profile_service.get_parent_student_notification_settings(
        parent_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if dto is None:
        await _safe_callback_answer(
            callback,
            "У вас нет доступа к настройкам этого ученика.",
            show_alert=True,
        )
        return
    
    # 1. Получаем настройки и словари
    dicts_dto = await schedule_service.get_school_dictionaries()

    # 2. Используем хелперы DTO для получения отформатированного текста
    vm = ProfileService.build_parent_student_notification_view_model(
        dto,
        dicts_dto,
    )
    text = UIRenderer.render_parent_student_notification_settings(vm)

    keyboard = (
        Keyboards.get_parent_student_notification_settings_kb(
            dto,
        )
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    ParentStudentToggleCD.filter()
)
async def toggle_parent_student_notification_setting(
    callback: CallbackQuery,
    callback_data: ParentStudentToggleCD,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Переключает одну personal adult subscription
    по student profile.
    """
    setting_token, student_id = callback_data.setting, callback_data.student_id

    setting_map = {
        "morning": "receive_morning_summary",
        "prelesson": "receive_pre_lesson_reminders",
        "changes": "receive_schedule_changes",
        "extra": "receive_extra_class_reminders",
    }

    setting_name = setting_map.get(setting_token)

    if setting_name is None:
        await _safe_callback_answer(
            callback,
            "Неизвестный тип уведомления.",
            show_alert=True,
        )
        return

    dto = await profile_service.get_parent_student_notification_settings(
        parent_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if dto is None:
        await _safe_callback_answer(
            callback,
            "Настройки больше недоступны.",
            show_alert=True,
        )
        return

    changed = (
        await profile_service.toggle_parent_student_notification_setting(
            parent_user_id=callback.from_user.id,
            student_id=student_id,
            setting_name=setting_name,
        )
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить настройку. "
            "Возможно, доступ к ученику был отозван.",
            show_alert=True,
        )
        return

    new_value = not getattr(dto, setting_name)
    dto = replace(dto, **{setting_name: new_value})

    # 1. Получаем настройки и словари
    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = ProfileService.build_parent_student_notification_view_model(
        dto,
        dicts_dto,
    )
    text = UIRenderer.render_parent_student_notification_settings(vm)

    keyboard = (
        Keyboards.get_parent_student_notification_settings_kb(
            dto,
        )
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(
        callback,
        "✅ Настройка обновлена.",
    )