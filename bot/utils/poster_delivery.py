"""Доставка PNG-постеров в Telegram с file_id-фолбэком (этап 3 ТЗ v2.2).

Схема отправки (решение из обсуждения): file_id в редких случаях может
протухнуть (пересборка бота с новым токеном, чистка старых файлов на
серверах Telegram) — одна протухшая запись НЕ должна валить показ постера:

1. file_id из L2 -> отправка по нему (мгновенно, без загрузки байтов);
2. TelegramBadRequest с признаками протухшего file_id -> запись
   инвалидируется, повторная отправка байтами из L1;
3. при успехе байтов новый file_id сохраняется в L2.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto, Message

from services.image_render.models import RenderedPoster
from services.image_render.service import ImageGenerationService

logger = logging.getLogger(__name__)

# Признаки протухшего file_id в тексте TelegramBadRequest
_STALE_FILE_MARKERS = (
    "wrong file identifier",
    "wrong file id",
    "file not found",
    "failed to get url",
    "file is too big",
)


def _looks_like_stale_file_id(exc: TelegramBadRequest) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _STALE_FILE_MARKERS)


def build_day_caption(date_text: str, changes_count: int, subtitle: str | None = None) -> str:
    """Краткая подпись к постеру (лимит Telegram — 1024 символа).

    В caption только дата, кого показываем и счётчик изменений;
    детали замен — за существующей кнопкой «Изменения» (решение
    обсуждения: без длинного спойлера в caption).
    """
    lines = [f"📅 {date_text}"]
    if subtitle:
        lines.append(f"👤 {subtitle}")
    if changes_count:
        lines.append(f"🔄 Изменений: {changes_count}")
    return "\n".join(lines)[:1000]


def _file_id_of(message: Any) -> str | None:
    """file_id самого крупного размера отправленного фото."""
    photo = getattr(message, "photo", None)
    if not photo:
        return None
    return photo[-1].file_id


class _PosterAnswering(Protocol):
    """Минимальный протокол message.answer_photo (для тестов)."""

    async def answer_photo(self, photo: Any, caption: str | None = None,
                            reply_markup: Any = None) -> Any: ...


class _PosterEditing(Protocol):
    """Минимальный протокол message.edit_media (для тестов)."""

    async def edit_media(self, media: InputMediaPhoto, reply_markup: Any = None) -> Any: ...


async def send_poster(
    message: _PosterAnswering,
    image_service: ImageGenerationService,
    poster: RenderedPoster,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
) -> Any:
    """Отправка нового сообщения-постера: file_id -> байты -> сохранение file_id."""
    file_id = image_service.get_file_id(poster.request_id)
    if file_id is not None:
        try:
            return await message.answer_photo(file_id, caption=caption, reply_markup=keyboard)
        except TelegramBadRequest as exc:
            if _looks_like_stale_file_id(exc):
                image_service.invalidate_file_id(poster.request_id)
                logger.warning("Протухший file_id для %s — перезалив байтами", poster.request_id)
            else:
                raise

    sent = await message.answer_photo(
        BufferedInputFile(poster.png_bytes, filename=f"{poster.request_id}.png"),
        caption=caption,
        reply_markup=keyboard,
    )
    new_file_id = _file_id_of(sent)
    if new_file_id:
        image_service.store_file_id(poster.request_id, new_file_id)
    return sent


async def edit_poster(
    callback: CallbackQuery,
    image_service: ImageGenerationService,
    poster: RenderedPoster,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
) -> None:
    """Перелистывание дня: edit_media меняет картинку без мерцания.

    Если исходное сообщение — не фото (текст после деградации),
    edit_media не сработает: удаляем сообщение и отправляем постер заново.
    """
    file_id = image_service.get_file_id(poster.request_id)
    if file_id is not None:
        try:
            await callback.message.edit_media(
                InputMediaPhoto(media=file_id, caption=caption),
                reply_markup=keyboard,
            )
            return
        except TelegramBadRequest as exc:
            if _looks_like_stale_file_id(exc):
                image_service.invalidate_file_id(poster.request_id)
                logger.warning("Протухший file_id для %s — перезалив байтами", poster.request_id)
            elif "message is not modified" in str(exc).lower():
                return  # тот же день, ничего не делаем
            elif "no photo" in str(exc).lower():
                pass  # сообщение не фото — перейдём к пересозданию ниже
            else:
                raise

    try:
        edited = await callback.message.edit_media(
            InputMediaPhoto(
                media=BufferedInputFile(poster.png_bytes, filename=f"{poster.request_id}.png"),
                caption=caption,
            ),
            reply_markup=keyboard,
        )
        new_file_id = _file_id_of(edited)
        if new_file_id:
            image_service.store_file_id(poster.request_id, new_file_id)
    except TelegramBadRequest as exc:
        if "no photo" in str(exc).lower():
            # Исходное сообщение — текст: заменяем отправкой нового постера
            await _delete_best_effort(callback)
            await send_poster(callback.message, image_service, poster, caption, keyboard)
        elif "message is not modified" in str(exc).lower():
            return
        else:
            raise


async def fallback_to_text(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
    """Graceful degradation (раздел 5 ТЗ): текущее сообщение — фото,
    поэтому edit_text невозможен: удаляем постер и отправляем текст."""
    await _delete_best_effort(callback)
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


async def _delete_best_effort(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        logger.debug("Не удалось удалить сообщение-постер", exc_info=True)
