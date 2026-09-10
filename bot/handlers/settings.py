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
import contextlib
from bot import callbacks
from urllib.parse import quote
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from dataclasses import replace

from services.profiles_service import ProfileService
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from core.models.dto import StudentProfileDTO, StudentProfileViewModel, WatchTargetViewModel
from services.students_service import StudentsService

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from services.time_service import TimeService
from services.schedule_service import ScheduleService
from bot.handlers.registration import RegistrationStates
from services.watch_targets_service import WatchTargetsService
from bot.utils.fsm_guard import validate_fsm_session


logger = logging.getLogger(__name__)
router = Router()

async def _safe_edit_text(
    message: Message,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> bool:
    """
    Безопасно обновляет inline-сообщение.

    Telegram выбрасывает TelegramBadRequest, например если:
    - новый текст и keyboard не отличаются от текущих;
    - сообщение нельзя изменить;
    - callback пришёл по старому/удалённому сообщению.

    Ошибка логируется, но не прерывает handler.
    Другие ошибки намеренно не подавляются.
    """
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return True
    except TelegramBadRequest as exc:
        logger.debug(
            "Telegram edit_text skipped: %s",
            exc,
        )
        return False


async def _safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    """
    Безопасно закрывает Telegram callback spinner.

    Не допускает, чтобы вторичный TelegramBadRequest ломал рабочую
    бизнес-операцию после успешного изменения БД.
    """
    try:
        await callback.answer(
            text=text,
            show_alert=show_alert,
        )
    except TelegramBadRequest as exc:
        logger.debug(
            "Telegram callback answer skipped: %s",
            exc,
        )
             

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

              
@router.callback_query(F.data == "settings:main")
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
    family_code = await profile_service.get_family_code(user_dto.family_id) if user_dto.family_id else None
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
        family_code=family_code, 
        class_name=class_name, 
        group_names=group_names
    )
    kb = Keyboards.get_settings_main_kb(user_dto)
    
    if is_callback:
        await message_obj.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message_obj.answer(text, reply_markup=kb, parse_mode="HTML")

# ================= ПЕРЕРЕГИСТРАЦИЯ =================
@router.callback_query(F.data == "auth:restart")
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

@router.callback_query(F.data == "auth:restart_confirm")
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
        
# ================= 3. УПРАВЛЕНИЕ СЕМЬЕЙ =================
# Порядок хендлеров важен
#1. family:invite_menu
#2. family:invite_role:
#3. family:invite_revoke_confirm:
#4. family:invite_revoke:
#5. family:invite:
#6. family:invites
@router.callback_query(F.data == "family:invite_menu")
async def show_family_invite_menu(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает admin-у список role-specific invites.
    """
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
            "Только администратор семьи может создавать приглашения.",
            show_alert=True,
        )
        return

    text = UIRenderer.render_family_invite_role_menu()
    keyboard = Keyboards.get_family_invite_role_kb()

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

@router.callback_query(
    F.data.startswith("family:invite_role:")
)
async def create_family_invite(
    callback: CallbackQuery,
    bot: Bot,
    profile_service: ProfileService,
) -> None:
    """
    Создаёт one-time role-specific invite и отдаёт deep link.
    """
    intended_role = callbacks.parse_family_invite_role(callback.data)
    if intended_role is None:
        await _safe_callback_answer(
            callback,
            "Некорректная роль приглашения.",
            show_alert=True,
        )
        return

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

    invite = await profile_service.create_family_invite(
        created_by_user_id=callback.from_user.id,
        family_id=user_dto.family_id,
        intended_role=intended_role,
        expires_in_hours=24,
    )

    if invite is None:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может создавать приглашения.",
            show_alert=True,
        )
        return

    me = await bot.get_me()

    if not me.username:
        logger.error(
            "Bot username is empty; cannot build deep link."
        )

        await _safe_callback_answer(
            callback,
            "Не удалось сформировать ссылку приглашения. "
            "У bot отсутствует username.",
            show_alert=True,
        )
        return

    deep_link = (
        f"https://t.me/{me.username}"
        f"?start=join_{invite.token}"
    )
    role_for_recipient = {
        "child": "ребёнка",
        "parent": "родителя",
        "observer": "наблюдателя",
    }[invite.intended_role]

    share_text = (
        "👋 Вас пригласили присоединиться к семье "
        "школьного расписания.\n\n"
        f"Роль: {role_for_recipient}.\n"
        "Откройте ссылку и завершите регистрацию."
    )

    share_link = build_telegram_share_link(
        deep_link=deep_link,
        share_text=share_text,
    )
    
    role_label = {
        "child": "Ребёнок с Telegram",
        "parent": "Родитель",
        "observer": "Наблюдатель",
    }[invite.intended_role]

    text = UIRenderer.render_family_invite_created(
        role_label=role_label,
        expires_at=invite.expires_at,
    )

    keyboard = Keyboards.get_family_invite_result_kb(
        share_link=share_link,
        deep_link=deep_link,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await callback.message.answer(
        "📎 <b>Ссылка приглашения</b>\n\n"
        f"{deep_link}\n\n"
        "Вы можете скопировать или переслать это сообщение. "
        "Ссылка одноразовая и действует ограниченное время.",
        parse_mode="HTML",
    )
    
    await _safe_callback_answer(
        callback,
        "Приглашение создано.",
    )

@router.callback_query(
    F.data.startswith("family:invite_revoke_confirm:")
)
async def revoke_family_invite(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Отзывает invite после явного подтверждения.
    """
    invite_id = callbacks.parse_family_invite_revoke_confirm(callback.data)
    if invite_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор приглашения.",
            show_alert=True,
        )
        return

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

    revoked = await profile_service.revoke_family_invite(
        invite_id=invite_id,
        family_id=user_dto.family_id,
        admin_user_id=callback.from_user.id,
    )

    if not revoked:
        await _safe_callback_answer(
            callback,
            "Приглашение уже использовано, отозвано или недоступно.",
            show_alert=True,
        )
        return

    invites = await profile_service.get_active_family_invites(
        admin_user_id=callback.from_user.id,
        family_id=user_dto.family_id,
        )

    text = (
        "✅ <b>Приглашение отозвано.</b>\n\n"
        "Ссылка больше не позволит присоединиться к семье.\n\n"
        + UIRenderer.render_active_family_invites(invites)
    )

    keyboard = Keyboards.get_active_family_invites_kb(
        invites,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(
        callback,
        "Приглашение отозвано.",
    )
    
@router.callback_query(
    F.data.startswith("family:invite_revoke:")
)         
async def confirm_family_invite_revoke(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает confirmation перед revoke active invite.
    """
    invite_id = callbacks.parse_family_invite_revoke(callback.data)
    if invite_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор приглашения.",
            show_alert=True,
        )
        return

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

    invite = await profile_service.get_active_family_invite_by_id(
        invite_id=invite_id,
        family_id=user_dto.family_id,
        admin_user_id=callback.from_user.id,
    )

    if invite is None:
        await _safe_callback_answer(
            callback,
            "Приглашение уже недействительно.",
            show_alert=True,
        )
        return

    text = UIRenderer.render_family_invite_revoke_confirmation(
        invite,
    )

    keyboard = Keyboards.get_family_invite_revoke_confirmation_kb(
        invite_id=invite.id,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

@router.callback_query(F.data.startswith("family:invite:"))
async def show_family_invite_details(
    callback: CallbackQuery,
    bot: Bot,
    profile_service: ProfileService,
) -> None:
    """
    Показывает active invite и позволяет повторно отправить ссылку.
    """
    invite_id = callbacks.parse_family_invite(callback.data)
    if invite_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор приглашения.",
            show_alert=True,
        )
        return

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

    invite = await profile_service.get_active_family_invite_by_id(
        invite_id=invite_id,
        family_id=user_dto.family_id,
        admin_user_id=callback.from_user.id,
    )

    if invite is None:
        await _safe_callback_answer(
            callback,
            "Приглашение не найдено, уже использовано, отозвано "
            "или срок его действия истёк.",
            show_alert=True,
        )
        return

    me = await bot.get_me()

    if not me.username:
        await _safe_callback_answer(
            callback,
            "Bot username не задан, невозможно сформировать ссылку.",
            show_alert=True,
        )
        return

    deep_link = (
        f"https://t.me/{me.username}"
        f"?start=join_{invite.token}"
    )

    role_for_recipient = {
        "child": "ребёнка",
        "parent": "родителя",
        "observer": "наблюдателя",
    }[invite.intended_role]

    share_text = (
        "👋 Вас пригласили присоединиться к семье "
        "школьного расписания.\n\n"
        f"Роль: {role_for_recipient}.\n"
        "Откройте ссылку и завершите регистрацию."
    )

    share_link = build_telegram_share_link(
        deep_link=deep_link,
        share_text=share_text,
    )

    text = UIRenderer.render_family_invite_details(
        invite,
    )

    keyboard = Keyboards.get_family_invite_details_kb(
        invite_id=invite.id,
        share_link=share_link,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

                  
@router.callback_query(F.data == "family:invites")
async def show_active_family_invites(
    callback: CallbackQuery,
    profile_service: ProfileService,
) -> None:
    """
    Показывает family admin список активных invites.
    """
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

    invites = await profile_service.get_active_family_invites(
        admin_user_id=callback.from_user.id,
        family_id=user_dto.family_id,
    )

    if invites is None:
        await _safe_callback_answer(
            callback,
            "Только администратор семьи может видеть приглашения.",
            show_alert=True,
        )
        return

    text = UIRenderer.render_active_family_invites(
        invites,
    )

    keyboard = Keyboards.get_active_family_invites_kb(
        invites,
    )

    await _safe_edit_text(
        callback.message,
        text,
        reply_markup=keyboard,
    )

    await _safe_callback_answer(callback)

   
@router.callback_query(F.data == "settings:family")
async def show_family_management(
    callback: CallbackQuery, 
    profile_service: ProfileService, 
    schedule_service: ScheduleService
):
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    
    if not user_dto.family_id:
        text = UIRenderer.render_family_management_error()
        kb = Keyboards.get_settings_main_kb(user_dto)
        return await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

    is_family_admin = await profile_service.is_family_admin(
        user_id=callback.from_user.id,
        family_id=user_dto.family_id,
    )
    
    # Получаем полный состав семьи
    family_members = await profile_service.get_family_members(user_dto.family_id)
    dicts_dto = await schedule_service.get_school_dictionaries()
    view_models = ProfileService.build_family_member_view_models(
        family_members,
        current_user_id=user_dto.user_id,
        dicts_dto=dicts_dto,
    )
    text = UIRenderer.render_family_members_menu(view_models)
    kb = Keyboards.get_family_management_kb(
        current_role=user_dto.role,
        is_family_admin=is_family_admin,
    )

    
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(
    F.data == "settings:children_notifications"
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
@router.callback_query(F.data == "settings:my_notifications")
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
            
    # ================= 5. ВВОД ВРЕМЕНИ СВОДКИ (FSM) =================

@router.callback_query(F.data == "settings:my_summary_time")
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
    F.data == "set_time:off",
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
    F.data == "settings:cancel_input",
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
@router.callback_query(F.data == "settings:notifications")
async def show_notifications_menu(callback: CallbackQuery, profile_service: ProfileService):
    user_dto = await profile_service.get_user_profile_dto(callback.from_user.id)
    text = UIRenderer.render_notifications_menu(user_dto)
    kb = Keyboards.get_notifications_kb(user_dto)

# Глушим ошибку TelegramBadRequest, если меню не изменилось 
    # (например, при быстром двойном клике)
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        
    await callback.answer()
   
@router.callback_query(F.data == "set_notif:changes")
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

@router.callback_query(F.data == "set_notif:prelesson")
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

@router.callback_query(F.data == "set_notif:extra")
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

# ================= 5. СМЕНА КЛАССА И ГРУППЫ =================
   
    
@router.callback_query(F.data == "settings:change_class")
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
    
# Меню watch targets    
@router.callback_query(F.data == "watch:menu")
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

@router.callback_query(
    SettingsStates.waiting_for_self_edit_class,
    F.data.startswith("self_edit:class:"),
)
async def select_self_edit_class(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    """
    Child выбрал новый class_id и переходит к выбору группы.
    """
    class_id = callbacks.parse_self_edit_class(callback.data)
    if class_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный класс.",
            show_alert=True,
        )
        return

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
    F.data == "self_edit:back_to_class",
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
    F.data == "self_edit:cancel",
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
    F.data.startswith("self_edit:group:"),
)
async def save_self_edit_group(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Сохраняет новый class_id/group_id child и синхронизирует
    Telegram-linked student_profile.
    """
    group_id = callbacks.parse_self_edit_group(callback.data)
    if group_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректная группа.",
            show_alert=True,
        )
        return

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
                
@router.callback_query(F.data == "watch:add")
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
    F.data.startswith("watch:class:"),
)
async def select_watch_target_class(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    class_id = callbacks.parse_watch_class(callback.data)
    if class_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный класс.",
            show_alert=True,
        )
        return

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
    F.data.startswith("watch:group:"),
)
async def select_watch_target_group(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
    watch_targets_service: WatchTargetsService,
) -> None:
    group_id = callbacks.parse_watch_group(callback.data)
    if group_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректная группа.",
            show_alert=True,
        )
        return

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
    F.data.startswith("watch:target:")
)
async def show_watch_target_details(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService,
) -> None:
    target_id = callbacks.parse_watch_target(callback.data)
    if target_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор класса.",
            show_alert=True,
        )
        return

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
    F.data.startswith("watch:toggle:")
)
async def toggle_watch_target(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService
) -> None:
    target_id = callbacks.parse_watch_toggle(callback.data)
    if target_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор класса.",
            show_alert=True,
        )
        return

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

    # Локальный flip: меняем boolean в памяти, не вызывая другой хендлер
    # (show_watch_target_details парсит "watch:target:", а у нас "watch:toggle:")
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
    F.data.startswith("watch:changes:")
)
async def toggle_watch_target_schedule_changes(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Включает или выключает уведомления об изменениях
    только для одного watch target.
    """
    target_id = callbacks.parse_watch_changes(callback.data)
    if target_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор класса.",
            show_alert=True,
        )
        return

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
    F.data.startswith("watch:delete:")
)
async def confirm_delete_watch_target(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
) -> None:
    target_id = callbacks.parse_watch_delete(callback.data)
    if target_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор класса.",
            show_alert=True,
        )
        return

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
    F.data.startswith("watch:delete_confirm:")
)
async def delete_watch_target(
    callback: CallbackQuery,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService,
) -> None:
    target_id = callbacks.parse_watch_delete_confirm(callback.data)
    if target_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор класса.",
            show_alert=True,
        )
        return

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
    
# Виртуальный ученик

@router.callback_query(
    F.data.startswith("student_tg:show:")
)
async def show_student_telegram_settings(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin открывает personal Telegram settings ученика.
    """
    student_id = callbacks.parse_student_tg_show(callback.data)
    if student_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

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
    F.data.startswith("student_tg:toggle:")
)
async def toggle_student_telegram_setting(
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin переключает personal boolean setting
    Telegram-linked student profile.
    """
    parsed = callbacks.parse_student_tg_toggle(callback.data)
    if parsed is None:
        await _safe_callback_answer(
            callback,
            "Некорректные данные настройки.",
            show_alert=True,
        )
        return
    setting_token, student_id = parsed

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
    F.data.startswith("student_tg:prelesson:")
)
async def toggle_student_telegram_prelesson(
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Включает или выключает pre-lesson reminders Telegram child.

    0 минут = выключено.
    10 минут = стандартное включённое значение.
    """
    student_id = callbacks.parse_student_tg_prelesson(callback.data)
    if student_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

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
    F.data.startswith("student_tg:lock:")
)
async def toggle_student_telegram_settings_lock(
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin включает/выключает lock personal settings child.
    """
    student_id = callbacks.parse_student_tg_lock(callback.data)
    if student_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

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
    F.data.startswith("student_tg:summary:")
)
async def prompt_student_telegram_summary_time(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin начинает изменение времени утренней сводки
    Telegram-linked student profile.
    """
    student_id = callbacks.parse_student_tg_summary(callback.data)
    if student_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

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
    F.data.startswith("student_tg:summary_off:"),
)
async def disable_student_telegram_summary_time(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Отключает personal morning summary Telegram child.
    """
    student_id = callbacks.parse_student_tg_summary_off(callback.data)
    if student_id is None:
        await state.clear()
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

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
                            
@router.callback_query(F.data == "family:students")
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
    
@router.callback_query(F.data == "student:add")
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
    F.data.startswith("student:class:"),
)
async def select_virtual_student_class(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    class_id = callbacks.parse_student_class(callback.data)
    if class_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный класс.",
            show_alert=True,
        )
        return

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
    F.data.startswith("student:group:"),
)
async def create_virtual_student(
    callback: CallbackQuery,
    state: FSMContext,
    students_service: StudentsService,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    group_id = callbacks.parse_student_group(callback.data)
    if group_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректная группа.",
            show_alert=True,
        )
        return

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
    F.data.startswith("student:show:")
)
async def show_student_details(
    callback: CallbackQuery,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    student_id = callbacks.parse_student_show(callback.data)
    if student_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

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
    F.data.startswith("student:delete:")
)
async def confirm_delete_virtual_student(
    callback: CallbackQuery,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    student_id = callbacks.parse_student_delete(callback.data)
    if student_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

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
    F.data.startswith("student:delete_confirm:")
)
async def delete_virtual_student(
    callback: CallbackQuery,
    students_service: StudentsService,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    student_id = callbacks.parse_student_delete_confirm(callback.data)
    if student_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

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
    
    
#PSN

@router.callback_query(
    F.data.startswith("psn:student:")
)
async def show_parent_student_notification_settings(
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Показывает настройки текущего взрослого
    для выбранного student profile.
    """
    student_id = callbacks.parse_psn_student(callback.data)
    if student_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
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
    F.data.startswith("psn:toggle:")
)
async def toggle_parent_student_notification_setting(
    callback: CallbackQuery,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Переключает одну personal adult subscription
    по student profile.
    """
    parsed = callbacks.parse_psn_toggle(callback.data)
    if parsed is None:
        await _safe_callback_answer(
            callback,
            "Некорректные данные настройки.",
            show_alert=True,
        )
        return
    setting_token, student_id = parsed

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
        
@router.callback_query(
    F.data.startswith("student:claim:")
)
async def create_student_claim_invite(
    callback: CallbackQuery,
    bot: Bot,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin выпускает одноразовый claim link
    для existing virtual student.
    """
    student_id = callbacks.parse_student_claim(callback.data)
    if student_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

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
    F.data.startswith("student:edit_class:")
)
async def start_student_class_edit(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin начинает изменение class/group student profile.
    """
    student_id = callbacks.parse_student_edit_class(callback.data)
    if student_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
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
    F.data.startswith("student:edit_class_select:"),
)
async def select_student_new_class(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Сохраняет выбранный class_id в FSM и открывает selector группы.
    """
    parsed = callbacks.parse_student_edit_class_select(callback.data)
    if parsed is None:
        await _safe_callback_answer(
            callback,
            "Некорректный класс.",
            show_alert=True,
        )
        return
    student_id, class_id = parsed

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
    F.data.startswith("student:edit_group_select:"),
)
async def save_student_new_class_and_group(
    callback: CallbackQuery,
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
    parsed = callbacks.parse_student_edit_group_select(callback.data)
    if parsed is None:
        await _safe_callback_answer(
            callback,
            "Некорректная группа.",
            show_alert=True,
        )
        return
    student_id, group_id = parsed

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
    F.data.startswith("student:extra_permissions:")
)
async def show_adult_student_extra_classes_permissions(
    callback: CallbackQuery,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin просматривает права других взрослых
    на управление кружками student profile.
    """
    student_id = callbacks.parse_student_extra_permissions(callback.data)
    if student_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный идентификатор ученика.",
            show_alert=True,
        )
        return

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
    F.data.startswith("student_perm:toggle:")
)
async def toggle_adult_student_extra_classes_permission(
    callback: CallbackQuery,
    profile_service: ProfileService,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Family admin переключает право другого adult
    управлять кружками student profile.
    """
    parsed = callbacks.parse_student_perm_toggle(callback.data)
    if parsed is None:
        await _safe_callback_answer(
            callback,
            "Некорректные данные права доступа.",
            show_alert=True,
        )
        return
    student_id, adult_user_id = parsed

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
    
    #----------------------
    #   УЧИТЕЛЬ
    #----------------------
    
@router.callback_query(
    F.data == "settings:change_teacher"
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
    F.data.startswith("teacher_change:"),
)
async def save_teacher_change(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Сохраняет новый NIKA teacher_id для теку Telegram teacher.
    """
    teacher_id = callbacks.parse_teacher_change(callback.data)
    if teacher_id is None:
        await _safe_callback_answer(
            callback,
            "Некорректный учитель.",
            show_alert=True,
        )
        return

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