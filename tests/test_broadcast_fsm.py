# tests/test_broadcast_fsm.py
#
# Полный цикл admin-рассылки на уровне хендлеров:
# команда -> текст -> (фото) -> (кнопка) -> предпросмотр -> подтверждение.
#
# Прямой вызов хендлеров с fake Message/Callback/State — как в
# test_registration_fsm.py. Реальный BroadcastService на sqlite
# (из test_broadcast_service.make_service) + fake dispatcher/bot.

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bot.callbacks import BroadcastConfirmCD
from bot.handlers import admin_broadcast
from bot.handlers.admin_broadcast import BroadcastFlow
from core.models.dto import (
    BroadcastAudience,
    BroadcastAudienceDTO,
)
from tests.test_broadcast_service import make_service

ADMIN_ID = 42
USER_IDS = (101, 102)


class _FakeState:
    def __init__(self, initial_data: dict | None = None) -> None:
        self.data = dict(initial_data or {})
        self.clear_calls = 0
        self.current_state = None

    async def get_data(self) -> dict:
        return dict(self.data)

    async def clear(self) -> None:
        self.clear_calls += 1
        self.data.clear()
        self.current_state = None

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)

    async def set_state(self, state) -> None:
        self.current_state = state


class _FakeMessage:
    def __init__(
        self,
        *,
        user_id: int,
        text: str | None = None,
        photo: list | None = None,
    ) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=user_id)
        self.text = text
        self.photo = photo
        self.answers: list[dict] = []
        self.photo_answers: list[dict] = []
        self.edits: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append({"text": text, **kwargs})

    async def answer_photo(
        self,
        *,
        photo,
        caption,
        reply_markup=None,
        parse_mode=None,
    ) -> None:
        self.photo_answers.append(
            {
                "photo": photo,
                "caption": caption,
                "reply_markup": reply_markup,
            }
        )

    async def edit_text(
        self,
        text: str,
        reply_markup=None,
        parse_mode="HTML",
    ) -> None:
        self.edits.append(
            {"text": text, "reply_markup": reply_markup}
        )


class _FakeCallback:
    def __init__(self, *, user_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.message = _FakeMessage(user_id=user_id)
        self.answers: list[dict] = []

    async def answer(
        self,
        text: str | None = None,
        show_alert: bool = False,
        **kwargs,
    ) -> None:
        self.answers.append(
            {"text": text, "show_alert": show_alert}
        )


class _FakeCommand:
    def __init__(self, args: str | None) -> None:
        self.args = args


class _FakeAdminService:
    def __init__(self, admin_ids: set[int]) -> None:
        self._admin_ids = set(admin_ids)

    def is_admin(self, *, user_id: int) -> bool:
        return user_id in self._admin_ids


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
    ) -> None:
        self.sent.append(
            {"chat_id": chat_id, "text": text}
        )


def _prepare_audience(profile) -> None:
    profile.audiences[BroadcastAudience.ALL] = (
        BroadcastAudienceDTO(
            recipient_ids=USER_IDS,
            skipped=0,
        )
    )


# ==============================================================
# Полный цикл без фото и кнопки
# ==============================================================

async def test_full_cycle_text_only(tmp_path):
    service, profile, dispatcher, _audit = make_service(tmp_path)
    _prepare_audience(profile)
    admin = _FakeAdminService({ADMIN_ID})
    state = _FakeState()

    # Шаг 1: /message
    message = _FakeMessage(user_id=ADMIN_ID, text="/message")
    await admin_broadcast.cmd_broadcast_start(
        message,
        _FakeCommand(args=""),
        state,
        admin_service=admin,
        broadcast_service=service,
    )

    assert state.current_state == BroadcastFlow.waiting_text
    assert state.data["broadcast_admin_user_id"] == ADMIN_ID
    assert state.data["broadcast_audience"] == "all"
    assert "(2)" in str(message.answers[0]["text"])

    # Шаг 2: текст.
    # РЕГРЕССИЯ: broadcast_text ещё не существует в state —
    # валидация обязана пропускать (баг «Состояние устарело»).
    text_message = _FakeMessage(
        user_id=ADMIN_ID,
        text="Тест рассылки",
    )
    await admin_broadcast.broadcast_receive_text(
        text_message,
        state,
    )

    # clear == 1: рестарт флоу в cmd_broadcast_start.
    # Stale-очистки НЕТ — фикс required=[broadcast_audience] работает.
    assert state.clear_calls == 1
    assert state.data["broadcast_text"] == "Тест рассылки"
    assert text_message.answers[0]["reply_markup"] is not None

    # Шаг 3: без фото (промпт редактируется в кнопочный).
    photo_callback = _FakeCallback(user_id=ADMIN_ID)
    await admin_broadcast.broadcast_photo_no(photo_callback, state)

    assert state.current_state is None
    assert len(photo_callback.message.edits) == 1
    assert (
        photo_callback.message.edits[0]["reply_markup"] is not None
    )

    # Шаг 4: без кнопки -> предпросмотр.
    button_callback = _FakeCallback(user_id=ADMIN_ID)
    await admin_broadcast.broadcast_button_no(
        button_callback,
        state,
        service,
    )

    # FSM очищен: дальше флоу живёт через БД.
    # FSM очищен: рестарт (1) + очистка после предпросмотра (1).
    assert state.clear_calls == 2
    assert not state.data

    preview = button_callback.message.answers[-1]
    assert preview["reply_markup"] is not None

    confirm_data = BroadcastConfirmCD.unpack(
        preview["reply_markup"]
        .inline_keyboard[0][0]
        .callback_data
    )

    # Черновик создан и принадлежит админу.
    assert (
        await service.get_owned_draft_audience(
            broadcast_id=confirm_data.broadcast_id,
            admin_user_id=ADMIN_ID,
        )
        == BroadcastAudience.ALL
    )

    # Шаг 5: подтверждение -> фоновая отправка -> отчёт.
    bot = _FakeBot()
    confirm_callback = _FakeCallback(user_id=ADMIN_ID)
    await admin_broadcast.broadcast_confirm(
        confirm_callback,
        confirm_data,
        bot,
        service,
    )

    tasks = list(admin_broadcast._broadcast_tasks)
    if tasks:
        await asyncio.gather(*tasks)

    assert dispatcher.send_calls == list(USER_IDS)
    assert len(bot.sent) == 1
    assert "Рассылка завершена" in bot.sent[0]["text"]

    # Черновик больше не draft.
    assert (
        await service.get_owned_draft_audience(
            broadcast_id=confirm_data.broadcast_id,
            admin_user_id=ADMIN_ID,
        )
        is None
    )

    # Повторное подтверждение того же broadcast — stale,
    # второй отчёт не отправляется.
    second_callback = _FakeCallback(user_id=ADMIN_ID)
    await admin_broadcast.broadcast_confirm(
        second_callback,
        confirm_data,
        bot,
        service,
    )
    assert second_callback.answers[-1]["show_alert"] is True
    assert len(bot.sent) == 1


# ==============================================================
# Полный цикл с фото и кнопкой
# ==============================================================

async def test_full_cycle_with_photo_and_button(tmp_path):
    service, profile, _dispatcher, _audit = make_service(tmp_path)
    _prepare_audience(profile)
    admin = _FakeAdminService({ADMIN_ID})
    state = _FakeState(
        {
            "broadcast_admin_user_id": ADMIN_ID,
            "broadcast_audience": "all",
        }
    )
    state.current_state = BroadcastFlow.waiting_text

    # Текст.
    await admin_broadcast.broadcast_receive_text(
        _FakeMessage(user_id=ADMIN_ID, text="С новостью лицея!"),
        state,
    )

    # Фото: да -> ожидание фото.
    photo_yes = _FakeCallback(user_id=ADMIN_ID)
    await admin_broadcast.broadcast_photo_yes(photo_yes, state)
    assert state.current_state == BroadcastFlow.waiting_photo

    # Само фото.
    photo_message = _FakeMessage(
        user_id=ADMIN_ID,
        photo=[SimpleNamespace(file_id="file-id-123")],
    )
    await admin_broadcast.broadcast_receive_photo(
        photo_message,
        state,
    )
    assert state.data["broadcast_photo_file_id"] == "file-id-123"
    assert state.current_state is None

    # Кнопка: да -> ожидание URL.
    button_yes = _FakeCallback(user_id=ADMIN_ID)
    await admin_broadcast.broadcast_button_yes(button_yes, state)
    assert state.current_state == BroadcastFlow.waiting_button_url

    # Невалидный URL отклоняется, состояние не меняется.
    bad_url = _FakeMessage(
        user_id=ADMIN_ID,
        text="t.me/not-a-full-url",
    )
    await admin_broadcast.broadcast_receive_button_url(
        bad_url,
        state,
    )
    assert "broadcast_button_url" not in state.data
    assert state.current_state == BroadcastFlow.waiting_button_url

    # Валидный URL.
    await admin_broadcast.broadcast_receive_button_url(
        _FakeMessage(
            user_id=ADMIN_ID,
            text="https://lyceum.nstu.ru/news",
        ),
        state,
    )
    assert (
        state.data["broadcast_button_url"]
        == "https://lyceum.nstu.ru/news"
    )
    assert state.current_state == BroadcastFlow.waiting_button_text

    # Текст кнопки -> предпросмотр с фото и caption.
    button_text_message = _FakeMessage(
        user_id=ADMIN_ID,
        text="Открыть новость",
    )
    await admin_broadcast.broadcast_receive_button_text(
        button_text_message,
        state,
        service,
    )

    assert state.clear_calls == 1
    assert len(button_text_message.photo_answers) == 1
    assert (
        button_text_message.photo_answers[0]["caption"]
        == "С новостью лицея!"
    )
    assert (
        button_text_message.photo_answers[0]["photo"]
        == "file-id-123"
    )
    assert (
        button_text_message.photo_answers[0]["reply_markup"]
        is not None
    )


# ==============================================================
# Guard-сценарии
# ==============================================================

async def test_text_step_rejects_foreign_actor(tmp_path):
    service, _profile, _dispatcher, _audit = make_service(tmp_path)
    state = _FakeState(
        {
            "broadcast_admin_user_id": ADMIN_ID,
            "broadcast_audience": "all",
        }
    )
    state.current_state = BroadcastFlow.waiting_text

    foreign = _FakeMessage(user_id=999, text="Перехват флоу")
    await admin_broadcast.broadcast_receive_text(foreign, state)

    assert state.clear_calls == 1
    assert "устарело" in str(foreign.answers[0]["text"])
    assert "broadcast_text" not in state.data


async def test_command_denied_for_non_admin(tmp_path):
    service, profile, _dispatcher, _audit = make_service(tmp_path)
    _prepare_audience(profile)
    admin = _FakeAdminService({ADMIN_ID})
    state = _FakeState()

    message = _FakeMessage(user_id=999, text="/message")
    await admin_broadcast.cmd_broadcast_start(
        message,
        _FakeCommand(args=""),
        state,
        admin_service=admin,
        broadcast_service=service,
    )

    assert state.current_state is None
    assert not state.data
    assert "только администратору" in str(
        message.answers[0]["text"]
    )


async def test_command_rejects_unknown_audience(tmp_path):
    service, profile, _dispatcher, _audit = make_service(tmp_path)
    _prepare_audience(profile)
    admin = _FakeAdminService({ADMIN_ID})
    state = _FakeState()

    message = _FakeMessage(user_id=ADMIN_ID, text="/message aliens")
    await admin_broadcast.cmd_broadcast_start(
        message,
        _FakeCommand(args="aliens"),
        state,
        admin_service=admin,
        broadcast_service=service,
    )

    assert state.current_state is None
    assert "Использование" in str(message.answers[0]["text"])