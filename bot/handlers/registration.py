import logging
import contextlib
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest

from services.profiles_service import ProfileService
from services.students_service import StudentsService
from core.repository.schedule_repository import ScheduleRepository
from services.schedule_service import ScheduleService
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from core.models.dto import ClassListDTO, GroupListDTO, FamilyCreatedDTO

logger = logging.getLogger(__name__)
router = Router()

class RegistrationStates(StatesGroup):
    waiting_for_role = State()
    waiting_for_name = State()
    waiting_for_family_action = State()
    waiting_for_family_code = State()
    waiting_for_class = State()
    waiting_for_group = State()
    
    waiting_for_claim_confirmation = State()
    waiting_for_claim_name = State()
    waiting_for_claim_class = State()
    waiting_for_claim_group = State()

@router.message(Command("start"))
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
) -> None:
    """
    Старт bot и обработка deep-link family invite.

    Обычный /start работает как раньше.
    /start join_<token> запускает роль, зафиксированную в invite.
    """
    user_id = message.from_user.id

    await profile_service.register_user_initial(
        user_id,
    )

    user_dto = await profile_service.get_user_profile_dto(
        user_id,
    )

    payload = (command.args or "").strip()

    # -------------------------------
    # Deep link student claim flow
    # -------------------------------
    if payload.startswith("claim_"):
        token = payload.removeprefix("claim_")

        # Ребёнок, уже состоящий в семье, не может быть silently
        # переведён в другую семью через forwarded link.
        if user_dto.family_id is not None:
            await message.answer(
                "⚠️ Вы уже состоите в семье.\n\n"
                "Для использования ссылки сначала выйдите "
                "из текущей семьи через настройки."
            )

            await state.clear()
            return

        # Пока не объединяем автоматом standalone profile
        # с существующим family virtual student profile.
        current_student = (
            await students_service.get_student_by_telegram_user_id(
                telegram_user_id=user_id,
            )
        )

        if current_student is not None:
            await message.answer(
                "⚠️ У вас уже есть самостоятельный профиль ученика.\n\n"
                "Чтобы привязаться к семейному профилю, сначала "
                "выполните перерегистрацию через настройки."
            )

            await state.clear()
            return

        invite = (
            await students_service.get_valid_student_claim_invite(
                token=token,
            )
        )

        if invite is None:
            await message.answer(
                "❌ Ссылка для привязки недействительна, "
                "уже использована, отозвана или срок её действия истёк."
            )

            await state.clear()
            return

        await state.clear()

        await state.update_data(
            claim_token=token,
            claim_student_id=invite.student_id,
            claim_actor_user_id=user_id,
        )

        text = UIRenderer.render_student_claim_confirmation(
            student_name=invite.student_name or "Ученик",
            class_id=invite.student_class_id or "—",
            group_id=invite.student_group_id or "ALL",
        )

        await message.answer(
            text,
            reply_markup=Keyboards.get_student_claim_confirmation_kb(),
            parse_mode="HTML",
        )

        await state.set_state(
            RegistrationStates.waiting_for_claim_confirmation,
        )

        return

    # -------------------------------
    # Deep link invite flow
    # -------------------------------
    if payload.startswith("join_"):
        token = payload.removeprefix("join_")

        # Нельзя случайно переместить уже завершённый профиль
        # в другую семью.
        if user_dto.is_fully_registered:
            await message.answer(
                "⚠️ Вы уже зарегистрированы в bot.\n\n"
                "Для использования приглашения сначала выйдите "
                "из текущего профиля через настройки."
            )
            await state.clear()
            return

        invite = await profile_service.get_valid_family_invite(
            token=token,
        )

        if invite is None:
            await message.answer(
                "❌ Приглашение недействительно, уже использовано "
                "или срок его действия истёк."
            )
            await state.clear()
            return

        role_text = {
            "child": "ребёнка",
            "parent": "родителя",
            "observer": "наблюдателя",
        }.get(
            invite.intended_role,
            "участника семьи",
        )

        await state.update_data(
            family_invite_token=token,
            invited_family_id=invite.family_id,
            invited_role=invite.intended_role,
        )

        await message.answer(
            "👋 Вас пригласили присоединиться к семье "
            f"в роли <b>{role_text}</b>.\n\n"
            "Как к вам обращаться?",
            parse_mode="HTML",
        )

        await state.set_state(
            RegistrationStates.waiting_for_name,
        )
        return

    # -------------------------------
    # Обычный /start
    # -------------------------------
    if user_dto.is_fully_registered:
        text = UIRenderer.render_already_registered(
            user_dto.name,
        )

        kb = Keyboards.get_main_menu()

        await message.answer(
            text,
            reply_markup=kb,
        )

        await state.clear()
        return

    text = UIRenderer.render_role_selection()
    kb = Keyboards.get_role_selection()

    await message.answer(
        text,
        reply_markup=kb,
    )

    await state.set_state(
        RegistrationStates.waiting_for_role,
    )

@router.callback_query(
    RegistrationStates.waiting_for_claim_confirmation,
    F.data == "claim:confirm",
)
async def confirm_student_claim(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Ребёнок явно подтверждает, что virtual student profile его.
    """
    data = await state.get_data()

    if data.get("claim_actor_user_id") != callback.from_user.id:
        await state.clear()

        await callback.answer(
            "❌ Состояние привязки устарело. "
            "Откройте ссылку заново.",
            show_alert=True,
        )
        return

    await callback.message.edit_text(
        UIRenderer.render_student_claim_name_prompt(),
        reply_markup=Keyboards.get_claim_cancel_keyboard(),
        parse_mode="HTML",
    )

    await state.set_state(
        RegistrationStates.waiting_for_claim_name,
    )

    await callback.answer()

@router.callback_query(
    F.data == "claim:cancel"
)
async def cancel_student_claim(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Cancel не отзывает token: ссылка действует до expires_at,
    пока не будет использована либо заменена admin-ом.
    """
    await state.clear()

    await callback.message.edit_text(
        UIRenderer.render_student_claim_cancelled(),
        parse_mode="HTML",
    )

    await callback.answer()

@router.message(
    RegistrationStates.waiting_for_claim_name
)
async def process_student_claim_name(
    message: Message,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    """
    Собирает новое имя перед привязкой Telegram profile.
    """
    data = await state.get_data()

    if data.get("claim_actor_user_id") != message.from_user.id:
        await state.clear()

        await message.answer(
            "❌ Состояние привязки устарело. "
            "Откройте ссылку заново."
        )
        return

    name = message.text.strip()

    if not name:
        await message.answer(
            "❌ Введите имя ученика.",
            reply_markup=Keyboards.get_claim_cancel_keyboard(),
        )
        return

    if len(name) > 64:
        await message.answer(
            "❌ Имя слишком длинное. Используйте до 64 символов.",
            reply_markup=Keyboards.get_claim_cancel_keyboard(),
        )
        return

    class_dto = await schedule_service.get_classes_list()

    await state.update_data(
        claim_name=name,
    )

    await message.answer(
        UIRenderer.render_class_selection(class_dto),
        reply_markup=Keyboards.get_claim_class_selection_kb(
            class_dto,
        ),
        parse_mode="HTML",
    )

    await state.set_state(
        RegistrationStates.waiting_for_claim_class,
    )

@router.callback_query(
    RegistrationStates.waiting_for_claim_class,
    F.data.startswith("claim:class:"),
)
async def process_student_claim_class(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    try:
        class_id = callback.data.split(":")[2]
    except IndexError:
        await callback.answer(
            "Некорректный класс.",
            show_alert=True,
        )
        return

    data = await state.get_data()

    if data.get("claim_actor_user_id") != callback.from_user.id:
        await state.clear()

        await callback.answer(
            "❌ Состояние привязки устарело.",
            show_alert=True,
        )
        return

    groups_dto = await schedule_service.get_groups_list()

    await state.update_data(
        claim_class_id=class_id,
    )

    text, _ = UIRenderer.render_main_group_selection()

    await callback.message.edit_text(
        text,
        reply_markup=Keyboards.get_claim_group_selection_kb(
            groups_dto,
        ),
        parse_mode="HTML",
    )

    await state.set_state(
        RegistrationStates.waiting_for_claim_group,
    )

    await callback.answer()

@router.callback_query(
    RegistrationStates.waiting_for_claim_group,
    F.data == "claim:back_to_class",
)
async def back_to_student_claim_class(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    data = await state.get_data()

    if data.get("claim_actor_user_id") != callback.from_user.id:
        await state.clear()

        await callback.answer(
            "❌ Состояние привязки устарело.",
            show_alert=True,
        )
        return

    class_dto = await schedule_service.get_classes_list()

    await callback.message.edit_text(
        UIRenderer.render_class_selection(class_dto),
        reply_markup=Keyboards.get_claim_class_selection_kb(
            class_dto,
        ),
        parse_mode="HTML",
    )

    await state.set_state(
        RegistrationStates.waiting_for_claim_class,
    )

    await callback.answer()

@router.callback_query(
    RegistrationStates.waiting_for_claim_group,
    F.data.startswith("claim:group:"),
)
async def process_student_claim_group(
    callback: CallbackQuery,
    state: FSMContext,
    students_service: StudentsService,
    profile_service: ProfileService,
) -> None:
    try:
        group_id = callback.data.split(":")[2]
    except IndexError:
        await callback.answer(
            "Некорректная группа.",
            show_alert=True,
        )
        return

    data = await state.get_data()

    actor_user_id = callback.from_user.id

    claim_actor_user_id = data.get("claim_actor_user_id")
    token = data.get("claim_token")
    name = data.get("claim_name")
    class_id = data.get("claim_class_id")

    if (
        claim_actor_user_id != actor_user_id
        or not token
        or not name
        or not class_id
    ):
        await state.clear()

        await callback.answer(
            "❌ Состояние привязки устарело. "
            "Откройте ссылку заново.",
            show_alert=True,
        )
        return

    response = await students_service.consume_student_claim_invite(
        token=token,
        telegram_user_id=actor_user_id,
        name=name,
        class_id=class_id,
        group_id=group_id,
    )

    await state.clear()

    if not response.success:
        await callback.answer(
            "❌ Не удалось привязать профиль. "
            "Возможно, ссылка уже использована, истекла "
            "или ученик уже привязан к Telegram.",
            show_alert=True,
        )
        return

    user_dto = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    text = UIRenderer.render_final_success(
        user_dto.name,
    )

    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    await callback.message.answer(
        "✅ <b>Telegram успешно привязан!</b>\n\n"
        f"{text}",
        parse_mode="HTML",
    )

    await callback.message.answer(
        UIRenderer.render_main_menu(),
        reply_markup=Keyboards.get_main_menu(),
    )

    await callback.answer()
                        
@router.callback_query(RegistrationStates.waiting_for_role, F.data.startswith("role:"))
async def process_role(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService):
    role = callback.data.split(":")[1]
    await state.update_data(role=role)
    await profile_service.update_user_role(callback.from_user.id, role)
    
    text = UIRenderer.render_name_prompt()
    await callback.message.edit_text(text)
    await state.set_state(RegistrationStates.waiting_for_name)

@router.message(RegistrationStates.waiting_for_name)
async def process_name(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Обрабатывает имя в обычной регистрации и через family invite.
    """
    name = message.text.strip()

    if not name:
        await message.answer(
            "❌ Введите имя, состоящее хотя бы из одного символа."
        )
        return

    if len(name) > 64:
        await message.answer(
            "❌ Имя слишком длинное. Используйте до 64 символов."
        )
        return

    data = await state.get_data()

    invite_token = data.get("family_invite_token")
    invited_role = data.get("invited_role")

    # ---------------------------------
    # Invite child: имя сохраняем в FSM,
    # class/group будут выбраны дальше.
    # Consume произойдёт только в process_group.
    # ---------------------------------
    if invite_token and invited_role == "child":
        await state.update_data(
            pending_invite_name=name,
        )

        class_dto = await schedule_service.get_classes_list()

        text = UIRenderer.render_class_selection(
            class_dto,
        )

        kb = Keyboards.get_class_selection(
            class_dto,
        )

        await message.answer(
            text,
            reply_markup=kb,
        )

        await state.set_state(
            RegistrationStates.waiting_for_class,
        )
        return

    # ---------------------------------
    # Invite adult: class/group не нужны.
    # Можно consume сразу после имени.
    # ---------------------------------
    if invite_token and invited_role in (
        "parent",
        "observer",
    ):
        consumed_role = await profile_service.consume_family_invite(
            token=invite_token,
            user_id=message.from_user.id,
            name=name,
        )

        if consumed_role is None:
            await state.clear()

            await message.answer(
                "❌ Приглашение больше недействительно, уже использовано "
                "или срок его действия истёк."
            )
            return

        role_label = {
            "parent": "родителя",
            "observer": "наблюдателя",
        }.get(
            consumed_role,
            "участника семьи",
        )

        await state.clear()

        menu_text = UIRenderer.render_main_menu()
        menu_kb = Keyboards.get_main_menu()

        await message.answer(
            "✅ Вы успешно присоединились к семье "
            f"в роли <b>{role_label}</b>.",
            parse_mode="HTML",
        )

        await message.answer(
            menu_text,
            reply_markup=menu_kb,
        )
        return

    # ---------------------------------
    # Старый обычный registration flow.
    # ---------------------------------
    await profile_service.update_user_name(
        message.from_user.id,
        name,
    )

    role = data.get("role")

    if role == "parent":
        text = UIRenderer.render_parent_family_action()
        kb = Keyboards.get_parent_family_action()

        await message.answer(
            text,
            reply_markup=kb,
        )

        await state.set_state(
            RegistrationStates.waiting_for_family_action,
        )
        return

    if role == "child":
        text = UIRenderer.render_child_family_action()
        kb = Keyboards.get_child_family_action()

        await message.answer(
            text,
            reply_markup=kb,
        )

        await state.set_state(
            RegistrationStates.waiting_for_family_action,
        )
        return

    if role == "observer":
        text = UIRenderer.render_family_code_prompt()

        await message.answer(text)

        await state.set_state(
            RegistrationStates.waiting_for_family_code,
        )
        return

    await state.clear()

    await message.answer(
        "❌ Не удалось определить выбранную роль. "
        "Отправьте /start и повторите регистрацию."
    )

@router.callback_query(RegistrationStates.waiting_for_family_action, F.data == "family:create")
async def process_family_create(callback: CallbackQuery, state: FSMContext, profile_service: ProfileService):
    user_id = callback.from_user.id
    family_code = await profile_service.create_family_and_link(admin_user_id=user_id)
    dto = FamilyCreatedDTO(family_code=family_code)
    
    # Получаем DTO, чтобы вытащить имя
    user_dto = await profile_service.get_user_profile_dto(user_id)
    
    text = UIRenderer.render_family_created(dto, user_dto.name)
    await callback.message.edit_text(text, parse_mode="HTML")
    await state.clear()

@router.callback_query(RegistrationStates.waiting_for_family_action, F.data == "family:join")
async def process_family_join_btn(callback: CallbackQuery, state: FSMContext):
    text = UIRenderer.render_family_code_prompt()
    await callback.message.edit_text(text)
    await state.set_state(RegistrationStates.waiting_for_family_code)

@router.callback_query(RegistrationStates.waiting_for_family_action, F.data == "family:skip")
async def process_family_skip_btn(callback: CallbackQuery, state: FSMContext, schedule_service: ScheduleService):
    class_dto = await schedule_service.get_classes_list()
    
    text = UIRenderer.render_class_selection(class_dto)
    kb = Keyboards.get_class_selection(class_dto)
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(RegistrationStates.waiting_for_class)
# LEGACY_FALLBACK, оставить
@router.message(RegistrationStates.waiting_for_family_code)
async def process_family_code_input(message: Message, state: FSMContext, profile_service: ProfileService, schedule_service: ScheduleService):
    code = message.text.strip().upper()
    data = await state.get_data()
    role = data.get('role', 'parent')
    user_id = message.from_user.id
    
    success = await profile_service.link_child_to_parent(user_id=user_id, family_code=code, role=role)
    
    if not success:
        text = UIRenderer.render_error_join()
        return await message.answer(text)

    # Получаем DTO для имени
    user_dto = await profile_service.get_user_profile_dto(user_id)

    if role == 'child':
        text_success = UIRenderer.render_success_join(user_dto.name)
        await message.answer(text_success, parse_mode="HTML")
        
        class_dto = await schedule_service.get_classes_list()
        
        text = UIRenderer.render_class_selection(class_dto)
        kb = Keyboards.get_class_selection(class_dto)
        await message.answer(text, reply_markup=kb)
        await state.set_state(RegistrationStates.waiting_for_class)
    else:
        text = UIRenderer.render_success_join(user_dto.name)
        menu_text = UIRenderer.render_main_menu()
        menu_kb = Keyboards.get_main_menu()
        
        await message.answer(text, parse_mode="HTML")
        await message.answer(menu_text, reply_markup=menu_kb)
        await state.clear()

@router.callback_query(RegistrationStates.waiting_for_class, F.data.startswith("class:"))
async def process_class(callback: CallbackQuery, state: FSMContext, schedule_service: ScheduleService):
    class_id = callback.data.split(":")[1]
    await state.update_data(class_id=class_id)
    
    group_dto = await schedule_service.get_groups_list()
    text, _ = UIRenderer.render_main_group_selection()
    kb = Keyboards.get_main_group_selection(group_dto)
    
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        
    await state.set_state(RegistrationStates.waiting_for_group)
    await callback.answer()

@router.callback_query(RegistrationStates.waiting_for_group, F.data.startswith("group:"))
async def process_group(
    callback: CallbackQuery, 
    state: FSMContext, 
    profile_service: ProfileService, 
    schedule_service: ScheduleService,
    students_service: StudentsService
):
    main_group_id = callback.data.split(":")[1]
    data = await state.get_data()
    invite_token = data.get("family_invite_token")
    invited_role = data.get("invited_role")

    if invite_token and invited_role == "child":
        pending_name = data.get("pending_invite_name")
        class_id = data.get("class_id")

        if not pending_name or not class_id:
            await state.clear()

            await callback.answer(
                "❌ Данные приглашения устарели. "
                "Откройте приглашение заново.",
                show_alert=True,
            )
            return

        consumed_role = await profile_service.consume_family_invite(
            token=invite_token,
            user_id=callback.from_user.id,
            name=pending_name,
            class_id=class_id,
            group_id=main_group_id,
        )

        if consumed_role is None:
            await state.clear()

            await callback.answer(
                "❌ Приглашение уже использовано, отозвано "
                "или срок его действия истёк.",
                show_alert=True,
            )
            return

        await state.clear()

#  Проверка успешности создания профиля при инвайте
        student = await students_service.ensure_telegram_student_profile(
            telegram_user_id=callback.from_user.id,
        )
        if student is None:
            await callback.answer(
                "❌ Регистрация завершена не полностью. "
                "Не удалось создать профиль ученика.",
                show_alert=True,
            )
            return

        user_dto = await profile_service.get_user_profile_dto(
            callback.from_user.id,
        )

        text = UIRenderer.render_final_success(
            user_dto.name,
        )

        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass

        await callback.message.answer(
            text,
            parse_mode="HTML",
        )

        menu_text = UIRenderer.render_main_menu()
        menu_kb = Keyboards.get_main_menu()

        await callback.message.answer(
            menu_text,
            reply_markup=menu_kb,
        )

        await callback.answer(
            "✅ Регистрация через приглашение завершена.",
        )
        return
    
    # 1. Сохраняем ТОЛЬКО выбранную группу
    final_group_string = main_group_id
    
    # 2. Сохраняем в профиль
    target_user_id = data.get('editing_child_id', callback.from_user.id)
    # дополнительная проверка: пользователь мог открыть старое FSM-состояние или попытаться подделать переход.
    editing_child_id = data.get("editing_child_id")

    if editing_child_id is not None:
        is_admin = await profile_service.is_family_admin_for_child(
            admin_user_id=callback.from_user.id,
            child_user_id=editing_child_id,
        )

        if not is_admin:
            await state.clear()

            await callback.answer(
                "Только администратор семьи может менять класс ребёнка.",
                show_alert=True,
            )
            return

    # Блок двойной защиты от подделки FSM-состояния
    editing_own_profile_id = data.get("editing_own_profile_id")
    if editing_own_profile_id is not None:
        target_dto = await profile_service.get_user_profile_dto(
            editing_own_profile_id,
        )
        if target_dto.role == "child":
            allowed = await profile_service.can_user_change_own_notification_settings(
                user_id=editing_own_profile_id,
            )
            if not allowed:
                await state.clear()
                await callback.answer(
                    "🔒 Изменение профиля заблокировано "
                    "администратором семьи.",
                    show_alert=True,
                )
                return

    await profile_service.set_child_class_and_group(target_user_id, data['class_id'], final_group_string)
    
#  Проверка синхронизации профиля при обычной регистрации/настройке
    student = await students_service.ensure_telegram_student_profile(
        telegram_user_id=target_user_id,
    )
    if student is None:
        await state.clear()
        await callback.answer(
            "❌ Не удалось синхронизировать профиль ученика.",
            show_alert=True,
        )
        return
    # 3. ВЕТКА 1: Возврат в Настройки (если редактировали профиль ребенка через родителя)
    if 'editing_child_id' in data:
        await state.clear()
        child_dto = await profile_service.get_user_profile_dto(
            target_user_id,
        )

        is_locked = await profile_service.is_child_notification_settings_locked(
            child_user_id=target_user_id,
        )

        text = UIRenderer.render_child_settings_menu(
            child_dto.name,
            child_dto.class_id,
        )

        kb = Keyboards.get_child_settings_kb(
            child_dto=child_dto,
            is_family_admin=True,
            is_notifications_locked=is_locked,
        )
        
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.edit_text(f"✅ Подгруппа успешно обновлена.\n\n{text}", reply_markup=kb, parse_mode="HTML")
        return await callback.answer()

    # 4. ВЕТКА 2: Возврат в свои Настройки (если просто меняли свой класс)
    elif data.get('is_settings_edit'):
        await state.clear()
        
        # Локальный импорт, чтобы избежать конфликта модулей
        from bot.handlers.settings import _show_settings_menu
        
        # Отрисовываем обновленное меню настроек в текущем сообщении
        await _show_settings_menu(
            message_obj=callback.message,
            user_id=callback.from_user.id,
            profile_service=profile_service,
            schedule_service=schedule_service,
            is_callback=True
        )
        return await callback.answer("✅ Класс и подгруппа успешно обновлены!")

    # 5. ВЕТКА 3: Стандартное завершение первой регистрации
    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    await state.clear()

    text = UIRenderer.render_final_success(
        getattr(user_dto, "name", "Пользователь"),
    )

    await callback.message.delete()

    await callback.message.answer(
        text,
        parse_mode="HTML",
    )

    menu_text = UIRenderer.render_main_menu()
    menu_kb = Keyboards.get_main_menu()

    await callback.message.answer(
        menu_text,
        reply_markup=menu_kb,
    )

    await callback.answer()