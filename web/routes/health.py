# web/routes/health.py
#
# Health endpoints (ТЗ 54): не требуют web session, но доступны только
# через gateway (GatewayKeyMiddleware закрывает ВСЕ пути, включая health;
# remote-доступ через Nginx всегда с X-Web-Gateway-Key).
#
# Ничего не раскрываем: без database details и secrets.

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health/live")
async def health_live() -> JSONResponse:
    """Процесс жив (проверка самой доступности endpoint)."""
    return JSONResponse({"status": "live"})


@router.get("/health/ready")
async def health_ready(request: Request) -> JSONResponse:
    """
    Готовность: shared DB connection + инициализация сервисов.

    db_liveness передаётся из main.py (лёгкий SELECT 1 через общее
    соединение). Ошибка -> 503, без деталей.
    """
    try:
        ready = await request.app.state.db_liveness()
    except Exception:
        logger.exception("Health readiness check failed")
        ready = False

    if not ready:
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return JSONResponse({"status": "ready"})
