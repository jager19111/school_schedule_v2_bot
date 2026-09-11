# Путь: bot/handlers/settings_family.py
# Описание: Управление составом семьи, генерация и отзыв инвайтов, просмотр активных приглашений.

import logging
import contextlib
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from bot import callbacks
from bot.callbacks import (
    FamilyInviteDetailsCD,
    FamilyInviteRevokeCD,
    FamilyInviteRevokeConfirmCD,
    FamilyInviteRoleCD,
)
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from bot.utils.safe_send import _safe_edit_text, _safe_callback_answer
from bot.handlers.settings import build_telegram_share_link

logger = logging.getLogger(__name__)
router = Router()

# ================= 3. УПРАВЛЕНИЕ СЕМЬЕЙ =================
# Порядок хендлеров важен
#1. family:invite_menu
#2. family:invite_role:
#3. family:invite_revoke_confirm:
#4. family:invite_revoke:
#5. family:invite:
#6. family:invites
@router.callback_query(F.data == callbacks.FAMILY_INVITE_MENU)
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
    FamilyInviteRoleCD.filter()
)
async def create_family_invite(
    callback: CallbackQuery,
    callback_data: FamilyInviteRoleCD,
    bot: Bot,
    profile_service: ProfileService,
) -> None:
    """
    Создаёт one-time role-specific invite и отдаёт deep link.
    """
    intended_role = callback_data.role

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
        "Ссылка одноразовая и действует 24 часа.",
        parse_mode="HTML",
    )
        # Короткий код — печатаемая форма для «продиктовать ребёнку»
    await callback.message.answer(
        f"📋 Код для ввода: <code>{invite.short_code}</code>\n"
        f"Код одноразовый и действует 24 часа.",
        parse_mode="HTML",
    )    
    await _safe_callback_answer(
        callback,
        "Приглашение создано.",
    )

@router.callback_query(
    FamilyInviteRevokeConfirmCD.filter()
)
async def revoke_family_invite(
    callback: CallbackQuery,
    callback_data: FamilyInviteRevokeConfirmCD,
    profile_service: ProfileService,
) -> None:
    """
    Отзывает invite после явного подтверждения.
    """
    invite_id = callback_data.invite_id

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
    FamilyInviteRevokeCD.filter()
)         
async def confirm_family_invite_revoke(
    callback: CallbackQuery,
    callback_data: FamilyInviteRevokeCD,
    profile_service: ProfileService,
) -> None:
    """
    Показывает confirmation перед revoke active invite.
    """
    invite_id = callback_data.invite_id

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

@router.callback_query(FamilyInviteDetailsCD.filter())
async def show_family_invite_details(
    callback: CallbackQuery,
    callback_data: FamilyInviteDetailsCD,
    bot: Bot,
    profile_service: ProfileService,
) -> None:
    """
    Показывает active invite и позволяет повторно отправить ссылку.
    """
    invite_id = callback_data.invite_id

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

                  
@router.callback_query(F.data == callbacks.FAMILY_INVITES)
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

   
@router.callback_query(F.data == callbacks.SETTINGS_FAMILY)
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