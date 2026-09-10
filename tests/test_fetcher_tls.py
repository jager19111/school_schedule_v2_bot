# tests/test_fetcher_tls.py
#
# Интеграционный тест TLS-лестницы ScheduleFetcher на РЕАЛЬНОМ
# TLS-хендшейке: локальный HTTPS-сервер с самоподписанным
# сертификатом и прогон лестницы strict -> pin -> off.
#
# ГЛАВНЫЙ проверяемый дефект: except-кортеж фетчера. В aiohttp
# ClientConnectorCertificateError — БРАТ ClientConnectorSSLError
# (оба наследуют ClientSSLError): except ClientConnectorSSLError
# его НЕ ловит, и отказ валидации самоподписанного сертификата
# вылетает мимо лестницы — ступень pin становится мёртвым кодом.
#
# Тесты СИНХРОННЫЕ (asyncio.run внутри) — не зависят ни от
# pytest-asyncio, ни от его режима/скоупов фикстур.
#
# ВАЖНО: URL строго через 127.0.0.1, НЕ localhost — на macOS
# localhost резолвится и в ::1 (IPv6), сервер слушает только IPv4,
# и попытка соединения уходит в ConnectionRefused.
#
# Требования: pytest, aiohttp, openssl в PATH.
# Запуск: pytest tests/test_fetcher_tls.py -v

from __future__ import annotations

import asyncio
import hashlib
import ssl
import subprocess
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.client_exceptions import (
    ClientSSLError,
    ServerFingerprintMismatch,
)

from core.nika.fetcher import ScheduleFetcher

HOST = "127.0.0.1"  # явно IPv4 — см. комментарий в шапке
WRONG_PIN = "ab" * 32


class TlsTestCert:
    """Самоподписанный сертификат для локального HTTPS-сервера."""

    def __init__(self, workdir: Path, name: str):
        self.key = workdir / f"{name}.key"
        self.crt = workdir / f"{name}.crt"
        self.der = workdir / f"{name}.der"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048",
             "-keyout", str(self.key), "-out", str(self.crt),
             "-days", "2", "-nodes", "-subj", f"/CN={HOST}"],
            check=True, capture_output=True, timeout=30,
        )
        subprocess.run(
            ["openssl", "x509", "-in", str(self.crt),
             "-outform", "DER", "-out", str(self.der)],
            check=True, capture_output=True, timeout=30,
        )

    @property
    def fingerprint_hex(self) -> str:
        return hashlib.sha256(self.der.read_bytes()).hexdigest()


async def _start_https(cert: TlsTestCert):
    """HTTPS-сервер с сертификатом cert. Возвращает (runner, base_url)."""
    app = web.Application()

    async def handler(request):
        return web.Response(
            text='<script src="nika_data_TEST.js"></script>',
            content_type="text/html",
        )

    app.router.add_get("/rasp/schedule.html", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert.crt), str(cert.key))
    site = web.TCPSite(runner, HOST, 0, ssl_context=ctx)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"https://{HOST}:{port}/rasp"


def test_ladder_pin_saves_when_ca_rejects(tmp_path: Path) -> None:
    """CA не доверяет self-signed -> strict падает -> pin спасает.

    Если фетчер ловит только ClientConnectorSSLError, отказ валидации
    приходит как ClientConnectorCertificateError и вылетает мимо
    лестницы: probe() падает, тест красный. Это и есть диагноз.
    """
    cert = TlsTestCert(tmp_path, "school")

    async def scenario():
        runner, base_url = await _start_https(cert)
        try:
            async with aiohttp.ClientSession() as session:
                fetcher = ScheduleFetcher(
                    session=session,
                    base_url=base_url,
                    tls_fingerprint_sha256=cert.fingerprint_hex,
                )
                descriptor = await fetcher.probe()
                assert descriptor.js_filename == "nika_data_TEST.js"
                assert fetcher.ssl_degraded is False
        finally:
            await runner.cleanup()

    asyncio.run(scenario())


def test_ladder_wrong_pin_no_data_without_flag(tmp_path: Path) -> None:
    """Чужой пин: расписание НЕ принимается молча.

    - off удалена (fail-closed): probe() возбуждает TLS-исключение —
      данные с непроверенного соединения не приняты. Идеал.
    - off осталась: данные возвращаются, но только с ssl_degraded=True.
      Если данные пришли и без флага — немая дыра, тест красный.
    """
    cert = TlsTestCert(tmp_path, "school")

    async def scenario():
        runner, base_url = await _start_https(cert)
        try:
            async with aiohttp.ClientSession() as session:
                fetcher = ScheduleFetcher(
                    session=session,
                    base_url=base_url,
                    tls_fingerprint_sha256=WRONG_PIN,
                )
                try:
                    await fetcher.probe()
                except (ClientSSLError, ServerFingerprintMismatch):
                    return
                assert fetcher.ssl_degraded is True, (
                    "Расписание принято через off-ступень без TLS-проверки, "
                    "и соединение не помечено как degraded"
                )
        finally:
            await runner.cleanup()

    asyncio.run(scenario())


def test_network_errors_do_not_walk_ladder() -> None:
    """Сетевые ошибки не проваливают лестницу — пробрасываются сразу."""

    async def scenario():
        async with aiohttp.ClientSession() as session:
            fetcher = ScheduleFetcher(
                session=session,
                base_url="https://127.0.0.1:1",  # порт гарантированно закрыт
                tls_fingerprint_sha256=WRONG_PIN,
            )
            with pytest.raises(aiohttp.ClientConnectorError) as excinfo:
                await fetcher.probe()
            assert not isinstance(excinfo.value, ClientSSLError), (
                "Сетевая ошибка ошибочно классифицирована как TLS — "
                "лестница съедает инфраструктурный сбой"
            )

    asyncio.run(scenario())


def test_fingerprint_building(tmp_path: Path) -> None:
    """_build_fingerprint: openssl-формат, мусор, неполный hex, None."""
    cert = TlsTestCert(tmp_path, "fp")

    assert ScheduleFetcher._build_fingerprint(cert.fingerprint_hex[:-1]) is None

    with_colons = ":".join(
        cert.fingerprint_hex[i:i + 2] for i in range(0, 64, 2)
    )
    fp = ScheduleFetcher._build_fingerprint(with_colons)
    assert fp is not None
    assert fp.fingerprint == bytes.fromhex(cert.fingerprint_hex)

    assert ScheduleFetcher._build_fingerprint("не-hex-мусор!!") is None
    assert ScheduleFetcher._build_fingerprint(None) is None
    assert ScheduleFetcher._build_fingerprint("") is None


def test_ladder_construction(tmp_path: Path) -> None:
    """С пином: strict -> pin -> off. Без пина: strict -> off."""
    cert = TlsTestCert(tmp_path, "ladder")

    def modes_for(pin):
        async def scenario():
            async with aiohttp.ClientSession() as session:
                fetcher = ScheduleFetcher(
                    session=session,
                    base_url="https://placeholder.invalid",
                    tls_fingerprint_sha256=pin,
                )
                return [mode for mode, _ in fetcher._ssl_ladder]

        return asyncio.run(scenario())

    assert modes_for(cert.fingerprint_hex) == [
        ScheduleFetcher.SSL_MODE_STRICT,
        ScheduleFetcher.SSL_MODE_PIN,
        ScheduleFetcher.SSL_MODE_OFF,
    ]
    assert modes_for(None) == [
        ScheduleFetcher.SSL_MODE_STRICT,
        ScheduleFetcher.SSL_MODE_OFF,
    ]
