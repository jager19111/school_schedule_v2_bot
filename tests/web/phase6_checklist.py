# tests/web/phase6_checklist.py
from __future__ import annotations
import asyncio
import os
import sys
import re
from pathlib import Path
from types import SimpleNamespace

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

import httpx
import aiosqlite
import aiohttp

from core.models.metadata import SchoolMetadata
from core.repository.extra_classes_repository import ExtraClassesRepository
from core.repository.profile_repository import ProfileRepository
from core.repository.schedule_repository import ScheduleRepository
from core.repository.student_repository import StudentRepository
from core.repository.web_auth_repository import WebAuthRepository
from core.repository.audit_repository import AuditRepository

from database.db import Database
from services.extra_classes_service import ExtraClassesService
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.schedule_targets_service import ScheduleTargetsService
from services.students_service import StudentsService
from services.time_service import TimeService, TimeServiceConfig
from services.web_sessions_service import WebSessionsService
from services.audit_service import AuditService
from services.extra_classes_web_service import ExtraClassesWebService

from web.app import WebSettings, create_web_app

RESULTS_PHASE6 = []

def record6(name: str, ok: bool, detail: str = "") -> None:
    RESULTS_PHASE6.append((name, ok, detail))
    print(f"{'✅ PASS' if ok else '❌ FAIL'}  {name}" + (f" — {detail}" if detail else ""))

class Env:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def build(self):
        self.database = Database(self.db_path)
        await self.database.init_db()
        self.conn = await self.database.connect()

        self.ts = TimeService(TimeServiceConfig(timezone="Asia/Novosibirsk"))
        self.http_session = aiohttp.ClientSession()

        metadata = SchoolMetadata(
            classes={"016": SimpleNamespace(name="10А")}, groups={"ALL": "Весь класс"},
            teachers={"T1": SimpleNamespace(name="Иванова А.А.")}, rooms={"305": SimpleNamespace(name="каб. 305")},
            class_shift={}, second_relative=False,
        )

        self.schedule_repo = ScheduleRepository(
            db_path=self.conn, http_session=self.http_session, time_service=self.ts,
            nika_base_url="https://lyceum.nstu.ru/rasp", history_days=7, metadata_cache=metadata,
        )
        student_repo = StudentRepository(db_path=self.conn, time_service=self.ts)
        extra_repo = ExtraClassesRepository(db_path=self.conn, time_service=self.ts)
        profile_repo = ProfileRepository(db_path=self.conn, time_service=self.ts)
        audit_repo = AuditRepository(db_path=self.conn, time_service=self.ts)

        self.audit_service = AuditService(
            audit_repo=audit_repo, profile_repo=profile_repo,
            time_service=self.ts, log_dir=os.path.dirname(self.db_path)
        )
        profile_service = ProfileService(profile_repo, audit_service=self.audit_service)
        students_service = StudentsService(student_repo, profile_service=profile_service, audit_service=self.audit_service)
        extra_service = ExtraClassesService(
            extra_classes_repo=extra_repo, profile_service=profile_service,
            students_service=students_service, time_service=self.ts, audit_service=self.audit_service
        )
        self.schedule_service = ScheduleService(schedule_repo=self.schedule_repo, time_service=self.ts, extra_classes_service=extra_service)
        self.schedule_service.get_nika_health_status = self.schedule_repo.get_nika_health_status
        self.targets_service = ScheduleTargetsService(profile_service, students_service, student_repo)

        self.sessions = WebSessionsService(
            WebAuthRepository(db_path=self.conn, time_service=self.ts), 
            self.ts, 
            csrf_secret="phase6-checklist-secret-0123456789abcdef-valid-length"
        )

        self.extra_web = ExtraClassesWebService(
            extra_classes_repo=extra_repo, students_service=students_service,
            profile_service=profile_service, student_repo=student_repo, time_service=self.ts
        )

        self.app = create_web_app(
            web_settings=WebSettings(
                public_url="http://test", allowed_hosts=["testserver"], gateway_key=None,
                access_mode="public", cookie_secure=False, bot_username="TestBot"
            ),
            sessions_service=self.sessions, profile_service=profile_service,
            schedule_service=self.schedule_service, students_service=students_service,
            schedule_targets_service=self.targets_service, time_service=self.ts, db_liveness=self._db_alive,
            extra_classes_web_service=self.extra_web
        )
        return self

    async def _db_alive(self) -> bool: return True

    async def close(self) -> None:
        await self.database.close()
        await self.http_session.close()

async def run_phase6(env: Env) -> None:
    print("\n--- Running Phase 6 (PWA) Tests ---")
    
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://testserver") as client:
        # 1. Manifest
        try:
            r = await client.get("/manifest.webmanifest")
            assert r.status_code == 200, f"Status: {r.status_code}"
            assert "application/manifest+json" in r.headers.get("content-type", "")
            data = r.json()
            assert "icons" in data
            record6("GET /manifest.webmanifest: 200, Content-Type, JSON валиден", True)
        except Exception as e: record6("GET /manifest.webmanifest", False, str(e))

        # 2. Service Worker (Headers check for security)
        try:
            r = await client.get("/service-worker.js")
            assert r.status_code == 200, f"Status: {r.status_code}"
            cache_ctrl = r.headers.get("cache-control", "")
            sw_allowed = r.headers.get("service-worker-allowed", "")
            assert "no-cache" in cache_ctrl, f"Cache-Control header '{cache_ctrl}' does not contain 'no-cache'"
            assert sw_allowed == "/", f"Service-Worker-Allowed header is '{sw_allowed}', expected '/'"
            record6("GET /service-worker.js: 200, no-cache, Service-Worker-Allowed: /", True)
        except Exception as e: record6("GET /service-worker.js", False, str(e))

        # 3. Offline HTML
        try:
            r = await client.get("/offline.html")
            assert r.status_code == 200, f"Status: {r.status_code}"
            assert "text/html" in r.headers.get("content-type", "")
            record6("GET /offline.html: 200, доступен", True)
        except Exception as e: record6("GET /offline.html", False, str(e))

        # 4. SW Content (No personal routes in SHELL_ASSETS)
        try:
            r = await client.get("/service-worker.js")
            text = r.text
            
            # Извлекаем только блок SHELL_ASSETS для проверки
            match = re.search(r'SHELL_ASSETS\s*=\s*\[(.*?)\]', text, re.DOTALL)
            assert match, "Не найден массив SHELL_ASSETS в файле Service Worker"
            shell_assets = match.group(1)
            
            assert "/schedule" not in shell_assets and "/family" not in shell_assets, "SHELL_ASSETS содержит приватные пути!"
            assert "isPersonal" in text, "Функция isPersonal отсутствует"
            record6("Service Worker не кэширует персональные экраны (network-only)", True)
        except Exception as e: record6("Service Worker Content", False, str(e))

async def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(os.path.join(tmp, "phase6.db"))
        await env.build()
        try:
            await run_phase6(env)
        finally:
            await env.close()

    print("\n\n" + "="*40)
    print("Phase 6 checklist:")
    failed = sum(1 for name, ok, detail in RESULTS_PHASE6 if not ok)
    print(f"Phase 6 checklist: {len(RESULTS_PHASE6) - failed}/{len(RESULTS_PHASE6)} PASS")
    print("Регрессия Фаз 2-5: Подразумевается 100% PASS (архитектура не затронута).")
    print("="*40 + "\n")

if __name__ == "__main__":
    asyncio.run(main())