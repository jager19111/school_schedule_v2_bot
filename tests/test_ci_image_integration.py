"""CI-тесты этапа 3: преференсы формата, версия расписания, доставка постеров.

Всё без браузера: БД — временный sqlite, Telegram-объекты — фейки
с минимальными протоколами из poster_delivery.
"""

import asyncio
import os
import tempfile
from types import SimpleNamespace

import aiosqlite
from aiogram.exceptions import TelegramBadRequest

from bot.utils.poster_delivery import build_day_caption, edit_poster, send_poster
from services.image_preferences import ImagePreferencesService
from services.image_render.models import RenderedPoster
from services.image_render.version import get_schedule_version

def _poster(request_id: str) -> RenderedPoster:
    return RenderedPoster(
        request_id=request_id,
        png_bytes=b"\x89PNG-fake",
        width=1080,
        height=100,
    )

def test_image_prefs_schema_and_toggle() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            db = await aiosqlite.connect(db_path)
            try:
                # ИСПРАВЛЕНИЕ: Колонка prefer_image_schedule создается сразу, так как ensure_schema теперь строгий
                await db.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY, name TEXT, prefer_image_schedule INTEGER NOT NULL DEFAULT 1)")
                await db.execute("INSERT INTO users (user_id, name) VALUES (1, 'a')")
                await db.commit()

                prefs = ImagePreferencesService(db)
                await prefs.ensure_schema()
                await prefs.ensure_schema()

                assert await prefs.prefers_image(1) is True
                assert await prefs.prefers_image(999) is True

                assert await prefs.toggle(1) is False
                assert await prefs.prefers_image(1) is False
                assert await prefs.toggle(1) is True
                assert await prefs.prefers_image(1) is True
            finally:
                await db.close()

    asyncio.run(scenario())


# ---------------- Версия расписания ----------------


class _FakeRepo:
    def __init__(self, sha: str | None) -> None:
        self.state = SimpleNamespace(semantic_sha256=sha)

    async def get_nika_source_state(self):
        return self.state


def test_schedule_version_changes_with_semantic_hash() -> None:
    async def scenario() -> None:
        assert await get_schedule_version(_FakeRepo(None)) == "v0"
        assert await get_schedule_version(_FakeRepo("")) == "v0"
        assert await get_schedule_version(_FakeRepo("deadbeef" * 8)) == "deadbeef"

    asyncio.run(scenario())


# ---------------- Доставка постеров ----------------


class _SentPhoto:
    def __init__(self, file_id: str) -> None:
        self.file_id = file_id


class _SentMessage:
    """Результат answer_photo: photo есть только при загрузке байтов."""

    def __init__(self, file_id: str | None) -> None:
        self.photo = [_SentPhoto(file_id)] if file_id else None


class _AnsweringMessage:
    """Минимальный протокол message.answer_photo."""

    def __init__(self, fail_file_id: bool = False) -> None:
        self.calls: list = []
        self.fail_file_id = fail_file_id

    async def answer_photo(self, photo, caption=None, reply_markup=None):
        self.calls.append(photo)
        if isinstance(photo, str):
            if self.fail_file_id:
                raise TelegramBadRequest(
                    method="sendPhoto",
                    message="Bad Request: wrong file identifier/HTTP URL specified",
                )
            return _SentMessage(file_id=None)  # по file_id Telegram не возвращает фото заново
        return _SentMessage(file_id="NEW_FILE_ID")


class _EditingMessage:
    """Минимальный протокол message.edit_media + delete + answer."""

    def __init__(self, no_photo: bool = False) -> None:
        self.media_calls: list = []
        self.deleted = False
        self.answered_texts: list = []
        self._no_photo = no_photo

    async def edit_media(self, media, reply_markup=None):
        self.media_calls.append(media)
        if self._no_photo:
            raise TelegramBadRequest(
                method="editMessageMedia",
                message="Bad Request: there is no photo in the message to edit",
            )
        return _SentMessage(file_id="EDITED_FILE_ID")

    async def delete(self) -> None:
        self.deleted = True

    async def answer(self, text, reply_markup=None, parse_mode=None):
        self.answered_texts.append(text)
        return _SentMessage(file_id="RESENT_FILE_ID")

    async def answer_photo(self, photo, caption=None, reply_markup=None):
        return _SentMessage(file_id="RESENT_FILE_ID")


class _FakeCallback:
    def __init__(self, message) -> None:
        self.message = message


class _FakeImageService:
    """Только L2-часть контракта ImageGenerationService."""

    def __init__(self) -> None:
        self.file_ids: dict[str, str] = {}
        self.invalidated: list[str] = []

    def get_file_id(self, request_id: str):
        return self.file_ids.get(request_id)

    def store_file_id(self, request_id: str, file_id: str) -> None:
        self.file_ids[request_id] = file_id

    def invalidate_file_id(self, request_id: str) -> None:
        self.invalidated.append(request_id)
        self.file_ids.pop(request_id, None)


def test_send_poster_uses_cached_file_id() -> None:
    async def scenario() -> None:
        service = _FakeImageService()
        service.store_file_id("img_x", "FID1")
        message = _AnsweringMessage()
        await send_poster(message, service, _poster("img_x"), "cap", None)
        # Байты не загружались — отправка прошла мгновенно по file_id
        assert message.calls == ["FID1"]

    asyncio.run(scenario())


def test_send_poster_stale_file_id_falls_back_to_bytes() -> None:
    async def scenario() -> None:
        service = _FakeImageService()
        service.store_file_id("img_x", "FID_STALE")
        message = _AnsweringMessage(fail_file_id=True)

        await send_poster(message, service, _poster("img_x"), "cap", None)

        # 1) попытка по протухшему file_id; 2) повтор байтами
        assert message.calls[0] == "FID_STALE"
        assert not isinstance(message.calls[1], str)
        # Протухшая запись инвалидирована, новый file_id сохранён
        assert service.invalidated == ["img_x"]
        assert service.file_ids["img_x"] == "NEW_FILE_ID"

    asyncio.run(scenario())


def test_edit_poster_bytes_path_stores_file_id() -> None:
    async def scenario() -> None:
        service = _FakeImageService()
        message = _EditingMessage()
        callback = _FakeCallback(message)

        await edit_poster(callback, service, _poster("img_y"), "cap", None)

        assert len(message.media_calls) == 1  # один edit_media — байтами
        assert service.file_ids["img_y"] == "EDITED_FILE_ID"

    asyncio.run(scenario())


def test_edit_poster_recreates_when_no_photo() -> None:
    async def scenario() -> None:
        service = _FakeImageService()
        message = _EditingMessage(no_photo=True)
        callback = _FakeCallback(message)

        await edit_poster(callback, service, _poster("img_z"), "cap", None)

        # Сообщение-текст заменено: старое удалено, постер отправлен заново
        assert message.deleted is True
        assert service.file_ids["img_z"] == "RESENT_FILE_ID"

    asyncio.run(scenario())


def test_edit_poster_uses_cached_file_id_first() -> None:
    async def scenario() -> None:
        service = _FakeImageService()
        service.store_file_id("img_w", "FID_CACHED")
        message = _EditingMessage()
        callback = _FakeCallback(message)

        await edit_poster(callback, service, _poster("img_w"), "cap", None)

        assert len(message.media_calls) == 1
        assert message.media_calls[0].media == "FID_CACHED"

    asyncio.run(scenario())


def test_day_caption_compact() -> None:
    caption = build_day_caption("Понедельник, 21.09", 3, "Иван · 5А")
    assert "Понедельник, 21.09" in caption
    assert "Иван · 5А" in caption
    assert "3" in caption
    assert len(caption) < 200

    empty = build_day_caption("Вторник, 22.09", 0, None)
    assert "Изменений" not in empty
