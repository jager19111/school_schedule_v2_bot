import hashlib
import hmac
import json
import time

from services.telegram_webauth_service import TelegramWebAuthService
from services.time_service import TimeService, TimeServiceConfig

BOT_TOKEN = "123456:test-token-for-unit-tests"
NOW = int(time.time())


def make_service() -> TelegramWebAuthService:
    return TelegramWebAuthService(
        TimeService(TimeServiceConfig(timezone="UTC")),
        bot_token=BOT_TOKEN,
    )


def sign(params: dict) -> str:
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    valid_hash = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    payload = dict(params)
    payload["hash"] = valid_hash
    from urllib.parse import urlencode
    return urlencode(payload)


def valid_params(auth_date: int = NOW) -> dict:
    return {
        "auth_date": str(auth_date),
        "query_id": "AAF1AAQAAAAAxAAAAA",
        "user": json.dumps({"id": 294267689, "first_name": "Roman"}),
    }


def test_valid_init_data_returns_identity():
    identity = make_service().validate_init_data(sign(valid_params()))
    assert identity is not None
    assert identity.user_id == 294267689


def test_tampered_signature_rejected():
    raw = sign(valid_params()).replace("Roman", "Hacker")
    assert make_service().validate_init_data(raw) is None


def test_wrong_bot_token_rejected():
    raw = sign(valid_params())
    other = TelegramWebAuthService(
        TimeService(TimeServiceConfig(timezone="UTC")),
        bot_token="999999:other-bot",
    )
    assert other.validate_init_data(raw) is None


def test_stale_auth_date_rejected():
    identity = make_service().validate_init_data(
        sign(valid_params(auth_date=NOW - 30 * 24 * 3600))
    )
    assert identity is None


def test_missing_user_rejected():
    params = valid_params()
    params.pop("user")
    assert make_service().validate_init_data(sign(params)) is None


def test_garbage_rejected():
    assert make_service().validate_init_data("not-an-init-data") is None