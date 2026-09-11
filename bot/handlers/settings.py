# Путь: bot/handlers/settings.py
# Описание: Ядро настроек. Хранит структуру, FSM-стейты, главные меню, перерегистрацию, самостоятельное изменение класса/группы и смену учителя.
# Структура
#family:students
#student:show:
#student:add
#student:delete:
#student:claim:
#student:edit_class:
#student:edit_class_select:
#student:edit_group_select:
#student:extra_permissions:

#student_perm:toggle:

#psn:student:
#psn:toggle:
#
#student_tg:show:
#student_tg:toggle:
#student_tg:summary:
#student_tg:summary_off:
#student_tg:prelesson:
#student_tg:lock:

import logging
from urllib.parse import quote
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot import callbacks
from bot.callbacks import SelfEditClassCD, SelfEditGroupCD, TeacherChangeCD
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.students_service import StudentsService
from bot.utils.fsm_guard import validate_fsm_session
from bot.utils.safe_send import _safe_edit_text, _safe_callback_answer

logger = logging.getLogger(__name__)
router = Router()

def build_telegram_share_link(
    *,
    deep_link: str,
    share_text: str,
) -> str:
    """
    Создаёт Telegram share URL.

    Используем quote(), а не urlencode()/quote_plus(),
    чтобы пробелы кодировались как %20, а не как +.
    Некоторые мобильные Telegram-клиенты отображают +
    буквально в тексте пересланного приглашения.
    """
    encoded_url = quote(
        deep_link,
        safe="",
    )

    encoded_text = quote(
        share_text,
        safe="",
    )

    return (
        "https://t.me/share/url"
        f"?url={encoded_url}"
        f"&text={encoded_text}"
    )

class SettingsStates(StatesGroup):
    waiting_for_my_time = State()
    waiting_for_child_time = State()
    waiting_for_watch_group = State()
    
    waiting_for_virtual_student_name = State()
    waiting_for_virtual_student_group = State()
    
    # Family admin → редактирование family student profile.
    waiting_for_student_class = State()
    waiting_for_student_group = State()

    # Child → собственный class/group self-edit.
    waiting_for_self_edit_class = State()
    waiting_for_self_edit_group = State()
    
    waiting_for_student_telegram_summary_time = State()
    
    waiting_for_teacher_change = State()

# ================= 1. ПОИСК ПО ШКОЛЕ =================

@router.message(F.text == "🏫 Поиск по школе")
async def show_school_search(message: Message):
    text = UIRenderer.render_school_search_menu()
    kb = Keyboards.get_school_search_kb()
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

# ================= 2. ГЛАВНЫЕ НАСТРОЙКИ =================

@router.message(F.text == "⚙️ Настройки")
async def settings_main_menu(message: Message, profile_service: ProfileService, schedule_service: ScheduleService):
    """Главное меню настроек. Вызывается из главного меню и после изменения настроек."""
    await _show_settings_menu(message, message.from_user.id, profile_service, schedule_service, is_callback=False)

              
@router.callback_query(F.data == callbacks.SETTINGS_MAIN)
async def settings_main_menu_cb(callback: CallbackQuery, profile_service: ProfileService, schedule_service: ScheduleService):
    """Главное меню настроек. Вызывается из коллбэка после изменения настроек."""
    await _show_settings_menu(callback.message, callback.from_user.id, profile_service, schedule_service, is_callback=True)
    await callback.answer()

async def _show_settings_menu(
    message_obj: Message, 
    user_id: int, 
    profile_service: ProfileService, 
    schedule_service: ScheduleService,
    is_callback: bool
):
    user_dto = await profile_service.get_user_profile_dto(user_id)
    is_family_admin = False
    if user_dto.family_id is not None:
        is_family_admin = await profile_service.is_family_admin(
            user_id=user_id,
            family_id=user_dto.family_id,
        )
    if not user_dto.is_fully_registered:
        if is_callback:
            try:
                await message_obj.edit_text(
                    UIRenderer.render_unregistered_error(),
                    parse_mode="HTML",
                )
            except TelegramBadRequest:
                pass
        else:
            await message_obj.answer(
                UIRenderer.render_unregistered_error(),
                parse_mode="HTML",
            )

        return
    # 1. Получаем все школьные справочники за один вызов
    dicts_dto = await schedule_service.get_school_dictionaries()
    
    # 2. Формируем красивые имена через встроенные хелперы DTO (если ID есть)
    class_name = dicts_dto.get_readable_class(user_dto.class_id) if user_dto.class_id else None
    group_names = dicts_dto.get_readable_group(user_dto.group_id) if user_dto.group_id else None
            
    # 3. Передаем чистые строки в рендерер
    text = UIRenderer.render_settings_main(
        user_dto=user_dto, 
        class_name=class_name, 
        group_names=group_names
    )
    text = UIRenderer.render_settings_main(
        user_dto,
        class_name=class_name,
        group_names=group_names,
        is_family_admin=is_family_admin,   # <-- новое
    )
    kb = Keyboards.get_settings_main_kb(user_dto)
    
    if is_callback:
        await message_obj.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message_obj.answer(text, reply_markup=kb, parse_mode="HTML")

# ================= ПЕРЕРЕГИСТРАЦИЯ =================
@router.callback_query(F.data == callbacks.AUTH_RESTART)
async def process_restart(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает последствия перерегистрации.

    Никакие данные здесь не удаляются.
    """
    impact = await profile_service.get_profile_reset_impact(
        user_id=callback.from_user.id,
    )

    if impact is None:
        await _safe_callback_answer(
            callback,
            "Не удалось найти ваш профиль.",
            show_alert=True,
        )
        return

    text = UIRenderer.render_profile_reset_confirmation(
        impact,
    )

    keyboard = Keyboards.get_profile_reset_confirmation_kb()

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

@router.callback_query(F.data == callbacks.AUTH_RESTART_CONFIRM)
async def confirm_restart(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    """
    Выполняет перерегистрацию только после явного подтверждения.
    """
    user_id = callback.from_user.id

    try:
        success = await profile_service.reset_user_profile(
            user_id=user_id,
        )

    except ValueError as exc:
        logger.warning(
            "Profile reset rejected: user_id=%s, error=%s",
            user_id,
            exc,
        )

        await _safe_callback_answer(
            callback,
            "Не удалось перерегистрировать профиль.",
            show_alert=True,
        )
        return

    except Exception:
        logger.exception(
            "Profile reset failed: user_id=%s",
            user_id,
        )

        await _safe_callback_answer(
            callback,
            "❌ Не удалось выполнить перерегистрацию. "
            "Попробуйте ещё раз.",
            show_alert=True,
        )
        return

    if not success:
        await _safe_callback_answer(
            callback,
            "Не удалось выполнить перерегистрацию.",
            show_alert=True,
        )
        return

    await state.clear()

    try:
        await callback.message.edit_text(
            "✅ Профиль сброшен.\n\n"
            "Отправьте /start, чтобы пройти регистрацию заново."
        )
    except TelegramBadRequest as exc:
        logger.debug(
            "Restart confirmation message update skipped: %s",
            exc,
        )

    await _safe_callback_answer(
        callback,
        "Профиль успешно сброшен.",
    )

# ================= 5. СМЕНА КЛАССА И ГРУППЫ =================
   
    
@router.callback_query(F.data == callbacks.SETTINGS_CHANGE_CLASS)
async def start_self_edit_class(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Child начинает изменение собственного класса и группы.

    Это самостоятельный settings flow. Он не использует
    RegistrationStates и generic class:/group: callbacks.
    """
    actor_user_id = callback.from_user.id

    actor = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    if not actor.is_fully_registered:
        await state.clear()

        await _safe_callback_answer(
            callback,
            "Сначала завершите регистрацию через /start.",
            show_alert=True,
        )
        return

    if actor.role != "child":
        await _safe_callback_answer(
            callback,
            "Изменение класса доступно только ученику.",
            show_alert=True,
        )
        return

    classes_dto = await schedule_service.get_classes_list()

    if not classes_dto.classes:
        await _safe_callback_answer(
            callback,
            "Список классов временно недоступен.",
            show_alert=True,
        )
        return

    await state.clear()

    await state.update_data(
        self_edit_user_id=actor_user_id,
    )

    await _safe_edit_text(
        callback.message,
        UIRenderer.render_class_selection(
            classes_dto,
        ),
        reply_markup=Keyboards.get_self_edit_class_selection_kb(
            classes_dto,
        ),
    )

    await state.set_state(
        SettingsStates.waiting_for_self_edit_class,
    )

    await _safe_callback_answer(callback)

@router.callback_query(
    SettingsStates.waiting_for_self_edit_class,
    SelfEditClassCD.filter(),
)
async def select_self_edit_class(
    callback: CallbackQuery,
    callback_data: SelfEditClassCD,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    """
    Child выбрал новый class_id и переходит к выбору группы.
    """
    class_id = callback_data.class_id

    if not await validate_fsm_session(
        callback,
        state,
        expected={"self_edit_user_id": callback.from_user.id},
    ):
        return

    groups_dto = await schedule_service.get_groups_list()

    await state.update_data(
        self_edit_class_id=class_id,
    )

    text, _ = UIRenderer.render_main_group_selection()

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=Keyboards.get_self_edit_group_selection_kb(
            groups_dto,
        ),
    )

    await state.set_state(
        SettingsStates.waiting_for_self_edit_group,
    )

    await _safe_callback_answer(callback)

@router.callback_query(
    SettingsStates.waiting_for_self_edit_group,
    F.data == callbacks.SELF_EDIT_BACK_TO_CLASS,
)
async def back_to_self_edit_class(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    """
    Возвращает child из group screen обратно к class screen.
    """
    if not await validate_fsm_session(
        callback,
        state,
        expected={"self_edit_user_id": callback.from_user.id},
    ):
        return

    classes_dto = await schedule_service.get_classes_list()

    # Класс пока не сохранён, поэтому очищаем промежуточный выбор.
    await state.update_data(
        self_edit_class_id=None,
    )

    await _safe_edit_text(
        callback.message,
        UIRenderer.render_class_selection(
            classes_dto,
        ),
        reply_markup=Keyboards.get_self_edit_class_selection_kb(
            classes_dto,
        ),
    )

    await state.set_state(
        SettingsStates.waiting_for_self_edit_class,
    )

    await _safe_callback_answer(callback)

@router.callback_query(
    F.data == callbacks.SELF_EDIT_CANCEL,
)
async def cancel_self_edit_class_group(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Отменяет изменение класса/группы ребёнка.

    На этом этапе в БД ещё ничего не сохранено.
    """
    if not await validate_fsm_session(
        callback,
        state,
        expected={"self_edit_user_id": callback.from_user.id},
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

@router.callback_query(
    SettingsStates.waiting_for_self_edit_group,
    SelfEditGroupCD.filter(),
)
async def save_self_edit_group(
    callback: CallbackQuery,
    callback_data: SelfEditGroupCD,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Сохраняет новый class_id/group_id child и синхронизирует
    Telegram-linked student_profile.
    """
    group_id = callback_data.group_id

    actor_user_id = callback.from_user.id
    
    if not await validate_fsm_session(
        callback,
        state,
        expected={"self_edit_user_id": actor_user_id},
    ):
        return

    data = await state.get_data()
    class_id = data.get("self_edit_class_id")

    if not class_id:
        await state.clear()

        await _safe_callback_answer(
            callback,
            "Не выбран класс. Начните изменение заново.",
            show_alert=True,
        )
        return

    # Повторная security-проверка:
    # пользователь мог стать unregistered, выйти из семьи
    # или изменить state между двумя callback-ами.
    actor = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    if (
        not actor.is_fully_registered
        or actor.role != "child"
    ):
        await state.clear()

        await _safe_callback_answer(
            callback,
            "Сначала завершите регистрацию через /start.",
            show_alert=True,
        )
        return

    await profile_service.set_child_class_and_group(
        actor_user_id,
        class_id,
        group_id,
    )

    student = await students_service.ensure_telegram_student_profile(
        telegram_user_id=actor_user_id,
    )

    if student is None:
        await state.clear()

        await _safe_callback_answer(
            callback,
            "Не удалось синхронизировать профиль ученика.",
            show_alert=True,
        )
        return

    await state.clear()

    await _show_settings_menu(
        message_obj=callback.message,
        user_id=actor_user_id,
        profile_service=profile_service,
        schedule_service=schedule_service,
        is_callback=True,
    )

    await _safe_callback_answer(
        callback,
        "✅ Класс и группа обновлены.",
    )

    #----------------------
    #   УЧИТЕЛЬ
    #----------------------
    
@router.callback_query(
    F.data == callbacks.SETTINGS_CHANGE_TEACHER
)
async def start_teacher_change(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Teacher меняет привязанный NIKA teacher profile.
    """
    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if user_dto.role != "teacher":
        await _safe_callback_answer(
            callback,
            "Этот раздел доступен только учителям.",
            show_alert=True,
        )
        return

    teachers_dto = await schedule_service.get_teachers_list()

    if not teachers_dto.teachers:
        await _safe_callback_answer(
            callback,
            "Справочник учителей пока недоступен.",
            show_alert=True,
        )
        return

    await state.clear()

    await state.update_data(
        teacher_change_user_id=callback.from_user.id,
    )

    await _safe_edit_text(
        callback.message,
        (
            "👨‍🏫 <b>Смена профиля учителя</b>\n\n"
            "Выберите себя из актуального справочника школы."
        ),
        reply_markup=Keyboards.get_teacher_change_kb(
            teachers_dto,
        ),
    )

    await state.set_state(
        SettingsStates.waiting_for_teacher_change,
    )

    await _safe_callback_answer(callback)
    
@router.callback_query(
    SettingsStates.waiting_for_teacher_change,
    TeacherChangeCD.filter(),
)
async def save_teacher_change(
    callback: CallbackQuery,
    callback_data: TeacherChangeCD,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Сохраняет новый NIKA teacher_id для теку Telegram teacher.
    """
    teacher_id = callback_data.teacher_id

    if not await validate_fsm_session(
        callback,
        state,
        expected={"teacher_change_user_id": callback.from_user.id},
    ):
        return

    teacher_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    if teacher_dto.role != "teacher":
        await state.clear()

        await _safe_callback_answer(
            callback,
            "Этот профиль больше не является профилем учителя.",
            show_alert=True,
        )
        return

    teachers_dto = await schedule_service.get_teachers_list()

    teacher_name = teachers_dto.teachers.get(
        teacher_id,
    )

    if teacher_name is None:
        await _safe_callback_answer(
            callback,
            "Учитель не найден в текущем справочнике.",
            show_alert=True,
        )
        return

    changed = await profile_service.set_teacher_profile(
        user_id=callback.from_user.id,
        teacher_id=teacher_id,
    )

    await state.clear()

    if not changed:
        await _safe_callback_answer(
            callback,
            "Не удалось изменить профиль учителя.",
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

    teacher_name_text = getattr(
        teacher_name,
        "name",
        teacher_name,
    )

    await _safe_callback_answer(
        callback,
        f"✅ Профиль изменён: {teacher_name_text}",
    )