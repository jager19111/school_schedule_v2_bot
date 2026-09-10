# bot/utils/safe_send.py
#
# ЭТАП 4.6: хелпер длины сообщений.
#
# ПРОБЛЕМА: Telegram ограничивает сообщение 4096 символами.
# Подробное расписание на неделю может превышать лимит.
# Раньше в двух местах (schedule_child.py и schedule_teacher.py)
# была ручная проверка `len(text) > 3900` с отказом:
#     "Подробная неделя слишком длинная. Используйте просмотр по дням."
# Пользователь нажимал кнопку и получал отказ вместо расписания.
#
# РЕШЕНИЕ: хелпер с авторазбиением длинного текста на части.
# Вместо отказа пользователь получает расписание, разбитое
# на несколько сообщений (по дням недели).
#
# СТРАТЕГИЯ:
# 1. Если текст < SAFETY_LIMIT — отправляем как есть (1 сообщение).
# 2. Если текст >= SAFETY_LIMIT — пытаемся разбить по границам дней
#    (строки, начинающиеся с "━━━━━" — разделитель из _format_date_header).
# 3. Если границы дней не найдены — разбиваем по абзацам ("\n\n").
# 4. Если и это не помогло — разбиваем по строкам ("\n").
# 5. Каждая часть отправляется отдельным сообщением.
#
# ИСПОЛЬЗОВАНИЕ:
#     from bot.utils.safe_send import send_long_message
#
#     await send_long_message(
#         bot=bot,
#         chat_id=callback.message.chat.id,
#         text=text,
#         reply_markup=keyboard,  # только на ПОСЛЕДНЕЙ части
#     )
#
# ЗАМЕТКА: для edit_text (inline-режим) разбиение невозможно —
# Telegram не поддерживает "продолжение" отредактированного
# сообщения. Поэтому хелпер используется в паре с fallback:
# если сообщение слишком длинное для edit, отправляем НОВЫЕ
# сообщения (answer) вместо редактирования.

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)

# Запас на HTML-теги и служебные символы.
SAFETY_LIMIT = 3800

# Разделитель дней в расписании (из UIRenderer._format_date_header).
_DAY_SEPARATOR = "━━━━━━━━━━━━━━━━━"


def split_long_text(
    text: str,
    limit: int = SAFETY_LIMIT,
) -> list[str]:
    """
    Разбивает длинный текст на части, каждая <= limit символов.

    Приоритет разбиения:
    1. По границам дней (━━━) — сохраняет целостность расписания.
    2. По абзацам (\n\n).
    3. По строкам (\n).
    4. Жёсткий разрез (крайний случай).
    """
    if len(text) <= limit:
        return [text]

    # Стратегия 1: по разделителям дней
    parts = _split_by_separator(text, _DAY_SEPARATOR, limit)
    if parts:
        return parts

    # Стратегия 2: по абзацам
    parts = _split_by_separator(text, "\n\n", limit)
    if parts:
        return parts

    # Стратегия 3: по строкам
    parts = _split_by_separator(text, "\n", limit)
    if parts:
        return parts

    # Стратегия 4: жёсткий разрез
    return [
        text[i : i + limit]
        for i in range(0, len(text), limit)
    ]


def _split_by_separator(
    text: str,
    separator: str,
    limit: int,
) -> list[str]:
    """
    Пытается разбить текст по разделителю, чтобы каждая часть
    была <= limit. Возвращает [] если не получилось.
    """
    segments = text.split(separator)

    if len(segments) <= 1:
        return []

    # Первый сегмент — заголовок, добавляем к нему первый разделитель
    parts: list[str] = []
    current = segments[0] + separator

    for segment in segments[1:]:
        candidate = current + segment + separator

        if len(candidate) <= limit:
            current = candidate
        else:
            # Текущая часть готова
            if current.strip():
                parts.append(current)
            current = segment + separator

            # Если даже один день превышает лимит — отказ от стратегии
            if len(current) > limit:
                return []

    if current.strip():
        parts.append(current)

    return parts if parts else []


async def send_long_message(
    *,
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
) -> list[Message]:
    """
    Отправляет текст, при необходимости разбивая на части.

    Клавиатура (reply_markup) прикрепляется ТОЛЬКО к последней части.

    Возвращает список отправленных сообщений.
    """
    parts = split_long_text(text)
    messages: list[Message] = []

    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        try:
            message = await bot.send_message(
                chat_id=chat_id,
                text=part,
                parse_mode=parse_mode,
                reply_markup=reply_markup if is_last else None,
            )
            messages.append(message)
        except Exception as exc:
            logger.warning(
                "send_long_message: failed to send part %d/%d "
                "to chat_id=%s: %s",
                index + 1,
                len(parts),
                chat_id,
                exc,
            )
            break

    if len(parts) > 1:
        logger.info(
            "Long message split into %d parts for chat_id=%s",
            len(parts),
            chat_id,
        )

    return messages


async def send_or_edit_long(
    *,
    callback,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """
    Универсальная замена ручной проверки len(text) > 3900.

    Если текст помещается в лимит — редактирует существующее
    сообщение (callback.message.edit_text).

    Если НЕ помещается — удаляет старое сообщение и отправляет
    расписание частями новыми сообщениями (с клавиатурой на последней).

    Возвращает True если удалось доставить расписание.
    """
    from aiogram.exceptions import TelegramBadRequest

    if len(text) <= SAFETY_LIMIT:
        # Короткий текст — обычное редактирование
        try:
            await callback.message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return True
        except TelegramBadRequest as exc:
            logger.debug("edit_text skipped: %s", exc)
            return False

    # Длинный текст — отправляем частями
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        # Сообщение могло быть уже удалено или недоступно
        logger.debug("delete before split skipped")

    messages = await send_long_message(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        text=text,
        reply_markup=keyboard,
    )

    return len(messages) > 0
