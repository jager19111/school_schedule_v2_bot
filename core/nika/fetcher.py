# core/nika/fetcher.py
#
# ЭТАП 2. СЕТЕВОЙ СЛОЙ.
#
# ЧТО РЕАЛИЗОВАНО:
#
# 1. (Задача 2.1) Персистентная aiohttp-сессия из main.py:
#    probe() и fetch_js_content() не создают и не закрывают сессии,
#    keep-alive соединение живёт в общем пуле весь цикл бота.
#    Таймауты — per-request (15с probe / 30с JS), session-таймаут
#    в main.py остаётся безопасным дефолтом.
#
# 2. (Задача 2.2) Устаревший fetch() (Compatibility wrapper) удалён.
#
# 3. НОВОЕ: TLS-лестница strict -> pin -> off.
#
#    Проблема "ssl=True, а на фолбеке ssl=False": чистый фолбек на
#    незащищённое соединение — это security-даунгрейд: MITM-атака с
#    подменённым сертификатом неотличима от "протухшего" сертификата,
#    и бот сам бы переключался на незащищённый канал.
#
#    Решение — три уровня, каждый запрос начинает с САМОГО строгого:
#
#    strict: ssl=True — обычная CA-верификация. Работает, если
#            сертификат школы подписан доверенным CA (Let's Encrypt
#            и т.п.) и не просрочен.
#    pin:    ssl=aiohttp.Fingerprint(...) — certificate pinning:
#            сверяется SHA256 фактического DER-сертификата сервера с
#            NIKA_TLS_FINGERPRINT_SHA256. Работает для самоподписанных
#            сертификатов и защищает от подмены ЛЮБЫМ другим
#            сертификатом, включая валидный CA-сертификат атакующего.
#    off:    ssl=False — последний рубеж, только если не прошли ни
#            CA-верификацию, ни пин (сертификат школы сменился).
#            ВАЖНО: сопровождается ГРОМКИМ warning в лог и означает,
#            что NIKA_TLS_FINGERPRINT_SHA256 пора обновить.
#
#    Свойства лестницы:
#    - каждый запрос стартует со strict: когда школа починит/обновит
#      сертификат, бот сам вернётся к полной верификации (self-healing).
#      Цена — одна неудачная TLS-попытка (~сотни мс) раз в
#      NIKA_REFRESH_INTERVAL_MINUTES, пока сертификат невалиден;
#    - продвигают лестницу ТОЛЬКО SSL-ошибки (ClientConnectorSSLError,
#      ServerFingerprintMismatch). Сетевые ошибки — падение прокси,
#      обрыв соединения — пробрасываются немедленно (проверено
#      экспериментально на aiohttp 3.13: ClientProxyConnectionError
#      лестницей не ловится);
#    - соединение не переиспользуется между режимами: пул aiohttp
#      ключуется по ssl-контексту.
#
#    Смена сертификата школой: pin не совпал -> WARNING с инструкцией
#    обновить NIKA_TLS_FINGERPRINT_SHA256 -> работа продолжается на
#    off до обновления константы.
#
#    Обновить отпечаток:
#      openssl s_client -connect lyceum.nstu.ru:443 -servername \
#        lyceum.nstu.ru </dev/null 2>/dev/null \
#        | openssl x509 -noout -fingerprint -sha256

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple
from urllib.parse import urljoin

import aiohttp
from aiohttp.client_exceptions import ServerFingerprintMismatch

logger = logging.getLogger(__name__)

# SHA256-отпечаток сертификата lyceum.nstu.ru (sha256 DER-сертификата,
# формат openssl x509 -fingerprint -sha256). Обновлять при ротации
# сертификата школы — см. предупреждение в логе и команду выше.



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
    переданную из main.py, и TLS-лестницу strict -> pin -> off.
    """

    SSL_MODE_STRICT = "strict"
    SSL_MODE_PIN = "pin"
    SSL_MODE_OFF = "off"

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        base_url: str = "https://lyceum.nstu.ru/rasp",
        proxy: str | None = None,
        tls_fingerprint_sha256: str | None = None, # <-- НОВОЕ
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

        # Пин: hex-строка из openssl -> сырые байты дайджеста.
        # aiohttp.Fingerprint принимает ТОЛЬКО сырые байты (32 байта =
        # sha256); hex-строка отвергается с "fingerprint has invalid
        # length" (проверено на aiohttp 3.13.3).

        self._ssl_fingerprint = self._build_fingerprint(tls_fingerprint_sha256)

        # Лестница SSL-режимов от строгого к слабому.
        self._ssl_ladder: List[Tuple[str, Any]] = [
            (self.SSL_MODE_STRICT, True),
        ]
        if self._ssl_fingerprint is not None:
            self._ssl_ladder.append(
                (self.SSL_MODE_PIN, self._ssl_fingerprint),
            )
        self._ssl_ladder.append(
            (self.SSL_MODE_OFF, False),
        )
#         # Состояние TLS-деградации для админ-алертов:
#         # True = последний успешный fetch шёл в обход проверки.
        self._ssl_degraded = False
        # Заголовки per-request: сессия общая, навешивать на неё
        # заголовки одного конкретного клиента было бы неправильно.
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "SchoolScheduleBot/2.0"
            )
        }
        ladder_repr = " -> ".join(
            mode_name
            for mode_name, _ in self._ssl_ladder
        )
        logger.info(
            "NIKA TLS ladder armed: %s "
            "(fingerprint pin: %s)",
            ladder_repr,
            (
                "enabled"
                if self._ssl_fingerprint is not None
                else "disabled"
            ),
        )

    @property
    def ssl_degraded(self) -> bool:
        """
        True, если последний успешный fetch шёл в обход TLS-проверки.

        Снимается автоматически при первом успехе в strict/pin —
        когда школа починит сертификат или админ обновит отпечаток.
        """
        return self._ssl_degraded
    
    @staticmethod
    def _build_fingerprint(
        hex_digest: Optional[str],
    ) -> Optional[aiohttp.Fingerprint]:
        """
        Строит aiohttp.Fingerprint из hex-строки отпечатка.

        None/пустая строка — пин отключён (лестница strict -> off).
        Битовая строка логируется, пин отключается, бот не падает.
        """
        if not hex_digest:
            return None

        normalized = (
            hex_digest.strip()
            .replace(":", "")
            .replace(" ", "")
            .lower()
        )
        try:
            return aiohttp.Fingerprint(bytes.fromhex(normalized))
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Invalid TLS fingerprint %r: %s. "
                "Certificate pinning disabled.",
                hex_digest,
                exc,
            )
            return None

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

    async def _get_text(
        self,
        url: str,
        *,
        timeout: aiohttp.ClientTimeout,
        encoding: Optional[str] = None,
    ) -> str:
        """
        GET с TLS-лестницей strict -> pin -> off.

        Каждый запрос начинается со strict — самовосстановление при
        починке сертификата. Продвижение вниз — только по SSL-ошибкам
        (CA-верификация не прошла / пин не совпал); сетевые ошибки
        (прокси недоступен и т.п.) пробрасываются немедленно.
        """
        last_index = len(self._ssl_ladder) - 1

        for index, (mode_name, ssl_arg) in enumerate(self._ssl_ladder):
            try:
                async with self.session.get(
                    url,
                    proxy=self.proxy,
                    ssl=ssl_arg,
                    headers=self.headers,
                    timeout=timeout,
                ) as response:
                    response.raise_for_status()
                    if mode_name != self.SSL_MODE_OFF:
                        # Успех в защищённом режиме снимает флаг
                        # деградации (сертификат починили/обновили пин).
                        self._ssl_degraded = False
                    if encoding is not None:
                        return await response.text(encoding=encoding)
                    return await response.text()

            except (
                aiohttp.ClientConnectorSSLError,
                ServerFingerprintMismatch,
            ) as exc:
                if index == last_index:
                    raise

                next_mode_name = self._ssl_ladder[index + 1][0]

                if next_mode_name == self.SSL_MODE_PIN:
                    # Роутинная ситуация, если школа использует
                    # самоподписанный сертификат: CA-проверка не
                    # проходит, но пин подтверждает подлинность.
                    logger.info(
                        "CA verification failed (%s). "
                        "Retrying with pinned certificate.",
                        exc,
                    )
                    #
                else:
                    # Деградация: дальше работаем без TLS-проверки.
                    self._ssl_degraded = True

                    # Попали в off: не прошли ни CA, ни пин.
                    # Либо школа сменила сертификат (обнови
                    # NIKA_TLS_FINGERPRINT_SHA256), либо это
                    # потенциальный MITM — внимание обязательно.
                    logger.warning(
                        "TLS verification FAILED on strict mode (%s). "
                        "Certificate does not match pin. "
                        "Falling back to UNVERIFIED connection (ssl=False): "
                        "MITM-защита отключена. "
                        "Скорее всего школа сменила сертификат — обновите "
                        "NIKA_TLS_FINGERPRINT_SHA256 в .env.",
                        exc,
                    )
                continue

        # Недостижимо: цикл либо вернёт текст, либо пробросит исключение.
        raise RuntimeError("SSL ladder exhausted without result")  # pragma: no cover

    async def probe(self) -> NikaSourceDescriptor:
        """
        Загружает только schedule.html и находит текущий nika_data_*.js.

        Это дешёвая операция, которую можно выполнять часто.
        Соединение переиспользуется из общего keep-alive пула сессии.
        """
        schedule_url = f"{self.base_url}/schedule.html"

        html = await self._get_text(
            schedule_url,
            timeout=self._html_timeout(),
        )

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
        return await self._get_text(
            source.js_url,
            timeout=self._js_timeout(),
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
        nika_data: dict,
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
    ) -> dict:
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
