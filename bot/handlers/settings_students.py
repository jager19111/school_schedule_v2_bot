# Путь: bot/handlers/settings_students.py
# Описание: Управление профилями учеников в семье: виртуальные профили, привязка Telegram, настройка прав, изменение класса и группы.

import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot import callbacks
from bot.callbacks import (
    AdultExtraPermissionToggleCD,
    StudentClaimCD,
    StudentDeleteCD,
    StudentDeleteConfirmCD,
    StudentDetailsCD,
    StudentEditClassCD,
    StudentEditGroupCD,
    StudentEditStartCD,
    StudentExtraPermissionsCD,
    StudentTelegramLockCD,
    StudentTelegramPrelessonCD,
    StudentTelegramSettingsCD,
    StudentTelegramSummaryCD,
    StudentTelegramSummaryOffCD,
    StudentTelegramToggleCD,
    VirtualStudentClassCD,
    VirtualStudentGroupCD,
)
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from core.models.dto import StudentProfileDTO
from services.profiles_service import ProfileService
from services.students_service import StudentsService
from services.schedule_service import ScheduleService
from services.time_service import TimeService
from bot.utils.fsm_guard import validate_fsm_session
from bot.utils.safe_send import _safe_edit_text, _safe_callback_answer
from bot.handlers.settings import SettingsStates, build_telegram_share_link

logger = logging.getLogger(__name__)
router = Router()

async def _require_family_admin_for_student(
    *,
    callback: CallbackQuery,
    profile_service: ProfileService,
    student_id: int,
) -> bool:
    """
    Проверяет права family admin на конкретный student profile.
    """
    is_admin = await profile_service.is_family_admin_for_student(
        admin_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if is_admin:
        return True

    await _safe_callback_answer(
        callback,
        "Только администратор семьи может менять профиль ученика.",
        show_alert=True,
    )

    return False

async def _show_student_telegram_settings(
    *,
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    student_id: int,
) -> bool:
    """
    Загружает и рендерит Telegram settings student profile.

    ProfileService возвращает None, если:
    - student virtual;
    - инициатор не family admin;
    - student отсутствует;
    - Telegram user больше не связан с profile.
    """
    dto = await profile_service.get_student_telegram_settings_for_admin(
        admin_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if dto is None:
        return False

    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = ProfileService.build_student_telegram_settings_view_model(
        dto,
        dicts_dto,
    )
    text = UIRenderer.render_student_telegram_settings(vm)

    keyboard = Keyboards.get_student_telegram_settings_kb(
        dto,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    return True

async def _show_family_students_menu(
    *,
    callback: CallbackQuery,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Рендерит список student_profiles, доступных текущему взрослому.
    """
    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if user_dto.role not in ("parent", "observer"):
        await _safe_callback_answer(
            callback,
            "Раздел учеников доступен только взрослым.",
            show_alert=True,
        )
        return

    if not user_dto.family_id:
        await _safe_callback_answer(
            callback,
            "Вы не состоите в семье.",
            show_alert=True,
        )
        return

    is_family_admin = await profile_service.is_family_admin(
        user_id=callback.from_user.id,
        family_id=user_dto.family_id,
    )

    students = await students_service.get_students_for_adult(
        adult_user_id=callback.from_user.id,
    )

    dicts_dto = await schedule_service.get_school_dictionaries()
    view_models = StudentsService.build_student_view_models(
        students,
        dicts_dto,
    )
    text = UIRenderer.render_family_students(view_models)
    keyboard = Keyboards.get_family_students_kb(
        view_models,
        is_family_admin=is_family_admin,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )
                            
@router.callback_query(F.data == callbacks.FAMILY_STUDENTS)
async def show_family_students(
    callback: CallbackQuery,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    await _show_family_students_menu(
        callback=callback,
        profile_service=profile_service,
        students_service=students_service,
        schedule_service=schedule_service
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(F.data == callbacks.STUDENT_ADD)
async def start_add_virtual_student(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if not user_dto.family_id:
        await _safe_callback_answer(
            callback,
            "Вы не состоите в семье.",
            show_alert=True,
        )
        return

    is_family_admin = await profile_service.is_family_admin(
        user_id=callback.from_user.id,
        family_id=user_dto.family_id,
    )

    if not is_family_admin:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может добавлять учеников.",
            show_alert=True,
        )
        return

    await state.update_data(
        virtual_student_admin_id=callback.from_user.id,
        virtual_student_family_id=user_dto.family_id,
    )

    await _safe_edit_text(
        callback.message,
        UIRenderer.render_virtual_student_name_prompt(),
        reply_markup=Keyboards.get_cancel_keyboard(),
    )

    await state.set_state(
        SettingsStates.waiting_for_virtual_student_name,
    )

    await _safe_callback_answer(callback)
    
@router.message(
    SettingsStates.waiting_for_virtual_student_name
)
async def process_virtual_student_name(
    message: Message,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    name = message.text.strip()

    if not name:
        await message.answer(
            "❌ Введите имя ученика."
        )
        return

    if len(name) > 64:
        await message.answer(
            "❌ Имя слишком длинное. Используйте до 64 символов."
        )
        return

    if not await validate_fsm_session(
        message,
        state,
        expected={"virtual_student_admin_id": message.from_user.id},
    ):
        return

    # 1. Запрашиваем справочники школы единым запросом через ScheduleServiceV2
    dicts_dto = await schedule_service.get_school_dictionaries()

    await state.update_data(
        virtual_student_name=name,
    )

    # 2. Передаем ClassListDTO через вспомогательное свойство as_class_list
    await message.answer(
        "🎓 <b>Выберите класс ученика</b>",
        reply_markup=Keyboards.get_student_class_selection_kb(
            dto=dicts_dto.as_class_list,
        ),
        parse_mode="HTML",
    )

    await state.set_state(
        SettingsStates.waiting_for_virtual_student_group,
    )
    
@router.callback_query(
    SettingsStates.waiting_for_virtual_student_group,
    VirtualStudentClassCD.filter(),
)
async def select_virtual_student_class(
    callback: CallbackQuery,
    callback_data: VirtualStudentClassCD,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    class_id = callback_data.class_id

    if not await validate_fsm_session(
        callback,
        state,
        expected={"virtual_student_admin_id": callback.from_user.id},
    ):
        return

    # 1. Запрашиваем справочники школы единым запросом
    dicts_dto = await schedule_service.get_school_dictionaries()

    await state.update_data(
        virtual_student_class_id=class_id,
    )

    # 2. Передаем GroupListDTO через вспомогательное свойство as_group_list
    await _safe_edit_text(
        callback.message,
        (
            "👥 <b>Выберите группу ученика</b>\n\n"
            "Если группа неизвестна, выберите «Весь класс»."
        ),
        reply_markup=Keyboards.get_student_group_selection_kb(
            dto=dicts_dto.as_group_list,
        ),
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    SettingsStates.waiting_for_virtual_student_group,
    VirtualStudentGroupCD.filter(),
)
async def create_virtual_student(
    callback: CallbackQuery,
    callback_data: VirtualStudentGroupCD,
    state: FSMContext,
    students_service: StudentsService,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    group_id = callback_data.group_id

    if not await validate_fsm_session(
        callback,
        state,
        expected={"virtual_student_admin_id": callback.from_user.id},
    ):
        return

    data = await state.get_data()
    admin_user_id = data.get("virtual_student_admin_id")
    family_id = data.get("virtual_student_family_id")
    name = data.get("virtual_student_name")
    class_id = data.get("virtual_student_class_id")

    if not family_id or not name or not class_id:
        await state.clear()
        await _safe_callback_answer(
            callback,
            "Состояние добавления устарело.",
            show_alert=True,
        )
        return

    response = await students_service.create_virtual_student(
        admin_user_id=admin_user_id,
        family_id=family_id,
        name=name,
        class_id=class_id,
        group_id=group_id,
    )

    await state.clear()

    if not response.success:
        await _safe_callback_answer(
            callback,
            "Не удалось добавить ученика. "
            "Проверьте права администратора семьи.",
            show_alert=True,
        )
        return

    await _show_family_students_menu(
        callback=callback,
        profile_service=profile_service,
        schedule_service=schedule_service,
        students_service=students_service,
    )

    await _safe_callback_answer(
        callback,
        "✅ Ученик добавлен.",
    )
    
@router.callback_query(
    StudentDetailsCD.filter()
)
async def show_student_details(
    callback: CallbackQuery,
    callback_data: StudentDetailsCD,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    student_id = callback_data.student_id

    result = await students_service.get_student_for_adult(
        adult_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if result is None:
        await _safe_callback_answer(
            callback,
            "Ученик не найден или у вас нет доступа.",
            show_alert=True,
        )
        return

    student, access = result
    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = StudentsService.build_student_view_model(student, dicts_dto)
    text = UIRenderer.render_student_details(vm)
    keyboard = Keyboards.get_student_details_kb(
        vm,
        is_family_admin=access.is_family_admin,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    StudentDeleteCD.filter()
)
async def confirm_delete_virtual_student(
    callback: CallbackQuery,
    callback_data: StudentDeleteCD,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    student_id = callback_data.student_id

    result = await students_service.get_student_for_adult(
        adult_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if result is None:
        await _safe_callback_answer(
            callback,
            "Ученик не найден или у вас нет доступа.",
            show_alert=True,
        )
        return

    student, access = result

    if not access.is_family_admin:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может удалять учеников.",
            show_alert=True,
        )
        return

    if student.telegram_user_id is not None:
        await _safe_callback_answer(
            callback,
            "Нельзя удалить ученика с подключённым Telegram. "
            "Сначала потребуется отдельный flow отвязки профиля.",
            show_alert=True,
        )
        return

    # --- ПРИМЕНЕННЫЙ ПАТЧ ---
    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = StudentsService.build_student_view_model(student, dicts_dto)
    text = UIRenderer.render_virtual_student_delete_confirmation(vm)
    # ------------------------

    keyboard = Keyboards.get_student_delete_confirmation_kb(
        student.id,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    StudentDeleteConfirmCD.filter()
)
async def delete_virtual_student(
    callback: CallbackQuery,
    callback_data: StudentDeleteConfirmCD,
    students_service: StudentsService,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    student_id = callback_data.student_id

    response = await students_service.delete_virtual_student(
        admin_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if not response.success:
        await _safe_callback_answer(
            callback,
            "Не удалось удалить ученика. "
            "Возможно, Telegram уже подключён или у вас нет прав.",
            show_alert=True,
        )
        return

    await _show_family_students_menu(
        callback=callback,
        profile_service=profile_service,
        students_service=students_service,
        schedule_service=schedule_service,
    )

    await _safe_callback_answer(
        callback,
        "🗑 Ученик удалён.",
    )

@router.callback_query(
    StudentTelegramSettingsCD.filter()
)
async def show_student_telegram_settings(
    callback: CallbackQuery,
    callback_data: StudentTelegramSettingsCD,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin открывает personal Telegram settings ученика.
    """
    student_id = callback_data.student_id

    await state.clear()

    shown = await _show_student_telegram_settings(
        callback=callback,
        profile_service=profile_service,
        schedule_service=schedule_service,
        student_id=student_id,
    )

    if not shown:
        await _safe_callback_answer(
            callback,
            (
                "Настройки недоступны. Убедитесь, что ученик "
                "подключён к Telegram и вы администратор семьи."
            ),
            show_alert=True,
        )
        return

    await _safe_callback_answer(callback)

@router.callback_query(
    StudentTelegramToggleCD.filter()
)
async def toggle_student_telegram_setting(
    callback: CallbackQuery,
    callback_data: StudentTelegramToggleCD,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin переключает personal boolean setting
    Telegram-linked student profile.
    """
    setting_token, student_id = callback_data.setting, callback_data.student_id

    setting_map = {
        "notif": "is_notifications_enabled",
        "changes": "receive_schedule_changes",
        "extra": "receive_extra_class_reminders",
        "own_extra": "can_manage_own_extra_classes",
    }

    field_name = setting_map.get(setting_token)

    if field_name is None:
        await _safe_callback_answer(
            callback,
            "Неизвестная настройка.",
            show_alert=True,
        )
        return

    changed = (
        await profile_service.toggle_student_telegram_boolean_setting(
            admin_user_id=callback.from_user.id,
            student_id=student_id,
            field_name=field_name,
        )
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            (
                "Не удалось изменить настройку. "
                "Проверьте права администратора и связь Telegram."
            ),
            show_alert=True,
        )
        return

    shown = await _show_student_telegram_settings(
        callback=callback,
        profile_service=profile_service,
        schedule_service=schedule_service,
        student_id=student_id,
    )

    if not shown:
        await _safe_callback_answer(
            callback,
            "Настройки больше недоступны.",
            show_alert=True,
        )
        return

    await _safe_callback_answer(
        callback,
        "✅ Настройка обновлена.",
    )

@router.callback_query(
    StudentTelegramPrelessonCD.filter()
)
async def toggle_student_telegram_prelesson(
    callback: CallbackQuery,
    callback_data: StudentTelegramPrelessonCD,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Включает или выключает pre-lesson reminders Telegram child.

    0 минут = выключено.
    10 минут = стандартное включённое значение.
    """
    student_id = callback_data.student_id

    dto = await profile_service.get_student_telegram_settings_for_admin(
        admin_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if dto is None:
        await _safe_callback_answer(
            callback,
            "Настройки недоступны.",
            show_alert=True,
        )
        return

    new_value = (
        0
        if dto.pre_lesson_offset_minutes > 0
        else 10
    )

    changed = (
        await profile_service.update_student_telegram_integer_setting(
            admin_user_id=callback.from_user.id,
            student_id=student_id,
            field_name="pre_lesson_offset_minutes",
            value=new_value,
        )
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить предурочные напоминания.",
            show_alert=True,
        )
        return

    await _show_student_telegram_settings(
        callback=callback,
        profile_service=profile_service,
        schedule_service=schedule_service,
        student_id=student_id,
    )

    state_text = (
        "включены за 10 минут"
        if new_value > 0
        else "выключены"
    )

    await _safe_callback_answer(
        callback,
        f"✅ Напоминания {state_text}.",
    )

@router.callback_query(
    StudentTelegramLockCD.filter()
)
async def toggle_student_telegram_settings_lock(
    callback: CallbackQuery,
    callback_data: StudentTelegramLockCD,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin включает/выключает lock personal settings child.
    """
    student_id = callback_data.student_id

    dto = await profile_service.get_student_telegram_settings_for_admin(
        admin_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if dto is None:
        await _safe_callback_answer(
            callback,
            "Настройки недоступны.",
            show_alert=True,
        )
        return

    new_locked_value = not dto.child_notification_settings_locked

    changed = await profile_service.set_student_notification_settings_locked(
        admin_user_id=callback.from_user.id,
        student_id=student_id,
        locked=new_locked_value,
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить блокировку настроек.",
            show_alert=True,
        )
        return

    await _show_student_telegram_settings(
        callback=callback,
        profile_service=profile_service,
        schedule_service=schedule_service,
        student_id=student_id,
    )

    await _safe_callback_answer(
        callback,
        (
            "🔒 Настройки ребёнка заблокированы."
            if new_locked_value
            else "🔓 Блокировка настроек ребёнка снята."
        ),
    )

@router.callback_query(
    StudentTelegramSummaryCD.filter()
)
async def prompt_student_telegram_summary_time(
    callback: CallbackQuery,
    callback_data: StudentTelegramSummaryCD,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin начинает изменение времени утренней сводки
    Telegram-linked student profile.
    """
    student_id = callback_data.student_id

    dto = await profile_service.get_student_telegram_settings_for_admin(
        admin_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if dto is None:
        await _safe_callback_answer(
            callback,
            "Настройки недоступны.",
            show_alert=True,
        )
        return

    await state.clear()

    await state.update_data(
        student_tg_settings_admin_id=callback.from_user.id,
        student_tg_settings_student_id=student_id,
    )

    # --- ПРИМЕНЕННЫЙ ПАТЧ ---
    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = ProfileService.build_student_telegram_settings_view_model(
        dto,
        dicts_dto,
    )
    
    await _safe_edit_text(
        callback.message,
        UIRenderer.render_student_telegram_summary_time_prompt(
            vm,
        ),
        reply_markup=(
            Keyboards.get_student_telegram_summary_time_kb(
                student_id=student_id,
            )
        ),
    )
    # ------------------------

    await state.set_state(
        SettingsStates.waiting_for_student_telegram_summary_time,
    )

    await _safe_callback_answer(callback)
    

@router.callback_query(
    SettingsStates.waiting_for_student_telegram_summary_time,
    StudentTelegramSummaryOffCD.filter(),
)
async def disable_student_telegram_summary_time(
    callback: CallbackQuery,
    callback_data: StudentTelegramSummaryOffCD,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Отключает personal morning summary Telegram child.
    """
    student_id = callback_data.student_id

    if not await validate_fsm_session(
        callback,
        state,
        expected={
            "student_tg_settings_admin_id": callback.from_user.id,
            "student_tg_settings_student_id": student_id
        },
    ):
        return

    changed = (
        await profile_service.update_student_telegram_morning_summary_time(
            admin_user_id=callback.from_user.id,
            student_id=student_id,
            time_str=None,
        )
    )

    await state.clear()

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось отключить утреннюю сводку.",
            show_alert=True,
        )
        return

    await _show_student_telegram_settings(
        callback=callback,
        profile_service=profile_service,
        schedule_service=schedule_service,
        student_id=student_id,
    )

    await _safe_callback_answer(
        callback,
        "🔕 Утренняя сводка отключена.",
    )

@router.message(
    SettingsStates.waiting_for_student_telegram_summary_time
)
async def save_student_telegram_summary_time(
    message: Message,
    state: FSMContext,
    time_service: TimeService,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Сохраняет время personal morning summary Telegram child.
    """
    if not await validate_fsm_session(
        message,
        state,
        expected={"student_tg_settings_admin_id": message.from_user.id},
    ):
        return

    data = await state.get_data()
    admin_user_id = data.get("student_tg_settings_admin_id")
    student_id = data.get("student_tg_settings_student_id")
    
    if student_id is None:
        await state.clear()
        await message.answer(
            "❌ Состояние настройки устарело. "
            "Откройте профиль ученика заново."
        )
        return

    normalized_time = time_service.normalize_time(
        message.text,
    )

    if normalized_time is None:
        await message.answer(
            "❌ Неверный формат времени. "
            "Например: <code>07:00</code>.",
            reply_markup=(
                Keyboards.get_student_telegram_summary_time_kb(
                    student_id=student_id,
                )
            ),
            parse_mode="HTML",
        )
        return

    changed = (
        await profile_service.update_student_telegram_morning_summary_time(
            admin_user_id=admin_user_id,
            student_id=student_id,
            time_str=normalized_time,
        )
    )

    await state.clear()

    if not changed:
        await message.answer(
            "❌ Не удалось сохранить время утренней сводки."
        )
        return

    dto = await profile_service.get_student_telegram_settings_for_admin(
        admin_user_id=admin_user_id,
        student_id=student_id,
    )

    if dto is None:
        await message.answer(
            "✅ Время сохранено, но профиль ученика больше недоступен."
        )
        return

    # --- ПРИМЕНЕННЫЙ ПАТЧ ---
    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = ProfileService.build_student_telegram_settings_view_model(
        dto,
        dicts_dto,
    )

    await message.answer(
        "✅ <b>Время утренней сводки обновлено.</b>\n\n"
        + UIRenderer.render_student_telegram_settings(vm),
        reply_markup=Keyboards.get_student_telegram_settings_kb(
            dto,
        ),
        parse_mode="HTML",
    )
    # ------------------------

@router.callback_query(
    StudentClaimCD.filter()
)
async def create_student_claim_invite(
    callback: CallbackQuery,
    callback_data: StudentClaimCD,
    bot: Bot,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin выпускает одноразовый claim link
    для existing virtual student.
    """
    student_id = callback_data.student_id

    admin_user_id = callback.from_user.id

    invite = await students_service.create_student_claim_invite(
        admin_user_id=admin_user_id,
        student_id=student_id,
        expires_in_hours=24,
    )

    if invite is None:
        await _safe_callback_answer(
            callback,
            "Не удалось создать ссылку. "
            "Проверьте, что ученик virtual и вы администратор семьи.",
            show_alert=True,
        )
        return

    me = await bot.get_me()

    if not me.username:
        logger.error(
            "Bot username is empty: cannot build student claim link."
        )

        await _safe_callback_answer(
            callback,
            "Не удалось создать ссылку: у bot не задан username.",
            show_alert=True,
        )
        return

    deep_link = (
        f"https://t.me/{me.username}"
        f"?start=claim_{invite.token}"
    )

    share_text = (
        "Открой эту ссылку, чтобы привязать Telegram "
        "к профилю школьного расписания."
    )

    share_link = build_telegram_share_link(
        deep_link=deep_link,
        share_text=share_text,
    )

    student = StudentProfileDTO(
        id=invite.student_id,
        family_id=invite.family_id,
        telegram_user_id=None,
        name=invite.student_name or "Ученик",
        class_id=invite.student_class_id or "—",
        group_id=invite.student_group_id or "ALL",
    )
    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = StudentsService.build_student_view_model(student, dicts_dto)
    text = UIRenderer.render_student_claim_invite_created(
        vm,
        expires_at=invite.expires_at,
        deep_link=deep_link,
    )

    keyboard = Keyboards.get_student_claim_invite_result_kb(
        share_link=share_link,
        deep_link=deep_link,
        student_id=invite.student_id,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(
        callback,
        "✅ Ссылка для привязки создана.",
    )
    
@router.callback_query(
    StudentEditStartCD.filter()
)
async def start_student_class_edit(
    callback: CallbackQuery,
    callback_data: StudentEditStartCD,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin начинает изменение class/group student profile.
    """
    student_id = callback_data.student_id

    student_result = await students_service.get_student_for_adult(
        adult_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if student_result is None:
        await _safe_callback_answer(
            callback,
            "Ученик не найден.",
            show_alert=True,
        )
        return

    student_dto, _access = student_result

    if not _access.is_family_admin:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может менять профиль ученика.",
            show_alert=True,
        )
        return

# 1. Получаем красивые названия через наш хелпер
    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = StudentsService.build_student_view_model(student_dto, dicts_dto)

    # --- ВОССТАНОВЛЕНО: Сохранение состояния FSM ---
    await state.clear()
    await state.update_data(
        student_edit_id=student_id,
        student_edit_admin_id=callback.from_user.id,
    )
    # -----------------------------------------------

    await _safe_edit_text(
        callback.message,
        UIRenderer.render_student_edit_class_prompt(vm),
        reply_markup=Keyboards.get_student_edit_class_selection_kb(
            dto=dicts_dto.as_class_list,
            student_id=student_id,
        ),
    )

    await state.set_state(
        SettingsStates.waiting_for_student_class,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    SettingsStates.waiting_for_student_class,
    StudentEditClassCD.filter(),
)
async def select_student_new_class(
    callback: CallbackQuery,
    callback_data: StudentEditClassCD,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Сохраняет выбранный class_id в FSM и открывает selector группы.
    """
    student_id, class_id = callback_data.student_id, callback_data.class_id

    if not await validate_fsm_session(
        callback,
        state,
        expected={
            "student_edit_admin_id": callback.from_user.id,
            "student_edit_id": student_id
        },
    ):
        return

    student_result = await students_service.get_student_for_adult(
        adult_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if student_result is None:
        await state.clear()
        await _safe_callback_answer(
            callback,
            "Ученик больше недоступен.",
            show_alert=True,
        )
        return

    student, _access = student_result

    if not _access.is_family_admin:
        await state.clear()
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может менять профиль ученика.",
            show_alert=True,
        )
        return
    
# 1. Получаем все школьные справочники за один вызов
    dicts_dto = await schedule_service.get_school_dictionaries()    
    vm = StudentsService.build_student_view_model(student, dicts_dto)
    new_class_name = dicts_dto.get_readable_class(class_id)
    
    # --- ВОССТАНОВЛЕНО: Запоминаем выбранный класс ---
    await state.update_data(
        student_edit_class_id=class_id,
    )
    # -------------------------------------------------

    await _safe_edit_text(
        callback.message,
        UIRenderer.render_student_edit_group_prompt(
            vm,
            new_class_name=new_class_name,
        ),
        reply_markup=Keyboards.get_student_edit_group_selection_kb(
            dto=dicts_dto.as_group_list,
            student_id=student_id,
        ),
    )

    await state.set_state(
        SettingsStates.waiting_for_student_group,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    SettingsStates.waiting_for_student_group,
    StudentEditGroupCD.filter(),
)
async def save_student_new_class_and_group(
    callback: CallbackQuery,
    callback_data: StudentEditGroupCD,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Финально сохраняет class_id/group_id student profile.

    StudentRepository синхронизирует users.class_id/group_id,
    if profile связан с Telegram-child.
    """
    student_id, group_id = callback_data.student_id, callback_data.group_id

    if not await validate_fsm_session(
        callback,
        state,
        expected={
            "student_edit_admin_id": callback.from_user.id,
            "student_edit_id": student_id
        },
    ):
        return

    data = await state.get_data()
    admin_user_id = data.get("student_edit_admin_id")
    state_student_id = data.get("student_edit_id")
    class_id = data.get("student_edit_class_id")

    if not class_id:
        await state.clear()
        await _safe_callback_answer(
            callback,
            "Состояние изменения устарело. Откройте профиль ученика заново.",
            show_alert=True,
        )
        return

    response = await students_service.update_student_profile(
        admin_user_id=admin_user_id,
        student_id=student_id,
        class_id=class_id,
        group_id=group_id,
    )

    await state.clear()

    if not response.success:
        await _safe_callback_answer(
            callback,
            "Не удалось сохранить класс и группу ученика.",
            show_alert=True,
        )
        return

    student_result = await students_service.get_student_for_adult(
        adult_user_id=callback.from_user.id,
        student_id=student_id,
    )

    if student_result is None:
        await _safe_callback_answer(
            callback,
            "Профиль ученика недоступен.",
            show_alert=True,
        )
        return

    student, access = student_result

    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = StudentsService.build_student_view_model(student, dicts_dto)
    text = (
        "✅ <b>Класс и группа обновлены.</b>\n\n"
        + UIRenderer.render_student_details(vm)
    )
    keyboard = Keyboards.get_student_details_kb(
        vm,
        is_family_admin=access.is_family_admin,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    StudentExtraPermissionsCD.filter()
)
async def show_adult_student_extra_classes_permissions(
    callback: CallbackQuery,
    callback_data: StudentExtraPermissionsCD,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin просматривает права других взрослых
    на управление кружками student profile.
    """
    student_id = callback_data.student_id

    admin_user_id = callback.from_user.id

    # Проверяем student profile и admin-rights.
    student_result = await students_service.get_student_for_adult(
        adult_user_id=admin_user_id,
        student_id=student_id,
    )

    if student_result is None:
        await _safe_callback_answer(
            callback,
            "Ученик не найден или недоступен.",
            show_alert=True,
        )
        return

    student, access = student_result

    if not access.is_family_admin:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может управлять "
            "правами взрослых.",
            show_alert=True,
        )
        return

    permissions = (
        await profile_service.get_adult_student_extra_classes_permissions(
            admin_user_id=admin_user_id,
            student_id=student_id,
        )
    )

    # None означает, что repository/service не подтвердили admin-rights.
    if permissions is None:
        await _safe_callback_answer(
            callback,
            "Не удалось проверить права администратора семьи.",
            show_alert=True,
        )
        return
    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = StudentsService.build_student_view_model(student, dicts_dto)
    text = UIRenderer.render_adult_student_extra_classes_permissions(
        vm,
        permissions,
    )


    keyboard = (
        Keyboards.get_adult_student_extra_classes_permissions_kb(
            student_id=student.id,
            permissions=permissions,
        )
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    AdultExtraPermissionToggleCD.filter()
)
async def toggle_adult_student_extra_classes_permission(
    callback: CallbackQuery,
    callback_data: AdultExtraPermissionToggleCD,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin переключает право другого adult
    управлять кружками student profile.
    """
    student_id, adult_user_id = callback_data.student_id, callback_data.adult_user_id

    admin_user_id = callback.from_user.id

    student_result = await students_service.get_student_for_adult(
        adult_user_id=admin_user_id,
        student_id=student_id,
    )

    if student_result is None:
        await _safe_callback_answer(
            callback,
            "Ученик не найден или больше недоступен.",
            show_alert=True,
        )
        return

    student, access = student_result

    if not access.is_family_admin:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может менять права "
            "других взрослых.",
            show_alert=True,
        )
        return

    permissions = (
        await profile_service.get_adult_student_extra_classes_permissions(
            admin_user_id=admin_user_id,
            student_id=student_id,
        )
    )

    if permissions is None:
        await _safe_callback_answer(
            callback,
            "Не удалось проверить список прав.",
            show_alert=True,
        )
        return

    selected_permission = next(
        (
            item
            for item in permissions
            if item.adult_user_id == adult_user_id
        ),
        None,
    )

    # Не позволяем подменой callback изменить право:
    # - admin;
    # - пользователя из другой семьи;
    # - взрослого, не связанного со student profile.
    if selected_permission is None:
        await _safe_callback_answer(
            callback,
            "Этот взрослый не найден среди участников семьи.",
            show_alert=True,
        )
        return

    changed = (
        await profile_service.set_adult_student_extra_classes_permission(
            admin_user_id=admin_user_id,
            adult_user_id=adult_user_id,
            student_id=student_id,
            can_manage=not (
                selected_permission.can_manage_extra_classes
            ),
        )
    )

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить право. "
            "Возможно, состав семьи изменился.",
            show_alert=True,
        )
        return

    refreshed_permissions = (
        await profile_service.get_adult_student_extra_classes_permissions(
            admin_user_id=admin_user_id,
            student_id=student_id,
        )
    )

    if refreshed_permissions is None:
        await _safe_callback_answer(
            callback,
            "Не удалось обновить список прав.",
            show_alert=True,
        )
        return

    dicts_dto = await schedule_service.get_school_dictionaries()
    vm = StudentsService.build_student_view_model(student, dicts_dto)
    
    # ИСПРАВЛЕНО: передаем refreshed_permissions, а не старый permissions
    text = UIRenderer.render_adult_student_extra_classes_permissions(
        vm,
        refreshed_permissions,
    )

    keyboard = (
        Keyboards.get_adult_student_extra_classes_permissions_kb(
            student_id=student.id,
            permissions=refreshed_permissions,
        )
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(
        callback,
        "✅ Право взрослого обновлено.",
    )