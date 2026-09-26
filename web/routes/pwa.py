# web/routes/pwa.py
#
# Phase 6 PWA foundation.
# Service worker выдаётся из root (/service-worker.js), а не из /static,
# чтобы его scope был '/' и он мог обслуживать shell приложения.
#
# ВАЖНО (ТЗ 49): SW НИКОГДА не кэширует персональные HTML/JSON/API:
# /, /schedule/*, /family/*, /extra-classes/*, /api/v1/*.

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()
_STATIC = Path(__file__).resolve().parent.parent / "static"


@router.get("/manifest.webmanifest", include_in_schema=False)
async def manifest() -> FileResponse:
    return FileResponse(
        _STATIC / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/service-worker.js", include_in_schema=False)
async def service_worker() -> FileResponse:
    # no-cache нужен, чтобы браузер регулярно проверял новую версию SW.
    return FileResponse(
        _STATIC / "service-worker.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@router.get("/offline.html", include_in_schema=False)
async def offline_shell() -> FileResponse:
    return FileResponse(
        _STATIC / "offline.html",
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )
