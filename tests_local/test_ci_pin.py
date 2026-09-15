#!/usr/bin/env python3
"""
Проверка certificate pinning БЕЗ запуска бота.

Прямой запрос к lyceum.nstu.ru с ssl=aiohttp.Fingerprint —
именно тот механизм, который использует ScheduleFetcher.

Запуск из venv проекта:
    python test_pin.py                # правильный отпечаток из константы
    python test_pin.py 0000...dead    # испорченный отпечаток (ожидается FAIL)

Ожидаемый результат:
    правильный отпечаток   -> PIN OK: HTTP 200
    испорченный отпечаток  -> PIN FAILED: ServerFingerprintMismatch
    сайт недоступен        -> PIN FAILED: <сетевая ошибка>

Если нужен прокси — впиши его в PROXY ниже (например,
"http://10.9.9.1:7897").
"""

import asyncio
import sys

import aiohttp

# Отпечаток сертификата lyceum.nstu.ru — тот же, что в .env
# (NIKA_TLS_FINGERPRINT_SHA256).
FINGERPRINT = (
    "1f5fec803419b94bb41a09cf519e0afd35445d57df0acfc3b572e84f6971d7e0"
)

URL = "https://lyceum.nstu.ru/rasp/schedule.html"

# Прокси: None, если запрос идёт напрямую.
PROXY = None


async def main() -> None:
    fingerprint_hex = (
        sys.argv[1]
        if len(sys.argv) > 1
        else FINGERPRINT
    ).strip().replace(":", "").lower()

    if len(fingerprint_hex) != 64:
        print(f"Некорректный отпечаток (длина {len(fingerprint_hex)}, нужно 64 hex-символа)")
        return

    fingerprint = aiohttp.Fingerprint(bytes.fromhex(fingerprint_hex))
    print(f"Проверяю пин: {fingerprint_hex[:16]}...")
    print(f"URL: {URL}\n")

    timeout = aiohttp.ClientTimeout(total=15, connect=5)
    session = aiohttp.ClientSession(timeout=timeout)
    try:
        async with session.get(
            URL,
            ssl=fingerprint,
            proxy=PROXY,
        ) as response:
            body_size = len(await response.text())
            print(f"PIN OK: HTTP {response.status}, получено {body_size} байт")
            print("Сертификат совпадает с отпечатком — пин работает.")
    except Exception as exc:
        print(f"PIN FAILED: {type(exc).__name__}: {exc}")
        if "FingerprintMismatch" in type(exc).__name__:
            print("Сертификат НЕ совпадает с отпечатком — пин работает (это ожидаемо для испорченного).")
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
