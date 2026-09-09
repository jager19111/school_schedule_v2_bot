# core/nika/fetcher.py
#
# ЭТАП 2. СЕТЕВОЙ СЛОЙ.
#
# ИЗМЕНЕНИЯ:
#
# 1. (Задача 2.1) Персистентная aiohttp-сессия.
#    Раньше probe() и fetch_js_content() создавали ClientSession на каждый
#    вызов: probe() выполняется каждые NIKA_REFRESH_INTERVAL_MINUTES,
#    то есть каждые 5 минут поднимался новый TCP+TLS-сокет (а при
#    включённом прокси — ещё и CONNECT), затем закрывался. Keep-alive
#    не работал. Теперь сессия создаётся ОДИН раз в main.py, живёт весь
#    жизненный цикл процесса и передаётся сюда через конструктор.
#    Методы НЕ закрывают сессию — она общая.
#
# 2. (Задача 2.1, уточнение) Таймауты — per-request, а не session-level.
#    У probe и JS-загрузки разные бюджеты времени (15с vs 30с):
#    session-таймаут остаётся безопасным дефолтом, а каждый метод
#    переопределяет его своим ClientTimeout через параметр timeout=
#    вызова session.get(). Иначе JS-файл ~150КБ на медленном прокси
#    обрезался бы на 15 секунде.
#
# 3. (Задача 2.2) Удалён устаревший fetch() (Compatibility wrapper):
#    дублировал двухэтапную загрузку и не использовался нигде
#    (refresh_if_changed работает через probe + fetch_js_content).
#
# 4. Fail-fast валидация сессии в конструкторе: закрытая/отсутствующая
#    сессия — ошибка старта, а не RuntimeError посреди ночного тика.
#
# НЕ ИЗМЕНИЛОСЬ: headers, ssl=False (обход проблемы с сертификатом
# lyceum.nstu.ru), логика разбора schedule.html, sha256-хеши,
# _extract_json_from_js.

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict
from urllib.parse import urljoin

import aiohttp

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NikaSourceDescriptor:
    """
    Лёгкое описание опубликованной версии NIKA.

    JS ещё не скачан: descriptor получается только из schedule.html.
    """
    js_filename: str
    js_url: str


class ScheduleFetcher:
    """
    Загрузка расписания NIKA в два этапа.

    1. probe() загружает только schedule.html и находит актуальный JS.
    2. fetch_js_content() скачивает JS только при новой revision.

    Оба метода работают через ОБЩУЮ персистентную сессию,
    переданную из main.py. Сессия здесь не создаётся и не закрывается.
    """

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        base_url: str = "https://lyceum.nstu.ru/rasp",
        proxy: str | None = None,
    ) -> None:
        # Fail-fast: проблема с сессией должна всплыть при старте,
        # а не в первом же ночном тике планировщика.
        if session is None:
            raise ValueError(
                "ScheduleFetcher требует открытую aiohttp.ClientSession "
                "(создаётся в main.py, Задача 2.1)."
            )
        if session.closed:
            raise ValueError(
                "ScheduleFetcher получил уже закрытую aiohttp.ClientSession."
            )

        self.session = session
        self.base_url = base_url.rstrip("/")
        self.proxy = proxy

        # Передаём per-request: сессия общая, навешивать на неё
        # заголовки одного конкретного клиента было бы неправильно.
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "SchoolScheduleBot/2.0"
            )
        }

    @staticmethod
    def _html_timeout() -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(
            total=15,
            connect=5,
            sock_read=10,
        )

    @staticmethod
    def _js_timeout() -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(
            total=30,
            connect=5,
            sock_read=25,
        )

    async def probe(self) -> NikaSourceDescriptor:
        """
        Загружает только schedule.html и находит текущий nika_data_*.js.

        Это дешёвая операция, которую можно выполнять часто.
        Соединение переиспользуется из общего keep-alive пула сессии.
        """
        schedule_url = f"{self.base_url}/schedule.html"

        async with self.session.get(
            schedule_url,
            proxy=self.proxy,
            ssl=False,
            headers=self.headers,
            timeout=self._html_timeout(),
        ) as response:
            response.raise_for_status()

            html = await response.text()

        match = re.search(
            r"""src=["']([^"']*nika_data_[^"']+\.js)["']""",
            html,
        )

        if not match:
            raise ValueError(
                "Не найден актуальный nika_data_*.js "
                "в schedule.html"
            )

        raw_path = match.group(1)

        return NikaSourceDescriptor(
            js_filename=raw_path.rsplit("/", 1)[-1],
            js_url=urljoin(
                f"{self.base_url}/",
                raw_path,
            ),
        )

    async def fetch_js_content(
        self,
        source: NikaSourceDescriptor,
    ) -> str:
        """
        Скачивает уже найденный NIKA JS.

        Должен вызываться только если filename изменился либо отсутствует
        локальный raw cache.
        """
        async with self.session.get(
            source.js_url,
            proxy=self.proxy,
            ssl=False,
            headers=self.headers,
            timeout=self._js_timeout(),
        ) as response:
            response.raise_for_status()

            return await response.text(
                encoding="utf-8",
            )

    @staticmethod
    def calculate_raw_sha256(content: str) -> str:
        """SHA-256 точного JS-файла."""
        return hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def calculate_semantic_sha256(
        nika_data: Dict[str, Any],
    ) -> str:
        """
        SHA-256 данных NIKA без export metadata.

        EXPORT_DATE и EXPORT_TIME не считаются изменением расписания.
        """
        semantic_data = copy.deepcopy(nika_data)

        semantic_data.pop("EXPORT_DATE", None)
        semantic_data.pop("EXPORT_TIME", None)

        canonical_json = json.dumps(
            semantic_data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            canonical_json.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _extract_json_from_js(
        js_content: str,
    ) -> Dict[str, Any]:
        """
        Извлекает JSON из JS-конструкции var NIKA = {...}.
        """
        start_idx = js_content.find("var NIKA=")

        if start_idx == -1:
            start_idx = js_content.find("var NIKA =")

        if start_idx == -1:
            raise ValueError(
                "Глобальная переменная NIKA не найдена в JS"
            )

        json_start = js_content.find("{", start_idx)

        if json_start == -1:
            raise ValueError(
                "Не найдено начало JSON-объекта NIKA"
            )

        bracket_count = 0
        json_end = -1

        for index in range(json_start, len(js_content)):
            char = js_content[index]

            if char == "{":
                bracket_count += 1

            elif char == "}":
                bracket_count -= 1

                if bracket_count == 0:
                    json_end = index + 1
                    break

        if json_end == -1:
            raise ValueError(
                "Не найден конец JSON-объекта NIKA"
            )

        raw_json = js_content[json_start:json_end]

        try:
            return json.loads(raw_json)

        except json.JSONDecodeError as exc:
            logger.error(
                "NIKA JSON decode failed: %s",
                exc,
            )
            raise
