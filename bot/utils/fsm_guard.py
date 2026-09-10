# bot/utils/fsm_guard.py
#
# ЭТАП 4.5: единая FSM-валидация (устранение бойлерплейта).
#
# ПРОБЛЕМА: в 15+ хендлерах дублировался блок проверки
# актуальности FSM-сессии (15-20 строк в каждом):
#     data = await state.get_data()
#     if data.get("extra_actor_user_id") != actor_user_id:
#         await state.clear()
#         ...alert / answer...
#         return
#
# РЕШЕНИЕ: единый хелпер с двумя режимами проверки:
# - expected: точные значения ключей (принадлежность сессии
#   конкретному пользователю / конкретному ученику);
# - required: ключи, которые просто должны существовать и быть
#   непустыми (паттерн "if not target_student_id or ...").
#
# ПОВЕДЕНИЕ ПРИ ПРОВАЛЕ (унифицировано):
# - FSM-состояние очищается (раньше часть хендлеров не чистила);
# - CallbackQuery -> alert, Message -> обычный ответ;
# - вторичный TelegramBadRequest не ломает проверку.
#
# ВАЖНО: это НЕ декоратор/фильтр намеренно. Фильтр, вернувший
# False, молча роняет апдейт — пользователь получает вечный
# спиннер. Хелпер гарантирует обратную связь.

from __future__ import annotations

import logging
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)

STALE_SESSION_TEXT = "❌ Состояние устарело. Откройте меню заново."


async def _reject_stale(
    event: Message | CallbackQuery,
    state: FSMContext,
    stale_text: str,
) -> None:
    await state.clear()

    if isinstance(event, CallbackQuery):
        try:
            await event.answer(stale_text, show_alert=True)
        except TelegramBadRequest:
            logger.debug("Stale-session alert skipped", exc_info=True)
    else:
        await event.answer(stale_text)


async def validate_fsm_session(
    event: Message | CallbackQuery,
    state: FSMContext,
    *,
    expected: dict[str, Any] | None = None,
    required: list[str] | None = None,
    stale_text: str = STALE_SESSION_TEXT,
) -> bool:
    """
    Проверяет актуальность FSM-сессии. True — можно продолжать.

    Параметры:
        expected: ключ -> точное значение.
            Покрывает паттерн "сессия принадлежит текущему пользователю":
                expected={"extra_actor_user_id": callback.from_user.id}
            и "сессия привязана к конкретному ученику":
                expected={
                    "student_edit_admin_id": callback.from_user.id,
                    "student_edit_id": student_id,
                }
        required: список ключей, которые должны существовать и быть
            непустыми (замена паттерна
            "if not target_student_id or not class_id: ..."):
                required=["target_student_id", "class_id"]

    При провале: state очищается, пользователь получает сообщение,
    хендлер делает `return`.

    Пример использования:

        if not await validate_fsm_session(
            callback,
            state,
            expected={"extra_actor_user_id": callback.from_user.id},
            required=["target_student_id"],
        ):
            return
    """
    if expected or required:
        data = await state.get_data()

        for key, expected_value in (expected or {}).items():
            if data.get(key) != expected_value:
                logger.debug(
                    "FSM session stale: key=%r expected=%r got=%r "
                    "user_id=%s",
                    key,
                    expected_value,
                    data.get(key),
                    event.from_user.id if event.from_user else None,
                )
                await _reject_stale(event, state, stale_text)
                return False

        for key in required or []:
            if not data.get(key):
                logger.debug(
                    "FSM session incomplete: missing key=%r user_id=%s",
                    key,
                    event.from_user.id if event.from_user else None,
                )
                await _reject_stale(event, state, stale_text)
                return False

    return True
