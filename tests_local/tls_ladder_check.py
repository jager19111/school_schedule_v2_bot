# tls_ladder_check.py
#
# Диагностика TLS-лестницы фетчера NIKA.
# Отвечает на вопрос: какой ступенью strict -> pin -> off
# lyceum.nstu.ru проходит ПРЯМО СЕЙЧАС.
#
# Запуск:
#   python tls_ladder_check.py                        # без пина: strict + отпечатки
#   python tls_ladder_check.py <sha256-отпечаток>     # с пином из твоего фетчера
#
# Отпечаток для сравнения лежит в core/nika/fetcher.py — константа
# с SHA-256, которую ты «прилепил» к лестнице. Формат любой:
# hex с двоеточиями или без.
#
# Второй отпечаток (SPKI) вычисляется через системный openssl,
# если он доступен — это правильная основа для долгоживущего пина
# (переживает обновление сертификата школой, см. комментарий ниже).

from __future__ import annotations

import hashlib
import shutil
import socket
import ssl
import subprocess
import sys

HOST = "lyceum.nstu.ru"
PORT = 443
PATH = "/rasp/schedule.html"


def try_strict() -> tuple[bool, str]:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((HOST, PORT), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST) as tls:
                cert = tls.getpeercert()
                subject = ", ".join(
                    f"{k}={v}" for part in cert.get("subject", []) for k, v in part
                )
                return True, subject
    except ssl.SSLCertVerificationError as exc:
        return False, str(exc)
    except (OSError, socket.timeout) as exc:
        return False, f"сетевая ошибка: {exc}"


def fetch_over_strict() -> str:
    import http.client

    ctx = ssl.create_default_context()
    try:
        conn = http.client.HTTPSConnection(HOST, PORT, context=ctx, timeout=15)
        conn.request("GET", PATH, headers={"User-Agent": "tls-ladder-check/1.0"})
        resp = conn.getresponse()
        body = resp.read(2048)
        conn.close()
        if resp.status == 200 and b"nika" in body.lower():
            return "OK"
        return f"странно: HTTP {resp.status}, первые байты не похожи на schedule.html"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL: {exc}"


def get_cert_unvalidated() -> tuple[bytes, dict]:
    """Забирает сертификат сервера без валидации — посмотреть, что там сейчас."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((HOST, PORT), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=HOST) as tls:
            return tls.getpeercert(binary_form=True), tls.getpeercert()


def spki_sha256(der: bytes) -> str | None:
    """SPKI-отпечаток (публичный ключ) — переживает обновление сертификата.

    Нужно для решения: на чём держать пин. Если openssl недоступен — None.
    """
    if shutil.which("openssl") is None:
        return None
    try:
        result = subprocess.run(
            ["openssl", "x509", "-pubkey", "-noout"],
            input=der,
            capture_output=True,
            check=True,
            timeout=15,
        )
        pubkey_pem = result.stdout
        spki_der = subprocess.run(
            ["openssl", "pkey", "-pubin", "-outform", "DER"],
            input=pubkey_pem,
            capture_output=True,
            check=True,
            timeout=15,
        ).stdout
        return hashlib.sha256(spki_der).hexdigest()
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    pinned = None
    if len(sys.argv) > 1:
        pinned = sys.argv[1].strip().lower().replace(":", "")
        if len(pinned) != 64 or any(c not in "0123456789abcdef" for c in pinned):
            print("Аргумент должен быть 64 hex-символа SHA-256.")
            raise SystemExit(1)

    print(f"=== Проверка TLS-лестницы для {HOST} ===\n")

    ok, info = try_strict()
    print(f"СТУПЕНЬ 1 (strict): {'ПРОЙДЕНА' if ok else 'НЕ ПРОЙДЕНА'} — {info}")

    der, cert = get_cert_unvalidated()
    cert_fp = hashlib.sha256(der).hexdigest()
    issuer = ", ".join(f"{k}={v}" for part in cert.get("issuer", []) for k, v in part)
    print(f"\nСертификат сервера сейчас:")
    print(f"  издатель:         {issuer}")
    print(f"  действителен до:  {cert.get('notAfter', '?')}")
    print(f"  SHA-256 (DER):    {cert_fp}")
    spki = spki_sha256(der)
    if spki:
        print(f"  SHA-256 (SPKI):   {spki}  <- переживёт обновление сертификата")

    pin_match = None
    if pinned:
        pin_match = pinned == cert_fp
        print(f"\nСТУПЕНЬ 2 (pin):    {'ПРОЙДЕНА — совпадает с твоим пином' if pin_match else 'НЕ ПРОЙДЕНА'}")
        if not pin_match:
            print(f"  твой пин:         {pinned}")
            print("  Сертификат обновился (или это MITM). Если после этого лестница")
            print("  уходит в `off` молча — проверка фактически отключена.")

    print()
    if ok:
        http_result = fetch_over_strict()
        print(f"HTTP GET через strict: {http_result}")
        print("\nВЫВОД: сайт проходит полную валидацию. Лестница живёт на ступени 1,")
        print("пин не задействован, `off` не достижим. Это лучший вариант.")
    elif pin_match:
        print("ВЫВОД: strict падает из-за недоверия к CA (системный стор не знает")
        print("издателя), но сервер подлинный — ступень pin делает реальную работу.")
        print("Это рабочее состояние, но проверь, откуда падает strict:")
        print("у тебя на Mac или на боевом сервере это может различаться.")
    else:
        print("ВЫВОД: strict падает И пин не сходится (или пин не передан).")
        print("Если фетчер после этого качает расписание через `off` — это активная")
        print("дыра: MITM между ботом и школой проходит незамеченным.")
        print("Правильное поведение: стоп, работа из кеша расписания, алерт админу.")


if __name__ == "__main__":
    main()
