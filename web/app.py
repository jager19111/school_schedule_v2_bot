# web/app.py
#
# Фабрика FastAPI-приложения (Phase 1-2).
#
# Web — interface layer над существующими сервисами (ТЗ 2):
#   Web UI -> FastAPI Web Layer -> Existing Services -> Repositories -> SQLite
# Здесь нет бизнес-логики и SQL; только transport, auth/session handling,
# security-политики, web-схемы и шаблоны.
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

from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.schedule_targets_service import ScheduleTargetsService
from services.students_service import StudentsService
from services.time_service import TimeService
from services.web_sessions_service import WebSessionsService
from web.mappers import prev_next_dates
from web.security import (
    CSRFMiddleware,
    GatewayKeyMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)

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


def create_web_app(
    *,
    web_settings: WebSettings,
    sessions_service: WebSessionsService,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    schedule_targets_service: ScheduleTargetsService,
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
        version="0.2.0",
        docs_url=None,      # docs не выставляем наружу
        redoc_url=None,
        openapi_url=None,   # private deployment; включим осознанно позже
    )

    # --- app.state: зависимости, доступные всем route'ам ---
    app.state.web_settings = web_settings
    app.state.sessions_service = sessions_service
    app.state.profile_service = profile_service
    app.state.schedule_service = schedule_service
    app.state.students_service = students_service
    app.state.schedule_targets_service = schedule_targets_service
    app.state.time_service = time_service
    app.state.db_liveness = db_liveness
    # NIKA stale-предупреждение (ТЗ 53) обновляется фоново в Phase 3;
    # строка или None.
    app.state.nika_health_cache = None

    # --- Шаблоны + jinja-фильтры навигации по датам ---
    templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
    
    # ИСПРАВЛЕНО: удалена ошибочная распаковка функции `_prev, _next = prev_next_dates`

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
    from web.routes.health import router as health_router
    from web.routes.schedule import router as schedule_router

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(schedule_router)

    return app