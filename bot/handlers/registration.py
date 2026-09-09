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
from services.help_service import HelpService
from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from core.models.dto import ClassListDTO, GroupListDTO, FamilyCreatedDTO

logger = logging.getLogger(__name__)
router = Router()

async def _show_main_menu(
    message: Message,
    *,
    text: str | None = None,
) -> None:
    """
    Показывает постоянное нижнее меню.

    Сообщение намеренно нейтральное:
    успешное действие уже описано в основном renderer,
    а здесь пользователь получает только ориентир по навигации.
    """
    await message.answer(
        text or (
            "⬇️ <b>Главное меню</b>\n"
        ),
        reply_markup=Keyboards.get_main_menu(),
        parse_mode="HTML",
    )
    
class RegistrationStates(StatesGroup):
    waiting_for_role = State()
    waiting_for_name = State()
    waiting_for_family_action = State()
    waiting_for_family_code = State()
    waiting_for_class = State()
    waiting_for_group = State()
    
    waiting_for_teacher = State()
        
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
    schedule_service: ScheduleService,
    help_service: HelpService,
) -> None:
    """
    Старт bot и обработка deep-link family invite.

    Обычный /start работает как раньше.
    /start join_<token> запускает роль, зафиксированную в invite.
    """
    user_id = message.from_user.id

    # 1. Нормализация payload (защита от точек и пробелов в конце)
    payload = (
        (command.args or "")
        .strip()
        .rstrip(".,;:!?")
    )

    # 2. Получаем текущее состояние ДО любых изменений
    current_state = await state.get_state()
    current_data = await state.get_data()

    payload_kind = (
        "join" if payload.startswith("join_")
        else "claim" if payload.startswith("claim_")
        else "plain" if not payload
        else "unknown"
    )

    # 3. Логируем старт для диагностики
    logger.info(
        "Start received: user_id=%s payload_kind=%s "
        "payload_len=%s state=%r",
        user_id,
        payload_kind,
        len(payload),
        current_state,
    )

    if payload == "help":
        from bot.handlers.help import show_help

        await show_help(
            message=message,
            actor_user_id=message.from_user.id,
            section="main",
            profile_service=profile_service,
            help_service=help_service,
            edit_message=False,
        )
        return
    
    await profile_service.register_user_initial(
        user_id,
    )

    # ---------------------------------------------------------
    # 4. Защита от сброса FSM
    # Plain /start не должен уничтожать незавершённый invite / claim flow.
    # ---------------------------------------------------------
    if not payload:
        pending_family_invite = current_data.get(
            "family_invite_token",
        )

        pending_claim = current_data.get(
            "claim_token",
        )

        pending_actor_id = (
            current_data.get("claim_actor_user_id")
            or current_data.get("family_invite_actor_user_id")
        )

        belongs_to_current_user = (
            pending_actor_id is None
            or pending_actor_id == user_id
        )

        family_invite_states = {
            RegistrationStates.waiting_for_name.state,
            RegistrationStates.waiting_for_class.state,
            RegistrationStates.waiting_for_group.state,
        }

        claim_states = {
            RegistrationStates.waiting_for_claim_confirmation.state,
            RegistrationStates.waiting_for_claim_name.state,
        }

        # Telegram-клиент может прислать plain /start повторно
        # после deep link /start join_<token> или /start claim_<token>.
        #
        # Не показываем лишнее служебное сообщение и, главное,
        # не очищаем FSM: пользователь продолжает начатый flow.
        if (
            pending_family_invite
            and belongs_to_current_user
            and current_state in family_invite_states
        ):
            logger.info(
                "Duplicate plain /start ignored during family invite: "
                "user_id=%s state=%s",
                user_id,
                current_state,
            )
            return

        if (
            pending_claim
            and belongs_to_current_user
            and current_state in claim_states
        ):
            logger.info(
                "Duplicate plain /start ignored during claim flow: "
                "user_id=%s state=%s",
                user_id,
                current_state,
            )
            return
        
    user_dto = await profile_service.get_user_profile_dto(
        user_id,
    )

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

        invite = (
            await students_service.get_valid_student_claim_invite(
                token=token,
            )
        )
        current_student = (
            await students_service.get_student_by_telegram_user_id(
                telegram_user_id=user_id,
            )
        )
        if invite is None:
            await message.answer(
                "❌ Ссылка для привязки недействительна, "
                "уже использована, отозвана или срок её действия истёк."
            )

            await state.clear()
            return

        # --- 1. Запрашиваем справочники школы единым запросом через ScheduleServiceV2 ---
        dicts_dto = await schedule_service.get_school_dictionaries()
        
        # --- 2. Получаем красивые имена по ID из свойств dicts_dto ---
        class_name = dicts_dto.classes.get(
            invite.student_class_id,
            invite.student_class_id or "—",
        )

        if not invite.student_group_id or invite.student_group_id == "ALL":
            group_name = "ALL"
        else:
            group_name = dicts_dto.groups.get(
                invite.student_group_id, 
                invite.student_group_id
            )
            
        await state.clear()
  
        await state.update_data(
            claim_token=token,
            claim_student_id=invite.student_id,
            claim_actor_user_id=user_id,

            # Нужен только для UX/preview.
            # Repository всё равно повторно проверит данные
            # непосредственно внутри transaction.
            claim_source_student_id=(
                current_student.id
                if current_student is not None
                else None
            ),
        )

        text = UIRenderer.render_student_claim_confirmation(
            student_name=invite.student_name or "Ученик",
            class_name=class_name,
            group_name=group_name,
            has_standalone_profile=current_student is not None,
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
        
        current_student = (
            await students_service.get_student_by_telegram_user_id(
                telegram_user_id=user_id,
            )
        )

        is_standalone_child = (
            user_dto.role == "child"
            and user_dto.family_id is None
            and current_student is not None
            and current_student.family_id is None
            and current_student.is_active
        )
        # Нельзя случайно переместить уже завершённый профиль
        # в другую семью.
        if user_dto.is_fully_registered and not is_standalone_child:
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
            family_invite_actor_user_id=user_id,
        )

        intro_text = UIRenderer.render_family_invite_join_intro(
            intended_role=invite.intended_role,
            has_standalone_child_profile=(
                invite.intended_role == "child"
                and is_standalone_child
            ),
            #via_code=False,
        )

        await message.answer(
            intro_text,
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

        await _show_main_menu(message, text=text,)

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
    RegistrationStates.waiting_for_claim_name,
)
async def process_student_claim_name(
    message: Message,
    state: FSMContext,
    students_service: StudentsService,
    profile_service: ProfileService,
) -> None:
    """
    Получает имя ребёнка и атомарно объединяет standalone profile
    с family virtual student profile из claim invite.
    """
    data = await state.get_data()

    actor_user_id = message.from_user.id
    token = data.get("claim_token")

    if (
        data.get("claim_actor_user_id") != actor_user_id
        or not token
    ):
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
            "❌ Имя слишком длинное. "
            "Используйте до 64 символов.",
            reply_markup=Keyboards.get_claim_cancel_keyboard(),
        )
        return

    response = await students_service.consume_student_claim_invite(
        token=token,
        telegram_user_id=actor_user_id,
        name=name,
    )

    await state.clear()

    if not response.success:
        await message.answer(
            "❌ Не удалось привязать профиль.\n\n"
            "Возможно, ссылка уже использована, истекла, "
            "отозвана или Telegram уже связан с профилем "
            "ребёнка в другой семье."
        )
        return

    user_dto = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    try:
        await message.answer(
            "✅ <b>Telegram успешно привязан!</b>\n\n"
            f"{UIRenderer.render_final_success(user_dto.name)}",
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        logger.debug(
            "Unable to send claim-success message "
            "for user_id=%s",
            actor_user_id,
        )

    await _show_main_menu(message)
                           
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
    actor_user_id = message.from_user.id
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
        invite_actor_user_id = data.get(
            "family_invite_actor_user_id",
        )

        if invite_actor_user_id != actor_user_id:
            await state.clear()

            await message.answer(
                "❌ Состояние приглашения устарело. "
                "Откройте ссылку заново.",
                show_alert=True,
            )
            return

        await state.update_data(
            pending_invite_name=name,
        )
        dicts_dto = await schedule_service.get_school_dictionaries()

        text = UIRenderer.render_class_selection(
            dicts_dto.as_class_list,
        )

        kb = Keyboards.get_class_selection(
            dicts_dto.as_class_list,
        )

        await message.answer(
            text,
            reply_markup=kb,
            parse_mode="HTML",
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

        user_dto = await profile_service.get_user_profile_dto(
            message.from_user.id,
        )
        
        await state.clear()

        await message.answer(
            UIRenderer.render_success_join(
                name=user_dto.name,
                role=consumed_role,
            ),
            parse_mode="HTML",
        )

        await _show_main_menu(message)
        return

    # ---------------------------------
    # Старый обычный registration flow.
    # ---------------------------------
    await profile_service.update_user_name(
        message.from_user.id,
        name,
    )

    role = data.get("role")

    if role == "teacher":
        teachers_dto = await schedule_service.get_teachers_list()

        if not teachers_dto.teachers:
            await state.clear()

            await message.answer(
                "❌ Справочник учителей пока недоступен. "
                "Попробуйте позже, когда расписание будет загружено."
            )
            return

        await message.answer(
            UIRenderer.render_teacher_selection(),
            reply_markup=Keyboards.get_teacher_registration_kb(
                teachers_dto,
            ),
            parse_mode="HTML",
        )

        await state.set_state(
            RegistrationStates.waiting_for_teacher,
        )

        return

    if role == "parent":
        text = UIRenderer.render_parent_family_action()
        kb = Keyboards.get_parent_family_action()

        await message.answer(
            text,
            reply_markup=kb,
            parse_mode="HTML",
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
            parse_mode="HTML",
        )

        await state.set_state(
            RegistrationStates.waiting_for_family_action,
        )
        return

    if role == "observer":
            text = UIRenderer.render_family_code_join_intro(
                intended_role="observer",
            )

            await message.answer(
                text,
                parse_mode="HTML",
            )
            await state.set_state(
                RegistrationStates.waiting_for_family_code,
            )
            return

    await state.clear()

    await message.answer(
        "❌ Не удалось определить выбранную роль. "
        "Отправьте /start и повторите регистрацию."
    )
    
@router.callback_query(
    RegistrationStates.waiting_for_family_action,
    F.data == "family:create",
)
async def process_family_create(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    user_id = callback.from_user.id

    family_code = await profile_service.create_family_and_link(
        admin_user_id=user_id,
    )

    dto = FamilyCreatedDTO(
        family_code=family_code,
    )

    user_dto = await profile_service.get_user_profile_dto(
        user_id,
    )

    text = UIRenderer.render_family_created(
        dto,
        user_dto.name,
    )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
    )

    # edit_text не показывает нижнее ReplyKeyboardMarkup.
    # Поэтому отправляем меню отдельным сообщением.
    await _show_main_menu(callback.message,)

    await state.clear()
    await callback.answer()

@router.callback_query(
    RegistrationStates.waiting_for_family_action,
    F.data == "family:join",
)
async def process_family_join_btn(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()

    text = UIRenderer.render_family_join_intro(
        intended_role=data.get("role", "parent"),
        has_standalone_child_profile=False,
        via_code=True,
    )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
    )

    await callback.message.edit_text(
        UIRenderer.render_family_code_join_intro(
            intended_role=data.get("role", "parent"),
        ),
        parse_mode="HTML",
    )

    await state.set_state(
        RegistrationStates.waiting_for_family_code,
    )

    await callback.answer()

@router.callback_query(
    RegistrationStates.waiting_for_family_action,
    F.data == "family:skip",
)
async def process_family_skip_btn(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    # 1. Запрашиваем справочники школы единым запросом
    dicts_dto = await schedule_service.get_school_dictionaries()
    
    # 2. Передаем ClassListDTO через вспомогательное свойство as_class_list
    text = UIRenderer.render_class_selection(dicts_dto.as_class_list)
    kb = Keyboards.get_class_selection(dicts_dto.as_class_list)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(RegistrationStates.waiting_for_class)
    await callback.answer()
    
# LEGACY_FALLBACK, оставить
@router.message(RegistrationStates.waiting_for_family_code)
async def process_family_code_input(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    code = message.text.strip().upper()
    data = await state.get_data()
    role = data.get("role", "parent")
    user_id = message.from_user.id
    
    success = await profile_service.link_child_to_parent(
        user_id=user_id,
        family_code=code,
        role=role,
    )
    
    if not success:
        await message.answer(
            UIRenderer.render_error_join(),
            parse_mode="HTML",
        )
        return

    # Получаем DTO для имени
    user_dto = await profile_service.get_user_profile_dto(user_id)
    user_name = getattr(user_dto, "name", "Пользователь")

    if role == "child":
        text_success = UIRenderer.render_success_join(name=user_dto.name,role=role,)
        await message.answer(text_success, parse_mode="HTML")
        
        # 1. Запрашиваем справочники школы единым запросом через ScheduleService
        dicts_dto = await schedule_service.get_school_dictionaries()
        
        # 2. Рендерим выбор класса с использованием as_class_list
        text = UIRenderer.render_class_selection(dicts_dto.as_class_list)
        kb = Keyboards.get_class_selection(dicts_dto.as_class_list)
        
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        await state.set_state(RegistrationStates.waiting_for_class)
    else:
        text = UIRenderer.render_success_join(name=user_dto.name,role=role,)
        await message.answer(text, parse_mode="HTML")
        await _show_main_menu(message)
        await state.clear()

@router.callback_query(
    RegistrationStates.waiting_for_class,
    F.data.startswith("class:")
)
async def process_class(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    class_id = callback.data.split(":")[1]
    await state.update_data(class_id=class_id)
    
    # Запрашиваем справочники школы единым запросом
    dicts_dto = await schedule_service.get_school_dictionaries()
    
    text, _ = UIRenderer.render_main_group_selection()
    kb = Keyboards.get_main_group_selection(dicts_dto.as_group_list)
    
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        
    await state.set_state(RegistrationStates.waiting_for_group)
    await callback.answer()
    
@router.callback_query(
    RegistrationStates.waiting_for_group,
    F.data.startswith("group:"),
)
async def process_group(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
) -> None:
    try:
        group_id = callback.data.split(":", 1)[1]
    except IndexError:
        await callback.answer(
            "❌ Некорректная группа.",
            show_alert=True,
        )
        return

    actor_user_id = callback.from_user.id
    data = await state.get_data()

    # =========================================================
    # 1. Child joins family through join_<token>.
    # =========================================================
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
            user_id=actor_user_id,
            name=pending_name,
            class_id=class_id,
            group_id=group_id,
        )

        if consumed_role is None:
            await state.clear()

            await callback.answer(
                "❌ Приглашение уже использовано, отозвано "
                "или срок его действия истёк.",
                show_alert=True,
            )
            return

        # Для нового child создаёт profile.
        # Для standalone child, вступившего в семью,
        # повторно синхронизирует тот же student_profile.id.
        student = await students_service.ensure_telegram_student_profile(
            telegram_user_id=actor_user_id,
        )

        if student is None:
            await state.clear()

            await callback.answer(
                "❌ Семья подключена, но не удалось "
                "синхронизировать профиль ученика.",
                show_alert=True,
            )
            return

        user_dto = await profile_service.get_user_profile_dto(
            actor_user_id,
        )

        await state.clear()

        with contextlib.suppress(TelegramBadRequest):
            await callback.message.delete()

        await callback.message.answer(
            UIRenderer.render_final_success(
                user_dto.name,
            ),
            parse_mode="HTML",
        )

        await _show_main_menu(
            callback.message,
        )

        await callback.answer(
            "✅ Регистрация через приглашение завершена.",
        )
        return
    

    # =========================================================
    # 4. Standard standalone child registration.
    # =========================================================
    actor_dto = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    if actor_dto.role != "child":
        await state.clear()

        await callback.answer(
            "❌ Регистрация ученика недоступна для текущей роли.",
            show_alert=True,
        )
        return
        
    class_id = data.get("class_id")

    if not class_id:
        await state.clear()

        await callback.answer(
            "❌ Не выбран класс. Начните регистрацию заново.",
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

        await callback.answer(
            "❌ Не удалось создать профиль ученика.",
            show_alert=True,
        )
        return

    user_dto = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    await state.clear()

    with contextlib.suppress(TelegramBadRequest):
        await callback.message.delete()

    await callback.message.answer(
        UIRenderer.render_final_success(
            user_dto.name,
        ),
        parse_mode="HTML",
    )

    await _show_main_menu(
        callback.message,
    )

    await callback.answer()

@router.callback_query(
    RegistrationStates.waiting_for_teacher,
    F.data.startswith("reg_teacher:"),
)
async def process_teacher_selection(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Завершает teacher registration после выбора NIKA teacher ID.
    """
    try:
        teacher_id = callback.data.split(":")[1]
    except IndexError:
        await callback.answer(
            "❌ Некорректный идентификатор учителя.",
            show_alert=True,
        )
        return

    if teacher_id == "cancel":
        await state.clear()

        await callback.message.edit_text(
            "❌ Регистрация учителя отменена.\n\n"
            "Отправьте /start, чтобы начать заново."
        )

        await callback.answer()
        return

    data = await state.get_data()

    if data.get("role") != "teacher":
        await state.clear()

        await callback.answer(
            "❌ Состояние регистрации устарело. "
            "Отправьте /start и начните заново.",
            show_alert=True,
        )
        return

    teachers_dto = await schedule_service.get_teachers_list()

    teacher_name = teachers_dto.teachers.get(
        teacher_id,
    )

    if teacher_name is None:
        await callback.answer(
            "❌ Учитель не найден в текущем справочнике школы.",
            show_alert=True,
        )
        return

    updated = await profile_service.set_teacher_profile(
        user_id=callback.from_user.id,
        teacher_id=teacher_id,
    )

    if not updated:
        await state.clear()

        await callback.answer(
            "❌ Не удалось сохранить профиль учителя.",
            show_alert=True,
        )
        return

    await state.clear()

    user_dto = await profile_service.get_user_profile_dto(
        callback.from_user.id,
    )

    teacher_name_text = getattr(
        teacher_name,
        "name",
        teacher_name,
    )

    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    await callback.message.answer(
        UIRenderer.render_teacher_registration_success(
            name=user_dto.name,
            teacher_name=str(teacher_name_text),
        ),
        parse_mode="HTML",
    )

    await _show_main_menu(callback.message)

    await callback.answer(
        "✅ Учительский профиль создан.",
    )