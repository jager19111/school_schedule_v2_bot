# web/security.py
#
# Security-средний слой web-приложения:
# - GatewayKeyMiddleware: X-Web-Gateway-Key (доверие к gateway, НЕ identity);
# - SecurityHeadersMiddleware: строгий CSP + private, no-store;
# - RateLimitMiddleware: in-process token bucket (один процесс = in-memory
#   корректен; заменяем на shared-реализацию при переходе к multi-worker);
# - CSRFMiddleware: session + X-CSRF-Token + same-origin для mutations;
# - CORS НЕ включаем (один origin; ТЗ 5.5).
#
# Никакие secrets (gateway key, csrf, cookie) не логируются.

from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "manifest-src 'self'; "
    "worker-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)

# Персональные данные никогда не попадают в shared/public cache.
_STATIC_PREFIXES = ("/static/",)


class GatewayKeyMiddleware(BaseHTTPMiddleware):
    """
    X-Web-Gateway-Key подтверждает, что запрос пришёл через доверенный
    Nginx. Nginx обязан ПЕРЕЗАПИСЫВАТЬ входящий пользовательский
    заголовок (proxy_set_header X-Web-Gateway-Key $web_gateway_key),
    а не прокидывать $http_x_web_gateway_key.

    Ключ НЕ определяет пользователя. Если ключ не задан в конфиге —
    режим локальной разработки (один warning при старте).
    """

    def __init__(self, app, gateway_key: Optional[str]) -> None:
        super().__init__(app)
        self._gateway_key = gateway_key
        if not gateway_key:
            logger.warning(
                "WEB_GATEWAY_KEY не задан: gateway-проверка отключена "
                "(только для локальной разработки!)"
            )

    async def dispatch(self, request: Request, call_next):
        if self._gateway_key:
            provided = request.headers.get("X-Web-Gateway-Key", "")
            if provided != self._gateway_key:
                return JSONResponse(
                    {"detail": "Доступ запрещён."}, status_code=403
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """CSP и базовые security-заголовки + cache-политика."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith(_STATIC_PREFIXES):
            # Персональные HTML/JSON responses не кэшируются.
            response.headers["Cache-Control"] = "private, no-store"
        return response


class _TokenBucket:
    """Классический token bucket (rate — токенов/сек, burst — стартовый запас)."""

    __slots__ = ("rate", "burst", "tokens", "updated")

    def __init__(self, rate: float, burst: int) -> None:
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.updated = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(
            float(self.burst),
            self.tokens + (now - self.updated) * self.rate,
        )
        self.updated = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Политики (решение Phase 0):
    - /api/v1/auth/exchange — строгий per-IP;
    - POST/PUT/PATCH/DELETE (mutations) — умеренный per-IP;
    - прочие GET — обычный per-IP;
    - /api/v1/schedule/stream (SSE, Phase 7) — НЕ ограничивается
      request-per-second bucket'ом: отдельная политика
      (connection establishment rate; max active connections будет
      в SSE ConnectionManager).
    """

    SSE_PREFIX = "/api/v1/schedule/stream"

    POLICIES = {
        "exchange": (0.2, 10),        # ~12/мин, burst 10
        "mutation": (1.0, 60),        # 60/мин
        "get": (5.0, 300),            # 300/мин
        "sse_establish": (0.1, 10),   # только установка соединения
    }

    def __init__(self, app) -> None:
        super().__init__(app)
        self._buckets: Dict[Tuple[str, str], _TokenBucket] = {}

    def _client_ip(self, request: Request) -> str:
        # uvicorn(proxy_headers=True + forwarded_allow_ips) уже кладёт
        # реальный клиентский IP в request.client.host.
        return request.client.host if request.client else "unknown"

    def _bucket(self, key: Tuple[str, str], policy: str) -> _TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            rate, burst = self.POLICIES[policy]
            bucket = _TokenBucket(rate, burst)
            self._buckets[key] = bucket
        return bucket

    def _classify(self, request: Request) -> str:
        path = request.url.path
        if path == "/api/v1/auth/exchange":
            return "exchange"
        if path.startswith(self.SSE_PREFIX):
            return "sse_establish"
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            return "mutation"
        return "get"

    async def dispatch(self, request: Request, call_next):
        policy = self._classify(request)
        ip = self._client_ip(request)
        if not self._bucket((policy, ip), policy).allow():
            return JSONResponse(
                {"detail": "Слишком много запросов. Повторите позже."},
                status_code=429,
            )
        return await call_next(request)


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Все cookie-authenticated state-changing requests (POST/PUT/PATCH/DELETE)
    требуют валидный X-CSRF-Token + same-origin.

    /api/v1/auth/exchange исключён: сессии ещё нет (защиту обеспечивает
    сам одноразовый login token с TTL 5 минут). Health-эндпоинты — GET.
    """

    EXEMPT_PATHS = frozenset({"/api/v1/auth/exchange"})
    MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    def __init__(self, app, sessions_service) -> None:
        super().__init__(app)
        self._sessions = sessions_service

    def _same_origin(self, request: Request) -> bool:
        """Origin/Referer, если присутствуют, обязаны совпадать с host."""
        host = request.headers.get("host", "")
        for header in ("origin", "referer"):
            value = request.headers.get(header)
            if value:
                return urlparse(value).netloc == host
        # Нет Origin/Referer (браузеры шлют их для POST/form) —
        # полагаемся на CSRF-токен + SameSite=Lax cookie.
        return True

    async def dispatch(self, request: Request, call_next):
        if request.method not in self.MUTATING:
            return await call_next(request)
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        cookie_token = request.cookies.get("web_session")
        if not cookie_token:
            # Мутации без сессии получат 401 в auth-dependency.
            return await call_next(request)

        context = await self._sessions.resolve_session(cookie_token)
        if context is None:
            return await call_next(request)  # 401 поставит auth-dependency

        provided = request.headers.get("X-CSRF-Token", "")
        if not self._sessions.verify_csrf(
            session_hash=context.session_hash, provided_token=provided
        ):
            return JSONResponse(
                {"detail": "Недействительный CSRF-токен."}, status_code=403
            )
        if not self._same_origin(request):
            return JSONResponse(
                {"detail": "Недопустимый источник запроса."}, status_code=403
            )
        return await call_next(request)
