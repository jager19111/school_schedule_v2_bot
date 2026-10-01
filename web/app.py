# web/app.py
#
# Фабрика FastAPI-приложения (Phase 1-7).
#
# Web — interface layer над существующими сервисами (ТЗ 2):
#   Web UI -> FastAPI Web Layer -> Existing Services -> Repositories -> SQLite
# Здесь нет бизнес-логики и SQL; только transport, auth/session handling,
# security-политики, web-схемы, шаблоны и SSE-инфраструктура.
#
# Middleware-порядок (внешний -> внутренний):
#   TrustedHost -> GatewayKey -> SecurityHeaders -> RateLimit -> CSRF -> routes
# CORS глобально НЕ включаем (один origin, ТЗ 5.5).

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi import Request

from services.extra_classes_web_service import ExtraClassesWebService
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.schedule_targets_service import ScheduleTargetsService
from services.students_service import StudentsService
from services.time_service import TimeService
from services.web_sessions_service import WebSessionsService
from services.watch_targets_service import WatchTargetsService
from web.events import ApplicationEventBus
from web.idempotency import IdempotencyStore
from web.mappers import prev_next_dates
from web.security import (
    CSRFMiddleware,
    GatewayKeyMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from web.sse import SSEConnectionManager

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class WebSettings:
    """
    Вся web-конфигурация (никаких хардкодов адресов и secrets).

    Заполняется в main.py из config.py / env:
      WEB_PUBLIC_URL, WEB_HOST, WEB_PORT, WEB_TRUSTED_PROXY_IPS,
      WEB_GATEWAY_KEY, WEB_CSRF_SECRET, WEB_ACCESS_MODE,
      WEB_ALLOWED_FAMILY_IDS, WEB_COOKIE_SECURE.
    """

    public_url: str
    allowed_hosts: List[str]
    gateway_key: Optional[str]
    access_mode: str = "family_allowlist"           # family_allowlist | public
    allowed_family_ids: frozenset = field(default_factory=frozenset)
    cookie_secure: bool = True                      # False только для локальной разработки
    session_cookie_max_age: int = 365 * 24 * 3600   # absolute lifetime (365 дней)
    bot_username: Optional[str] = None              # deep-link приглашений


def create_web_app(
    *,
    web_settings: WebSettings,
    sessions_service: WebSessionsService,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    schedule_targets_service: ScheduleTargetsService,
    watch_targets_service: WatchTargetsService,
    extra_classes_web_service: ExtraClassesWebService,
    time_service: TimeService,
    db_liveness: Callable[[], Awaitable[bool]],
) -> FastAPI:
    """
    Собирает FastAPI-приложение.

    db_liveness: замыкание из main.py поверх shared aiosqlite-соединения;
    FastAPI НЕ владеет соединением и не закрывает его при shutdown
    (владелец — main.py, ТЗ 7.4).
    """
    app = FastAPI(
        title="School Schedule Web",
        version="0.7.0",
        docs_url=None,      # docs не выставляем наружу
        redoc_url=None,
        openapi_url=None,   # private deployment; включим осознанно позже
    )

    @app.exception_handler(StarletteHTTPException)
    async def custom_http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ):
        """
        Разделяет browser navigation и programmatic requests.

        Browser navigation:
        - 401 -> /auth;
        - 403 -> спокойная access-denied page.

        API / HTMX:
        - strict JSON 401/403;
        - без HTML redirect, чтобы client мог сам корректно обработать ошибку.
        """
        is_api_request = request.url.path.startswith("/api/")
        is_htmx_request = request.headers.get("HX-Request") == "true"
        is_page_request = not is_api_request and not is_htmx_request
        # P7.3: server-authoritative forced logout.
        #
        # session_revoked event запускает HTMX GET
        # /api/v1/live/revalidate. К этому моменту session уже отозвана
        # server-side, dependency возвращает 401 ещё до вызова route.
        #
        # Обычный JSON 401 не заставляет HTMX надёжно сменить page.
        # HX-Redirect на successful control response гарантирует full
        # navigation к public auth gate.
        if (
            request.url.path == "/api/v1/live/revalidate"
            and is_htmx_request
            and exc.status_code == 401
        ):
            return Response(
                status_code=200,
                headers={
                    "HX-Redirect": "/auth",
                    "Cache-Control": "no-store",
                },
            )
        if is_page_request and exc.status_code == 401:
            return RedirectResponse(
                url="/auth",
                status_code=303,
                headers={
                    "Cache-Control": "no-store",
                },
            )

        if is_page_request and exc.status_code == 403:
            templates = request.app.state.templates

            return templates.TemplateResponse(
                request,
                "auth/access_denied.html",
                {},
                status_code=403,
                headers={
                    "Cache-Control": "no-store",
                },
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
            },
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )
            
    # --- app.state: зависимости, доступные всем route'ам ---
    app.state.web_settings = web_settings
    app.state.sessions_service = sessions_service
    app.state.profile_service = profile_service
    app.state.schedule_service = schedule_service
    app.state.students_service = students_service
    app.state.schedule_targets_service = schedule_targets_service
    app.state.watch_targets_service = watch_targets_service
    app.state.extra_classes_web_service = extra_classes_web_service
    app.state.time_service = time_service
    app.state.db_liveness = db_liveness
    app.state.idempotency = IdempotencyStore(ttl_seconds=600)

    # --- Phase 7: event bus + SSE connection manager ---
    # Шина создаётся здесь (web-специфика); main.py публикует в неё
    # ScheduleChanged после commit NIKA-обновления (см. integration doc).
    event_bus = ApplicationEventBus()
    sse_manager = SSEConnectionManager(event_bus)
    app.state.event_bus = event_bus
    app.state.sse_manager = sse_manager

    # --- Шаблоны + jinja-фильтры навигации по датам ---
    templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

    def _prev_date(value: str) -> str:
        return prev_next_dates(value)[0]

    def _next_date(value: str) -> str:
        return prev_next_dates(value)[1]

    templates.env.filters["prev_date"] = _prev_date
    templates.env.filters["next_date"] = _next_date
    app.state.templates = templates

    # --- Middleware (порядок важен) ---
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=web_settings.allowed_hosts)
    app.add_middleware(GatewayKeyMiddleware, gateway_key=web_settings.gateway_key)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CSRFMiddleware, sessions_service=sessions_service)

    # --- Static (CSP 'self'; кэш-политика static — Phase 6 PWA) ---
    static_dir = _WEB_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # --- Routes ---
    from web.routes.auth import router as auth_router
    from web.routes.extra_classes import router as extra_router
    from web.routes.family import router as family_router
    from web.routes.health import router as health_router
    from web.routes.pwa import router as pwa_router
    from web.routes.schedule import router as schedule_router
    from web.routes.school import router as school_router
    from web.routes.stream import router as stream_router
    from web.routes.settings import router as settings_router

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(schedule_router)
    app.include_router(school_router)
    app.include_router(settings_router)
    app.include_router(family_router)
    app.include_router(extra_router)
    app.include_router(pwa_router)
    app.include_router(stream_router)

    # При shutdown web-сервера закрываем SSE best effort
    # (финальное закрытие ресурсов — в main.py, ТЗ 7.4).
    @app.on_event("shutdown")
    async def _close_sse() -> None:  # pragma: no cover
        sse_manager.close_all()

    return app
