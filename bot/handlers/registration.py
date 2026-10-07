# bot/handlers/registration.py
#
# ЭТАП 4 (систематизация хендлеров): изменения относительно прежней версии.
#
# 1. Парсинг callback_data через центральный модуль bot/callbacks.py:
#    role: / class: / group: / reg_teacher: / claim:* / family:*.
#    Формат строк на проводе не изменён.
# 2. Исправлен баг process_family_join_btn: выполнялось ДВА edit_text
#    подряд — первый (render_family_join_intro) мгновенно затирался
#    вторым. Оставлен только итоговый экран.
# 3. Исправлен UI-баг claim-флоу: group_name="ALL" уходил пользователю
#    литералом; теперь SchoolDictionariesDTO.get_readable_group()
#    отдаёт "Весь класс" / расшифрованные группы.
# 4. Мелочь: parse-методы строже старых split() — некорректная строка
#    отклоняется alert'ом, а не уходит в сервисы пустым значением.

import logging
import contextlib

from aiogram import Router, F
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any
from config import Config

from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest

from services.profiles_service import ProfileService
from services.students_service import StudentsService
from services.schedule_service import ScheduleService
from services.help_service import HelpService
from core.models.dto import UserProfileDTO

from bot.utils.ui_renderer import UIRenderer
from bot.keyboards.keyboard import Keyboards
from bot import callbacks
from bot.callbacks import (
    RegistrationClassCD,
    RegistrationGroupCD,
    RoleCD,
    TeacherRegistrationCD,
)
from  bot.utils.codes import normalize_short_code
from bot.utils.fsm_guard import validate_fsm_session
logger = logging.getLogger(__name__)
router = Router()
FSM_FAMILY_INVITE_TOKEN = "family_invite_token"
FSM_INVITED_ROLE = "invited_role"
FSM_FAMILY_INVITE_ACTOR_USER_ID = (
    "family_invite_actor_user_id"
)
FSM_PENDING_INVITE_NAME = "pending_invite_name"
FSM_CLAIM_TOKEN = "claim_token"
FSM_CLAIM_ACTOR_USER_ID = "claim_actor_user_id"

_ALLOWED_INVITE_ROLES = frozenset(
    {
        "child",
        "parent",
        "observer",
    }
)

_ALLOWED_REGISTRATION_ROLES = frozenset(
    {
        "child",
        "parent",
        "observer",
        "teacher",
    }
)


def _read_registration_role(
    data: Mapping[str, Any],
) -> str | None:
    """
    Возвращает валидную роль registration FSM или None.

    None означает отсутствие/повреждение state, а не default role.
    Handler обязан остановить flow, а не угадывать роль пользователя.
    """
    role = data.get("role")

    if role not in _ALLOWED_REGISTRATION_ROLES:
        return None

    return role


@dataclass(frozen=True, slots=True)
class _FamilyInviteFSMContext:
    """
    Typed read-model family invite state.

    FSM storage остаётся dict, но handler получает только
    валидированный typed context. Неполный/повреждённый invite state
    приводит к ValueError, а не к частичному выполнению flow.
    """

    token: str
    role: str
    actor_user_id: int
    pending_name: str | None = None

    @classmethod
    def from_fsm_data(
        cls,
        data: Mapping[str, Any],
    ) -> "_FamilyInviteFSMContext | None":
        """
        None:
            в FSM нет family invite flow.

        ValueError:
            invite context начат, но повреждён/неполон.
        """
        token = data.get(FSM_FAMILY_INVITE_TOKEN)

        if token is None:
            return None

        role = data.get(FSM_INVITED_ROLE)
        actor_user_id = data.get(
            FSM_FAMILY_INVITE_ACTOR_USER_ID,
        )
        pending_name = data.get(FSM_PENDING_INVITE_NAME)

        if not isinstance(token, str) or not token.strip():
            raise ValueError("Invalid family invite token in FSM")

        if role not in _ALLOWED_INVITE_ROLES:
            raise ValueError("Invalid family invite role in FSM")

        if (
            not isinstance(actor_user_id, int)
            or isinstance(actor_user_id, bool)
            or actor_user_id <= 0
        ):
            raise ValueError("Invalid family invite actor in FSM")

        if pending_name is not None and not isinstance(
            pending_name,
            str,
        ):
            raise ValueError("Invalid family invite name in FSM")

        return cls(
            token=token,
            role=role,
            actor_user_id=actor_user_id,
            pending_name=pending_name,
        )
        


async def _show_main_menu(
    message: Message,
    *,
    text: str | None = None,
    config: Config | None = None,
) -> None:
    """
    Показывает постоянное нижнее меню.

    Сообщение намеренно нейтральное:
    успешное действие уже описано в основном renderer,
    а здесь пользователь получает только ориентир по навигации.
    """
    web_app_url = None
    
    # Формируем ссылку, только если передан конфиг и PWA включено
    if config and getattr(config, "WEB_TG_APP_ENABLED", True):
        web_app_url = f"{config.WEB_PUBLIC_URL.rstrip('/')}/tg/app"

    await message.answer(
        text or (
            "⬇️ <b>Главное меню</b>\n"
        ),
        # Передаем url в клавиатуру (если config не передан, уйдет None и отрисуется просто текст)
        reply_markup=Keyboards.get_main_menu(web_app_url=web_app_url),
        parse_mode="HTML",
    )

async def _show_class_selection(
    message: Message,
    *,
    state: FSMContext,
    schedule_service: ScheduleService,
    edit_message: bool,
) -> None:
    """
    Показывает выбор класса и переводит registration FSM
    в waiting_for_class.

    edit_message=False:
        отправляет новое сообщение — используется после text input.

    edit_message=True:
        заменяет callback message — используется после callback action.
    """
    dictionaries = await schedule_service.get_school_dictionaries()

    text = UIRenderer.render_class_selection(
        dictionaries.as_class_list,
    )
    keyboard = Keyboards.get_class_selection(
        dictionaries.as_class_list,
    )

    if edit_message:
        await message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    else:
        await message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    await state.set_state(
        RegistrationStates.waiting_for_class,
    )

async def _show_registration_success(
    message: Message,
    *,
    text: str,
    delete_origin_message: bool,
) -> None:
    """
    Завершает registration/join UI flow.

    Для callback-based class/group flow origin message удаляется, чтобы
    старые inline buttons не оставались в чате. Для message-based flow
    исходное user message не удаляется.
    """
    if delete_origin_message:
        with contextlib.suppress(TelegramBadRequest):
            await message.delete()

    await message.answer(
        text,
        parse_mode="HTML",
    )
    await _show_main_menu(message)

async def _start_student_claim_from_deep_link(
    message: Message,
    *,
    token: str,
    user_id: int,
    user_dto: UserProfileDTO,
    state: FSMContext,
    students_service: StudentsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Запускает claim flow для virtual student profile по deep link.

    Repository повторно проверяет token и target student в момент consume;
    FSM хранит только claim token и owner user ID.
    """
    if user_dto.family_id is not None:
        await message.answer(
            "⚠️ Вы уже состоите в семье.\n\n"
            "Для использования ссылки сначала выйдите "
            "из текущей семьи через настройки."
        )
        await state.clear()
        return

    invite = await students_service.get_valid_student_claim_invite(
        token=token,
    )

    if invite is None:
        await message.answer(
            "❌ Ссылка для привязки недействительна, "
            "уже использована, отозвана или срок её действия истёк."
        )
        await state.clear()
        return

    current_student = await students_service.get_student_by_telegram_user_id(
        telegram_user_id=user_id,
    )

    dictionaries = await schedule_service.get_school_dictionaries()

    class_name = dictionaries.classes.get(
        invite.student_class_id,
        invite.student_class_id or "—",
    )
    group_name = dictionaries.get_readable_group(
        invite.student_group_id,
    )

    await _store_student_claim_context(
        state,
        token=token,
        actor_user_id=user_id,
    )

    await message.answer(
        UIRenderer.render_student_claim_confirmation(
            student_name=invite.student_name or "Ученик",
            class_name=class_name,
            group_name=group_name,
            has_standalone_profile=current_student is not None,
        ),
        reply_markup=Keyboards.get_student_claim_confirmation_kb(),
        parse_mode="HTML",
    )
    await state.set_state(
        RegistrationStates.waiting_for_claim_confirmation,
    )

async def _start_family_invite_from_deep_link(
    message: Message,
    *,
    token: str,
    user_id: int,
    user_dto: UserProfileDTO,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
) -> None:
    """
    Запускает family invite flow по deep link join_<token>.

    Standalone child с local student profile может вступить в family:
    repository атомарно переносит family context существующего profile.
    Остальные fully registered users не могут быть silently moved.
    """
    current_student = await students_service.get_student_by_telegram_user_id(
        telegram_user_id=user_id,
    )

    is_standalone_child = (
        user_dto.role == "child"
        and user_dto.family_id is None
        and current_student is not None
        and current_student.family_id is None
        and current_student.is_active
    )

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

    await _store_family_invite_context(
        state,
        token=invite.token,
        role=invite.intended_role,
        actor_user_id=user_id,
        reset_existing_state=True,
    )

    await message.answer(
        UIRenderer.render_family_invite_join_intro(
            intended_role=invite.intended_role,
            has_standalone_child_profile=(
                invite.intended_role == "child"
                and is_standalone_child
            ),
        ),
        parse_mode="HTML",
    )
    await state.set_state(
        RegistrationStates.waiting_for_name,
    )

async def _complete_child_family_invite_registration(
    callback: CallbackQuery,
    *,
    state: FSMContext,
    invite_context: _FamilyInviteFSMContext,
    class_id: str | None,
    group_id: str,
    profile_service: ProfileService,
    students_service: StudentsService,
) -> None:
    """
    Завершает child registration через family invite.

    Repository повторно валидирует invite token атомарно на consume,
    поэтому FSM context используется только как UX-flow state.
    """
    actor_user_id = callback.from_user.id

    if invite_context.actor_user_id != actor_user_id:
        await state.clear()
        await callback.answer(
            "❌ Состояние приглашения устарело. "
            "Откройте приглашение заново.",
            show_alert=True,
        )
        return

    pending_name = invite_context.pending_name

    if not pending_name or not class_id:
        await state.clear()
        await callback.answer(
            "❌ Данные приглашения устарели. "
            "Откройте приглашение заново.",
            show_alert=True,
        )
        return

    consumed_role = await profile_service.consume_family_invite(
        token=invite_context.token,
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

    await _show_registration_success(
        callback.message,
        text=UIRenderer.render_final_success(
            user_dto.name,
        ),
        delete_origin_message=True,
    )

    await callback.answer(
        "✅ Регистрация через приглашение завершена.",
    )

async def _complete_standalone_child_registration(
    callback: CallbackQuery,
    *,
    state: FSMContext,
    class_id: str | None,
    group_id: str,
    profile_service: ProfileService,
    students_service: StudentsService,
) -> None:
    """
    Завершает standalone child registration после выбора class/group.
    """
    actor_user_id = callback.from_user.id

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

    await _show_registration_success(
        callback.message,
        text=UIRenderer.render_final_success(
            user_dto.name,
        ),
        delete_origin_message=True,
    )
    await callback.answer()
                
async def _store_family_invite_context(
    state: FSMContext,
    *,
    token: str,
    role: str,
    actor_user_id: int,
    pending_name: str | None = None,
    reset_existing_state: bool = False,
) -> None:
    """
    Сохраняет минимальный invite context для family registration flow.

    reset_existing_state=True используется при старте нового flow через
    deep link либо invite short code. Это не позволяет устаревшим данным
    предыдущего registration/claim flow попасть в новый invite flow.

    pending_name задаётся только после text input пользователя.
    """
    if reset_existing_state:
        await state.clear()

    payload: dict[str, str | int] = {
        FSM_FAMILY_INVITE_TOKEN: token,
        FSM_INVITED_ROLE: role,
        FSM_FAMILY_INVITE_ACTOR_USER_ID: actor_user_id,
    }

    if pending_name is not None:
        payload[FSM_PENDING_INVITE_NAME] = pending_name

    await state.update_data(**payload)

async def _store_student_claim_context(
    state: FSMContext,
    *,
    token: str,
    actor_user_id: int,
) -> None:
    """
    Сохраняет минимальный claim context.

    Student profile details не хранятся в FSM: repository повторно
    валидирует invite и actual student profile при consume operation.
    """
    await state.clear()
    await state.update_data(
        **{
            FSM_CLAIM_TOKEN: token,
            FSM_CLAIM_ACTOR_USER_ID: actor_user_id,
        }
    )
    
def _read_family_invite_context(
    data: Mapping[str, Any],
) -> _FamilyInviteFSMContext | None:
    """Единая typed boundary для family invite data из FSM."""
    return _FamilyInviteFSMContext.from_fsm_data(data)
            
@router.message(Command("menu"))
async def cmd_menu(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    """
    Вызов главного меню по команде /menu.
    Полезно, если постоянная клавиатура скрылась или «залипла».
    """
    user_id = message.from_user.id
    user_dto = await profile_service.get_user_profile_dto(user_id)

    if not user_dto.is_fully_registered:
        await message.answer(
            "⚠️ Вы ещё не завершили регистрацию.\nПожалуйста, отправьте /start для выбора роли."
        )
        return

    await state.clear()
    await _show_main_menu(
        message,
        text="⬇️ <b>Главное меню</b>",
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
        try:
            invite_context = _read_family_invite_context(
                current_data,
            )
        except ValueError:
            logger.warning(
                "Corrupted family invite FSM cleared: user_id=%s",
                user_id,
            )
            await state.clear()
            current_data = {}
            current_state = None
            invite_context = None

        pending_claim = current_data.get(FSM_CLAIM_TOKEN)
        pending_actor_id = (
            current_data.get(FSM_CLAIM_ACTOR_USER_ID)
            or (
                invite_context.actor_user_id
                if invite_context is not None
                else None
            )
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
            invite_context is not None
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
        await _start_student_claim_from_deep_link(
            message,
            token=payload.removeprefix("claim_"),
            user_id=user_id,
            user_dto=user_dto,
            state=state,
            students_service=students_service,
            schedule_service=schedule_service,
        )
        return

    # -------------------------------
    # Deep link invite flow
    # -------------------------------
    if payload.startswith("join_"):
        await _start_family_invite_from_deep_link(
            message,
            token=payload.removeprefix("join_"),
            user_id=user_id,
            user_dto=user_dto,
            state=state,
            profile_service=profile_service,
            students_service=students_service,
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
    F.data == callbacks.CLAIM_CONFIRM,
)
async def confirm_student_claim(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Ребёнок явно подтверждает, что virtual student profile его.
    """
    data = await state.get_data()
    if (
        data.get(FSM_CLAIM_ACTOR_USER_ID)
        != callback.from_user.id
    ):
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
    F.data == callbacks.CLAIM_CANCEL
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
    if not await validate_fsm_session(
        message,
        state,
        expected={
            FSM_CLAIM_ACTOR_USER_ID: message.from_user.id,
        },
        required=[FSM_CLAIM_TOKEN],
    ):
        return

    data = await state.get_data()
    token = data.get(FSM_CLAIM_TOKEN)
    # Обязательно возвращаем переменную, так как она нужна ниже
    actor_user_id = message.from_user.id

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


@router.callback_query(
    RegistrationStates.waiting_for_role,
    RoleCD.filter(),
)
async def process_role(
    callback: CallbackQuery,
    callback_data: RoleCD,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    """Сохраняет выбранную роль и переводит пользователя к вводу имени."""
    role = callback_data.role

    await state.update_data(role=role)
    await profile_service.update_user_role(
        callback.from_user.id,
        role,
    )

    await callback.message.edit_text(
        UIRenderer.render_name_prompt(),
    )
    await state.set_state(
        RegistrationStates.waiting_for_name,
    )
    await callback.answer()


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
    try:
        invite_context = _read_family_invite_context(data)
    except ValueError:
        await state.clear()
        await message.answer(
            "❌ Состояние приглашения устарело. "
            "Откройте приглашение заново.",
        )
        return
    invite_token = (
        invite_context.token
        if invite_context is not None
        else None
    )
    invited_role = (
        invite_context.role
        if invite_context is not None
        else None
    )
    # ---------------------------------
    # Invite child: имя сохраняем в FSM,
    # class/group будут выбраны дальше.
    # Consume произойдёт только в process_group.
    # ---------------------------------
    if invite_token and invited_role == "child":
        invite_actor_user_id = invite_context.actor_user_id
        if invite_actor_user_id != actor_user_id:
            await state.clear()
            await message.answer(
                "❌ Состояние приглашения устарело. "
                "Откройте ссылку заново.",
            )
            return
        await _store_family_invite_context(
            state,
            token=invite_context.token,
            role=invite_context.role,
            actor_user_id=invite_context.actor_user_id,
            pending_name=name,
        )
        await _show_class_selection(
            message,
            state=state,
            schedule_service=schedule_service,
            edit_message=False,
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
            token=invite_context.token,
            user_id=actor_user_id,
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
            actor_user_id,
        )
        await state.clear()

        await _show_registration_success(
            message,
            text=UIRenderer.render_success_join(
                name=user_dto.name,
                role=consumed_role,
            ),
            delete_origin_message=False,
        )
        return
    # ---------------------------------
    # Старый обычный registration flow.
    # ---------------------------------
    await profile_service.update_user_name(
        message.from_user.id,
        name,
    )
    role = _read_registration_role(data)
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
        await profile_service.update_user_name(
            actor_user_id,
            name,
        )

        await message.answer(
            UIRenderer.render_family_code_join_intro(
                intended_role="observer",
            ),
            parse_mode="HTML",
        )

        # Legacy FSM ID: фактически ожидается short code invitation,
        # а не общий family_code.
        await state.set_state(
            RegistrationStates.waiting_for_family_code,
        )
        return
    await state.clear()
    await message.answer(
        "❌ Не удалось определить выбранную роль. "
        "Отправьте /start и повторите регистрацию."
    )
    if role is None:
        await state.clear()
        await message.answer(
            "❌ Состояние регистрации устарело. "
            "Отправьте /start и начните заново.",
        )
        return

@router.callback_query(
    RegistrationStates.waiting_for_family_action,
    F.data == callbacks.FAMILY_CREATE,
)
async def process_family_create(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    """
    Создаёт семью только в parent registration flow.

    Callback data и keyboard visibility не являются security boundary:
    роль сверяется с текущим FSM state перед service call.
    """
    data = await state.get_data()

    if data.get("role") != "parent":
        await state.clear()
        await callback.answer(
            "❌ Создать семью может только родитель. "
            "Начните регистрацию заново.",
            show_alert=True,
        )
        return

    user_id = callback.from_user.id

    try:
        await profile_service.create_family_and_link(
            admin_user_id=user_id,
        )
    except ValueError:
        logger.warning(
            "Family creation rejected: user_id=%s",
            user_id,
        )
        await state.clear()
        await callback.answer(
            "❌ Не удалось создать семью. "
            "Отправьте /start и попробуйте снова.",
            show_alert=True,
        )
        return

    user_dto = await profile_service.get_user_profile_dto(
        user_id,
    )

    await callback.message.edit_text(
        UIRenderer.render_family_created(user_dto.name),
        parse_mode="HTML",
    )
    await _show_main_menu(callback.message)

    await state.clear()
    await callback.answer()
    

@router.callback_query(
    RegistrationStates.waiting_for_family_action,
    F.data == callbacks.FAMILY_JOIN,
)
async def process_family_join_btn(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Переходит к вводу short code family invitation.

    Join flow допустим только для child и parent. Observer уже
    направляется к short-code flow из process_name().
    """
    data = await state.get_data()
    role = _read_registration_role(data)

    if role not in {"child", "parent"}:
        await state.clear()
        await callback.answer(
            "❌ Состояние регистрации устарело. "
            "Отправьте /start и начните заново.",
            show_alert=True,
        )
        return

    await callback.message.edit_text(
        UIRenderer.render_family_code_join_intro(
            intended_role=role,
        ),
        parse_mode="HTML",
    )
    await state.set_state(
        RegistrationStates.waiting_for_family_code,
    )
    await callback.answer()
    

@router.callback_query(
    RegistrationStates.waiting_for_family_action,
    F.data == callbacks.FAMILY_SKIP,
)
async def process_family_skip_btn(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    """
    Продолжает standalone child registration с выбора класса.

    FAMILY_SKIP допустим только для child flow: это защита от
    manually forged callback data.
    """
    data = await state.get_data()

    if data.get("role") != "child":
        await state.clear()
        await callback.answer(
            "❌ Этот шаг регистрации недоступен для текущей роли.",
            show_alert=True,
        )
        return

    await _show_class_selection(
        callback.message,
        state=state,
        schedule_service=schedule_service,
        edit_message=True,
    )
    await callback.answer()


@router.message(RegistrationStates.waiting_for_family_code)
async def process_family_code_input(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Вход в семью по КОРОТКОМУ КОДУ приглашения.

    Роль зашита в приглашение админом при создании — входящий её
    не выбирает (главное отличие от легаси family_code).
    Варианты:
    - код не найден/истёк/отозван/исчерпан -> отказ;
    - роль кода != роль входящего -> отказ с подсказкой;
    - child -> выбор класса/группы, consume в process_group
      (тот же deep-link поток по invite token из FSM);
    - parent/observer -> consume сразу, главное меню.
    """
    code = normalize_short_code(message.text)
    data = await state.get_data()
    role = _read_registration_role(data)
    user_id = message.from_user.id

    if role not in _ALLOWED_INVITE_ROLES:
        await state.clear()
        await message.answer(
            "❌ Состояние регистрации устарело. "
            "Отправьте /start и начните заново.",
        )
        return

    invite = await profile_service.get_valid_family_invite_by_code(code)
    if invite is None:
        await message.answer(
            "❌ Код не найден, истёк или уже использован.\n\n"
            "Попросите у администратора семьи свежий код приглашения."
        )
        return

    invite_role = invite.intended_role
    if invite_role != role:
        role_titles = {
            "child": "для ребёнка",
            "parent": "для родителя",
            "observer": "для наблюдателя",
        }
        await message.answer(
            "❌ Этот код — "
            + role_titles.get(invite_role, "другой роли") + ".\n\n"
            "Попросите у администратора семьи код "
            + role_titles.get(role, "нужной роли") + "."
        )
        return

    # 1. Извлекаем актуальный профиль ДО вызова consume_family_invite, 
    # чтобы получить вручную введенное на предыдущем шаге имя.
    user_dto = await profile_service.get_user_profile_dto(user_id)
    current_name = user_dto.name or message.from_user.first_name or "Пользователь"

    if invite_role == "child":
        await _store_family_invite_context(
            state,
            token=invite.token,
            role=invite_role,
            actor_user_id=user_id,
            pending_name=current_name,
            reset_existing_state=True,
        )
        await _show_class_selection(
            message,
            state=state,
            schedule_service=schedule_service,
            edit_message=False,
        )
        return

    # 2. Передаем current_name (которое теперь гарантированно хранит ручной ввод)
    consumed_role = await profile_service.consume_family_invite(
        token=invite.token,
        user_id=user_id,
        name=data.get("pending_invite_name") or current_name,
    )
    
    if consumed_role is None:
        await state.clear()
        await message.answer(
            "❌ Приглашение уже использовано или истёк срок. "
            "Попросите у администратора семьи новый код."
        )
        return
        
    # Обновляем DTO на случай, если consume_family_invite изменил другие поля
    updated_dto = await profile_service.get_user_profile_dto(
        user_id,
    )
    await state.clear()

    await _show_registration_success(
        message,
        text=UIRenderer.render_success_join(
            name=updated_dto.name,
            role=consumed_role,
        ),
        delete_origin_message=False,
    )
    return


@router.callback_query(
    RegistrationStates.waiting_for_class,
    RegistrationClassCD.filter(),
)
async def process_class(
    callback: CallbackQuery,
    callback_data: RegistrationClassCD,
    state: FSMContext,
    schedule_service: ScheduleService,
) -> None:
    class_id = callback_data.class_id
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
    RegistrationGroupCD.filter(),
)
async def process_group(
    callback: CallbackQuery,
    callback_data: RegistrationGroupCD,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
) -> None:
    group_id = callback_data.group_id
    data = await state.get_data()

    try:
        invite_context = _read_family_invite_context(data)
    except ValueError:
        await state.clear()
        await callback.answer(
            "❌ Состояние приглашения устарело. "
            "Откройте приглашение заново.",
            show_alert=True,
        )
        return

    class_id = data.get("class_id")

    if invite_context is not None:
        if invite_context.role != "child":
            await state.clear()
            await callback.answer(
                "❌ Состояние приглашения устарело. "
                "Откройте приглашение заново.",
                show_alert=True,
            )
            return

        await _complete_child_family_invite_registration(
            callback,
            state=state,
            invite_context=invite_context,
            class_id=class_id,
            group_id=group_id,
            profile_service=profile_service,
            students_service=students_service,
        )
        return

    await _complete_standalone_child_registration(
        callback,
        state=state,
        class_id=class_id,
        group_id=group_id,
        profile_service=profile_service,
        students_service=students_service,
    )

@router.callback_query(
    RegistrationStates.waiting_for_teacher,
    TeacherRegistrationCD.filter(),
)
async def process_teacher_selection(
    callback: CallbackQuery,
    callback_data: TeacherRegistrationCD,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """
    Завершает teacher registration после выбора NIKA teacher ID.
    """
    teacher_id = callback_data.teacher_id
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
    teacher_name=str(teacher_name),
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.message.answer(
        UIRenderer.render_teacher_registration_success(
            name=user_dto.name,
            teacher_name=str(teacher_name),
        ),
        parse_mode="HTML",
    )
    await _show_main_menu(callback.message)
    await callback.answer(
        "✅ Учительский профиль создан.",
    )
