# tests/web/test_tg_app_regression.py
#
# Регрессионные тесты реального web-приложения (create_web_app):
#
# 1. consume обязан ставить Set-Cookie на возвращаемом RedirectResponse
#    (баг 07.10: Set-Cookie на инжектированном response терялся).
# 2. Любой HTMX-запрос с 401 -> 200 + HX-Redirect /auth
#    (баг: PWA 'замерзала' до ручной перезагрузки).
# 3. Гейты регистрации: не допускают создание сессий, если 
#    профиль не полностью зарегистрирован.
#
# В отличие от web_test_app (изолированные роутеры), здесь собирается
# НАСТОЯЩЕЕ приложение: реальный exception handler, реальные
# маршруты /tg/*, реальный middleware-стек.


from __future__ import annotations

import hmac
import hashlib
import time
from typing import Iterator
from urllib.parse import urlencode
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.browser_handoff_service import HandoffPayload
from services.web_sessions_service import WebSessionContext
from services.telegram_webauth_service import TelegramWebAuthService
from services.time_service import TimeService, TimeServiceConfig
from web.app import WebSettings, create_web_app
from web.deps import get_session_context

RAW_SESSION_TOKEN = "test-raw-session-token"
BOT_TOKEN = "test-bot-token:123456"


# --- Хелперы для эмуляции подписи Telegram ---

def valid_params() -> dict:
    """Генерирует свежие параметры для обхода проверки expiration."""
    return {
        "user": '{"id": 1001, "first_name": "Test"}',
        "auth_date": str(int(time.time())),
    }

def sign_init_data(params: dict) -> str:
    """Подписывает параметры так же, как это делает Telegram."""
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    hash_sign = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    final_params = params.copy()
    final_params["hash"] = hash_sign
    return urlencode(final_params)


# --- Фейковые зависимости ---

class FakeProfileService:
    def __init__(self, *, is_fully_registered: bool = True) -> None:
        self._registered = is_fully_registered

    async def get_user_profile_dto(self, user_id: int):
        return SimpleNamespace(is_fully_registered=self._registered)


class FakeHandoffService:
    """In-memory fake: 'expired-code' -> None, остальное валидно."""

    def __init__(self) -> None:
        self.consume_calls: list[str] = []

    async def consume_handoff(self, raw_code: str):
        self.consume_calls.append(raw_code)
        if raw_code == "expired-code":
            return None
        return HandoffPayload(user_id=1001, target_path="/")


class FakeSessionsService:
    """Воспроизводит контракт create_session / resolve_session."""

    def __init__(self) -> None:
        self.create_calls: list[dict] = []

    async def create_session(
        self,
        *,
        user_id: int,
        user_agent: str | None = None,
        surface: str = "browser",
    ):
        self.create_calls.append(
            {
                "user_id": user_id,
                "user_agent": user_agent,
                "surface": surface,
            }
        )
        return RAW_SESSION_TOKEN, WebSessionContext(
            session_id=42,
            session_hash="regression-test-hash",
            user_id=user_id,
            csrf_token="regression-csrf",
            surface=surface,
        )

    async def resolve_session(self, raw_token: str):
        if raw_token == RAW_SESSION_TOKEN:
            return WebSessionContext(
                session_id=42,
                session_hash="regression-test-hash",
                user_id=1001,
                csrf_token="regression-csrf",
                surface="browser",
            )
        return None


def _build_app(
    handoff: FakeHandoffService,
    sessions: FakeSessionsService,
    profile: FakeProfileService | None = None,
    webauth: TelegramWebAuthService | None = None,
) -> FastAPI:
    if profile is None:
        profile = FakeProfileService(is_fully_registered=True)
        
    async def db_liveness() -> bool:
        return True

    return create_web_app(
        web_settings=WebSettings(
            public_url="http://testserver",
            allowed_hosts=["testserver"],
            gateway_key=None,
            cookie_secure=False,
        ),
        sessions_service=sessions,
        telegram_webauth_service=webauth,
        browser_handoff_service=handoff,
        profile_service=profile,
        schedule_service=None,
        students_service=None,
        schedule_targets_service=None,
        watch_targets_service=None,
        extra_classes_web_service=None,
        time_service=None,
        db_liveness=db_liveness,
    )


@pytest.fixture
def handoff_service() -> FakeHandoffService:
    return FakeHandoffService()


@pytest.fixture
def fake_sessions() -> FakeSessionsService:
    return FakeSessionsService()


@pytest.fixture
def regression_client(
    handoff_service: FakeHandoffService,
    fake_sessions: FakeSessionsService,
) -> Iterator[TestClient]:
    app = _build_app(handoff_service, fake_sessions)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def expired_session_client() -> Iterator[TestClient]:
    """Пользователь с отозванной/истёкшей сессией."""
    app = _build_app(FakeHandoffService(), FakeSessionsService())

    async def expired_session():
        raise HTTPException(
            status_code=401,
            detail="Сессия недействительна.",
        )

    app.dependency_overrides[get_session_context] = expired_session
    with TestClient(app) as client:
        yield client


# --- Регрессия 1: Set-Cookie на RedirectResponse из consume ---

def test_consume_sets_cookie_on_redirect(
    regression_client: TestClient,
    fake_sessions: FakeSessionsService,
) -> None:
    response = regression_client.get(
        "/tg/browser/consume?code=valid-code",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"

    cookie_header = response.headers["set-cookie"]
    assert "web_session=" in cookie_header
    assert "httponly" in cookie_header.lower()

    assert len(fake_sessions.create_calls) == 1
    assert fake_sessions.create_calls[0]["surface"] == "browser"


def test_consume_reuses_existing_browser_session(
    regression_client: TestClient,
    handoff_service: FakeHandoffService,
    fake_sessions: FakeSessionsService,
) -> None:
    """Повторное нажатие скрепки: код не расходуется, сессия не создаётся."""
    first = regression_client.get(
        "/tg/browser/consume?code=first",
        follow_redirects=False,
    )
    assert first.status_code == 303

    # Cookie сохранён клиентом; второй consume должен уйти в reuse.
    second = regression_client.get(
        "/tg/browser/consume?code=second",
        follow_redirects=False,
    )

    assert second.status_code == 303
    assert second.headers["location"] == "/"
    assert len(handoff_service.consume_calls) == 1
    assert len(fake_sessions.create_calls) == 1


def test_consume_invalid_code_returns_410(
    regression_client: TestClient,
) -> None:
    response = regression_client.get(
        "/tg/browser/consume?code=expired-code",
        follow_redirects=False,
    )

    assert response.status_code == 410
    assert "недействительна" in response.text.lower()


# --- Регрессия 2: HTMX 401 -> HX-Redirect ---

def test_htmx_401_returns_hx_redirect(
    expired_session_client: TestClient,
) -> None:
    response = expired_session_client.get(
        "/school",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert response.headers["hx-redirect"] == "/auth"


def test_page_401_redirects_to_auth(
    expired_session_client: TestClient,
) -> None:
    """Обычная (не HTMX) навигация: 303 на /auth."""
    response = expired_session_client.get(
        "/school",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/auth"


# --- Новые тесты (Гейты регистрации) ---

def test_consume_rejects_unregistered_profile(
    handoff_service: FakeHandoffService,
    fake_sessions: FakeSessionsService,
):
    app = _build_app(
        handoff_service,
        fake_sessions,
        FakeProfileService(is_fully_registered=False),
    )
    with TestClient(app) as client:
        response = client.get(
            "/tg/browser/consume?code=valid-code",
            follow_redirects=False,
        )
        assert response.status_code == 403


def test_bootstrap_rejects_unregistered_profile(
    handoff_service: FakeHandoffService,
    fake_sessions: FakeSessionsService,
):
    """Гейт до создания telegram-сессии."""
    webauth = TelegramWebAuthService(
        TimeService(TimeServiceConfig(timezone="UTC")),
        bot_token=BOT_TOKEN,
    )
    init_data = sign_init_data(valid_params())
    
    app = _build_app(
        handoff_service,
        fake_sessions,
        FakeProfileService(is_fully_registered=False),
        webauth=webauth,
    )
    
    with TestClient(app) as client:
        response = client.post(
            "/tg/bootstrap",
            json={"initData": init_data},
        )
        
        assert response.status_code == 403
        assert "регистрац" in response.json()["detail"].lower()