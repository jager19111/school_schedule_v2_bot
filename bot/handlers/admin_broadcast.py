# bot/handlers/admin_broadcast.py
#
# Admin-рассылки: /message [teachers|parents]
# Флоу: текст -> (фото) -> (URL-кнопка) -> предпросмотр -> подтверждение.
#
# Правила:
# - только ADMIN (guard как в admin.py);
# - предпросмотр = реальная отправка админу: HTML-разметка
#   валидируется Telegram ДО подтверждения;
# - подтверждение идемпотентно: draft -> sending атомарен
#   в BroadcastRepository, двойной клик безопасен;
# - после предпросмотра FSM очищается: confirm/edit/cancel
#   проверяют владельца через broadcast-строку в БД;
# - отправка — фоновая задача: рассылка не блокирует
#   обработку апдейтов бота;
# - фото ограничивает текст 1024 символами (caption limit).

from __future__ import annotations

import asyncio
import contextlib
import logging
from urllib.parse import urlparse

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import callbacks
from bot.callbacks import (
    BroadcastCancelCD,
    BroadcastConfirmCD,
    BroadcastEditCD,
)
from bot.keyboards.keyboard import Keyboards
from bot.utils.fsm_guard import validate_fsm_session
from bot.utils.safe_send import _safe_callback_answer, _safe_edit_text
from bot.utils.ui_renderer import UIRenderer
from core.models.dto import BroadcastAudience
from services.admin_service import AdminService
from services.broadcast_service import BroadcastService

logger = logging.getLogger(__name__)
router = Router()

MAX_TEXT_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024
MAX_BUTTON_TEXT_LENGTH = 64

_ADMIN_GUARD_EXPECTED = "broadcast_admin_user_id"
_INPUT_FLOW_REQUIRED = ["broadcast_audience"]
_INPUT_CONTENT_REQUIRED = ["broadcast_audience", "broadcast_text"]


async def _validate_flow_session(
    event: Message | CallbackQuery,
    state: FSMContext,
) -> bool:
    """Шаг ввода текста: контент ещё не собран."""
    return await validate_fsm_session(
        event,
        state,
        expected={
            _ADMIN_GUARD_EXPECTED: event.from_user.id,
        },
        required=_INPUT_FLOW_REQUIRED,
    )


async def _validate_content_session(
    event: Message | CallbackQuery,
    state: FSMContext,
) -> bool:
    """Шаги после текста: текст уже собран."""
    return await validate_fsm_session(
        event,
        state,
        expected={
            _ADMIN_GUARD_EXPECTED: event.from_user.id,
        },
        required=_INPUT_CONTENT_REQUIRED,
    )

class BroadcastFlow(StatesGroup):
    waiting_text = State()
    waiting_photo = State()
    waiting_button_url = State()
    waiting_button_text = State()


_BROADCAST_STATE_FILTER = StateFilter(
    BroadcastFlow.waiting_text,
    BroadcastFlow.waiting_photo,
    BroadcastFlow.waiting_button_url,
    BroadcastFlow.waiting_button_text,
)

_broadcast_tasks: set[asyncio.Task] = set()

_AUDIENCE_COMMANDS = {
    "": BroadcastAudience.ALL,
    "all": BroadcastAudience.ALL,
    "teachers": BroadcastAudience.TEACHERS,
    "teacher": BroadcastAudience.TEACHERS,
    "parents": BroadcastAudience.FAMILY,
    "family": BroadcastAudience.FAMILY,
}


async def _require_admin(
    *,
    message: Message,
    admin_service: AdminService,
) -> bool:
    if admin_service.is_admin(user_id=message.from_user.id):
        return True
    logger.warning(
        "Admin command denied: user_id=%s command=%r",
        message.from_user.id,
        message.text,
    )
    await message.answer("⛔ Команда доступна только администратору.")
    return False


# ==============================================================
# Шаг 1: команда
# ==============================================================

@router.message(Command("message"))
async def cmd_broadcast_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    admin_service: AdminService,
    broadcast_service: BroadcastService,
) -> None:
    if not await _require_admin(message=message, admin_service=admin_service):
        return

    arg = (command.args or "").strip().lower()
    audience = _AUDIENCE_COMMANDS.get(arg)
    if audience is None:
        await message.answer(
            UIRenderer.render_broadcast_usage(),
            parse_mode="HTML",
        )
        return

    await state.clear()

    recipient_count = await broadcast_service.get_audience_count(audience)
    if recipient_count == 0:
        await message.answer(UIRenderer.render_broadcast_no_recipients())
        return

    await state.set_state(BroadcastFlow.waiting_text)
    await state.update_data(
        broadcast_admin_user_id=message.from_user.id,
        broadcast_audience=audience.value,
    )

    await message.answer(
        UIRenderer.render_broadcast_prompt(
            audience=audience,
            recipient_count=recipient_count,
        ),
        parse_mode="HTML",
    )


@router.message(Command("cancel"), _BROADCAST_STATE_FILTER)
async def cmd_broadcast_cancel(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()
    await message.answer(UIRenderer.render_broadcast_cancelled())


# ==============================================================
# Шаг 2: текст
# ==============================================================

@router.message(BroadcastFlow.waiting_text, F.text)
async def broadcast_receive_text(
    message: Message,
    state: FSMContext,
) -> None:
    if not await _validate_flow_session(message, state):
        return

    text = message.text or ""

    if text.startswith("/"):
        await message.answer(
            UIRenderer.render_broadcast_text_command_hint()
        )
        return

    if len(text) > MAX_TEXT_LENGTH:
        await message.answer(
            UIRenderer.render_broadcast_text_too_long(
                length=len(text),
                limit=MAX_TEXT_LENGTH,
            )
        )
        return

    await state.update_data(broadcast_text=text)

    await message.answer(
        UIRenderer.render_broadcast_photo_prompt(
            caption_limit_warning=(
                len(text) > MAX_CAPTION_LENGTH
            ),
        ),
        reply_markup=Keyboards.get_broadcast_photo_prompt(),
        parse_mode="HTML",
    )


@router.message(BroadcastFlow.waiting_text)
async def broadcast_text_invalid(message: Message) -> None:
    await message.answer(UIRenderer.render_broadcast_text_expected())


# ==============================================================
# Шаг 3: фото
# ==============================================================

@router.callback_query(F.data == callbacks.BROADCAST_PHOTO_YES)
async def broadcast_photo_yes(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not await _validate_content_session(callback, state):
        return

    data = await state.get_data()
    if len(data["broadcast_text"]) > MAX_CAPTION_LENGTH:
        await _safe_callback_answer(
            callback,
            "Текст больше 1024 символов — с фото не отправится. "
            "Сократите текст или продолжите без фото.",
            show_alert=True,
        )
        return

    await state.set_state(BroadcastFlow.waiting_photo)
    await _safe_callback_answer(callback, "Отправьте фото.")


@router.callback_query(F.data == callbacks.BROADCAST_PHOTO_NO)
async def broadcast_photo_no(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not await _validate_content_session(callback, state):
        return

    # Промпт редактируется: старая клавиатура не остаётся активной.
    await state.set_state(None)
    await _safe_edit_text(
        callback.message,
        UIRenderer.render_broadcast_button_prompt(),
        reply_markup=Keyboards.get_broadcast_button_prompt(),
    )
    await _safe_callback_answer(callback)


@router.message(BroadcastFlow.waiting_photo, F.photo)
async def broadcast_receive_photo(
    message: Message,
    state: FSMContext,
) -> None:
    if not await _validate_content_session(message, state):
        return

    await state.update_data(
        broadcast_photo_file_id=message.photo[-1].file_id,
    )
    await state.set_state(None)

    await message.answer(
        UIRenderer.render_broadcast_button_prompt(),
        reply_markup=Keyboards.get_broadcast_button_prompt(),
        parse_mode="HTML",
    )


@router.message(BroadcastFlow.waiting_photo)
async def broadcast_photo_invalid(message: Message) -> None:
    await message.answer(UIRenderer.render_broadcast_photo_expected())


# ==============================================================
# Шаг 4: URL-кнопка
# ==============================================================

@router.callback_query(F.data == callbacks.BROADCAST_BUTTON_YES)
async def broadcast_button_yes(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not await _validate_content_session(callback, state):
        return

    await state.set_state(BroadcastFlow.waiting_button_url)
    await _safe_edit_text(
        callback.message,
        UIRenderer.render_broadcast_button_url_prompt(),
        reply_markup=None,
    )
    await _safe_callback_answer(callback)


@router.callback_query(F.data == callbacks.BROADCAST_BUTTON_NO)
async def broadcast_button_no(
    callback: CallbackQuery,
    state: FSMContext,
    broadcast_service: BroadcastService,
) -> None:
    if not await _validate_content_session(callback, state):
        return

    await _show_broadcast_preview(
        callback.message,
        state,
        broadcast_service,
        admin_user_id=callback.from_user.id,
    )
    await _safe_callback_answer(callback)


@router.message(BroadcastFlow.waiting_button_url, F.text)
async def broadcast_receive_button_url(
    message: Message,
    state: FSMContext,
) -> None:
    if not await _validate_content_session(message, state):
        return

    raw = (message.text or "").strip()
    parsed = urlparse(raw)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        await message.answer(
            UIRenderer.render_broadcast_button_url_invalid()
        )
        return

    await state.update_data(broadcast_button_url=raw)
    await state.set_state(BroadcastFlow.waiting_button_text)
    await message.answer(
        UIRenderer.render_broadcast_button_text_prompt(
            limit=MAX_BUTTON_TEXT_LENGTH,
        )
    )


@router.message(BroadcastFlow.waiting_button_text, F.text)
async def broadcast_receive_button_text(
    message: Message,
    state: FSMContext,
    broadcast_service: BroadcastService,
) -> None:
    if not await _validate_content_session(message, state):
        return

    button_text = (message.text or "").strip()
    if not button_text or len(button_text) > MAX_BUTTON_TEXT_LENGTH:
        await message.answer(
            UIRenderer.render_broadcast_button_text_invalid(
                limit=MAX_BUTTON_TEXT_LENGTH,
            )
        )
        return

    await state.update_data(broadcast_button_text=button_text)
    await _show_broadcast_preview(
        message,
        state,
        broadcast_service,
        admin_user_id=message.from_user.id,
    )


@router.message(
    StateFilter(
        BroadcastFlow.waiting_button_url,
        BroadcastFlow.waiting_button_text,
    )
)
async def broadcast_button_input_invalid(message: Message) -> None:
    await message.answer(
        UIRenderer.render_broadcast_button_url_prompt()
    )


# ==============================================================
# Шаг 5: предпросмотр
# ==============================================================

async def _show_broadcast_preview(
    message: Message,
    state: FSMContext,
    broadcast_service: BroadcastService,
    *,
    admin_user_id: int,
) -> None:
    data = await state.get_data()
    audience = BroadcastAudience(data["broadcast_audience"])

    created = await broadcast_service.create_draft(
        admin_user_id=admin_user_id,
        audience=audience,
        text=data["broadcast_text"],
        photo_file_id=data.get("broadcast_photo_file_id"),
        button_text=data.get("broadcast_button_text"),
        button_url=data.get("broadcast_button_url"),
    )

    keyboard = Keyboards.get_broadcast_confirm_kb(
        broadcast_id=created.broadcast_id,
    )

    await message.answer(
        UIRenderer.render_broadcast_preview_header(),
        parse_mode="HTML",
    )

    try:
        if data.get("broadcast_photo_file_id"):
            await message.answer_photo(
                photo=data["broadcast_photo_file_id"],
                caption=data["broadcast_text"],
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await message.answer(
                data["broadcast_text"],
                reply_markup=keyboard,
                parse_mode="HTML",
            )
    except TelegramBadRequest as exc:
        await broadcast_service.cancel_draft(
            broadcast_id=created.broadcast_id,
        )
        logger.warning(
            "Broadcast preview rejected (bad HTML): "
            "broadcast_id=%s error=%s",
            created.broadcast_id,
            exc,
        )
        await message.answer(
            UIRenderer.render_broadcast_preview_rejected()
        )
        await state.set_state(BroadcastFlow.waiting_text)
        await state.update_data(
            broadcast_admin_user_id=admin_user_id,
            broadcast_audience=audience.value,
        )
        return

    await state.clear()


# ==============================================================
# Шаг 6: подтверждение / изменение / отмена
# ==============================================================

@router.callback_query(BroadcastConfirmCD.filter())
async def broadcast_confirm(
    callback: CallbackQuery,
    callback_data: BroadcastConfirmCD,
    bot: Bot,
    broadcast_service: BroadcastService,
) -> None:
    audience = await broadcast_service.get_owned_draft_audience(
        broadcast_id=callback_data.broadcast_id,
        admin_user_id=callback.from_user.id,
    )
    if audience is None:
        await _safe_callback_answer(
            callback,
            UIRenderer.render_broadcast_stale(),
            show_alert=True,
        )
        return

    await _safe_callback_answer(callback, "Рассылка запущена.")
    await _safe_edit_text(
        callback.message,
        UIRenderer.render_broadcast_launched(),
        reply_markup=None,
    )

    _spawn_broadcast_task(
        bot=bot,
        broadcast_service=broadcast_service,
        broadcast_id=callback_data.broadcast_id,
        admin_user_id=callback.from_user.id,
        chat_id=callback.message.chat.id,
    )


@router.callback_query(BroadcastEditCD.filter())
async def broadcast_edit(
    callback: CallbackQuery,
    callback_data: BroadcastEditCD,
    state: FSMContext,
    broadcast_service: BroadcastService,
) -> None:
    audience = await broadcast_service.get_owned_draft_audience(
        broadcast_id=callback_data.broadcast_id,
        admin_user_id=callback.from_user.id,
    )
    if audience is None:
        await _safe_callback_answer(
            callback,
            UIRenderer.render_broadcast_stale(),
            show_alert=True,
        )
        return

    await broadcast_service.cancel_draft(
        broadcast_id=callback_data.broadcast_id,
    )

    await state.set_state(BroadcastFlow.waiting_text)
    await state.update_data(
        broadcast_admin_user_id=callback.from_user.id,
        broadcast_audience=audience.value,
    )

    await _safe_edit_text(
        callback.message,
        UIRenderer.render_broadcast_edit_prompt(),
        reply_markup=None,
    )
    await _safe_callback_answer(callback, "Возврат к редактированию.")


@router.callback_query(BroadcastCancelCD.filter())
async def broadcast_cancel(
    callback: CallbackQuery,
    callback_data: BroadcastCancelCD,
    broadcast_service: BroadcastService,
) -> None:
    audience = await broadcast_service.get_owned_draft_audience(
        broadcast_id=callback_data.broadcast_id,
        admin_user_id=callback.from_user.id,
    )
    if audience is None:
        await _safe_callback_answer(
            callback,
            UIRenderer.render_broadcast_stale(),
            show_alert=True,
        )
        return

    await broadcast_service.cancel_draft(
        broadcast_id=callback_data.broadcast_id,
    )
    await _safe_edit_text(
        callback.message,
        UIRenderer.render_broadcast_cancelled(),
        reply_markup=None,
    )
    await _safe_callback_answer(callback, "Отменено.")


# ==============================================================
# Фоновая отправка
# ==============================================================

def _spawn_broadcast_task(
    *,
    bot: Bot,
    broadcast_service: BroadcastService,
    broadcast_id: int,
    admin_user_id: int,
    chat_id: int,
) -> None:
    task = asyncio.create_task(
        _run_broadcast_and_report(
            bot=bot,
            broadcast_service=broadcast_service,
            broadcast_id=broadcast_id,
            admin_user_id=admin_user_id,
            chat_id=chat_id,
        )
    )
    _broadcast_tasks.add(task)
    task.add_done_callback(_broadcast_tasks.discard)


async def _run_broadcast_and_report(
    *,
    bot: Bot,
    broadcast_service: BroadcastService,
    broadcast_id: int,
    admin_user_id: int,
    chat_id: int,
) -> None:
    try:
        report = await broadcast_service.run_broadcast(
            broadcast_id=broadcast_id,
            admin_user_id=admin_user_id,
        )
    except Exception:
        logger.exception(
            "Broadcast task failed: broadcast_id=%s",
            broadcast_id,
        )
        with contextlib.suppress(TelegramBadRequest):
            await bot.send_message(
                chat_id,
                UIRenderer.render_broadcast_task_failed(),
                parse_mode="HTML",
            )
        return

    if report is None:
        return

    with contextlib.suppress(TelegramBadRequest):
        await bot.send_message(
            chat_id,
            UIRenderer.render_broadcast_report(report),
            parse_mode="HTML",
        )