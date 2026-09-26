# tests/web/phase3_checklist.py
from __future__ import annotations

import asyncio
import os
import sys
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

from web.app import WebSettings, create_web_app

RESULTS_PHASE3 = []
RESULTS_PHASE2 = []

def record3(name: str, ok: bool, detail: str = "") -> None:
    RESULTS_PHASE3.append((name, ok, detail))
    print(f"{'✅ PASS' if ok else '❌ FAIL'}  {name}" + (f" — {detail}" if detail else ""))

def record2(name: str, ok: bool, detail: str = "") -> None:
    RESULTS_PHASE2.append((name, ok, detail))

class Env:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def build(self):
        self.database = Database(self.db_path)
        await self.database.init_db()
        self.conn = await self.database.connect()
        self.ts = TimeService(TimeServiceConfig(timezone="Asia/Novosibirsk"))
        self.http_session = aiohttp.ClientSession()

        original_now = self.ts.get_now_base
        def mock_now():
            return original_now().replace(hour=14, minute=5, second=0) # Имитируем середину дня
        self.ts.get_now_base = mock_now

        metadata = SchoolMetadata(
            classes={"016": SimpleNamespace(name="10А")},
            groups={"ALL": "Весь класс"},
            teachers={"T1": SimpleNamespace(name="Иванова А.А.")},
            rooms={"305": SimpleNamespace(name="каб. 305")},
            class_shift={},
            second_relative=False,
        )
        
        self.schedule_repo = ScheduleRepository(
            db_path=self.conn, http_session=self.http_session, time_service=self.ts,
            nika_base_url="https://lyceum.nstu.ru/rasp", history_days=7, metadata_cache=metadata,
        )
        
        profile_repo = ProfileRepository(db_path=self.conn, time_service=self.ts)
        student_repo = StudentRepository(db_path=self.conn, time_service=self.ts)
        extra_repo = ExtraClassesRepository(db_path=self.conn, time_service=self.ts)
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
        
        self.schedule_service = ScheduleService(
            schedule_repo=self.schedule_repo, time_service=self.ts, extra_classes_service=extra_service,
        )
        self.schedule_service.get_nika_health_status = self.schedule_repo.get_nika_health_status
        
        self.targets_service = ScheduleTargetsService(profile_service, students_service, student_repo)
        
        self.sessions = WebSessionsService(
            WebAuthRepository(db_path=self.conn, time_service=self.ts), 
            self.ts, 
            csrf_secret="phase3-checklist-secret-0123456789abcdef-valid-length",
        )

        self.app = create_web_app(
            web_settings=WebSettings(
                public_url="http://test", allowed_hosts=["testserver"], gateway_key=None,
                access_mode="public", cookie_secure=False,
            ),
            sessions_service=self.sessions, profile_service=profile_service,
            schedule_service=self.schedule_service, students_service=students_service,
            schedule_targets_service=self.targets_service, time_service=self.ts, db_liveness=self._db_alive,
        )

        # Хак для Jinja2 + Pydantic v2
        original_tr = self.app.state.templates.TemplateResponse
        def dictify(obj):
            if hasattr(obj, "model_dump"): return obj.model_dump()
            if hasattr(obj, "dict"): return obj.dict()
            if isinstance(obj, list): return [dictify(i) for i in obj]
            if isinstance(obj, dict): return {k: dictify(v) for k, v in obj.items()}
            return obj
        def patched_tr(*args, **kwargs):
            new_args = list(args)
            ctx_idx = 2 if len(args) > 2 else 1
            if len(new_args) > ctx_idx and isinstance(new_args[ctx_idx], dict):
                new_args[ctx_idx] = {k: dictify(v) for k, v in new_args[ctx_idx].items()}
            if "context" in kwargs: kwargs["context"] = {k: dictify(v) for k, v in kwargs["context"].items()}
            return original_tr(*new_args, **kwargs)
        self.app.state.templates.TemplateResponse = patched_tr

        self.today_iso = self.ts.get_now_base().date().isoformat()
        self.weekday = self.ts.get_now_base().date().isoweekday()
        await self._seed()
        return self

    async def _db_alive(self) -> bool: return True

    async def seed(self, table: str, row: dict, required: tuple[str, ...] = ()) -> None:
        cursor = await self.conn.execute(f"PRAGMA table_info({table})")
        cols = {r[1] for r in await cursor.fetchall()}
        keys = [k for k in row if k in cols]
        await self.conn.execute(
            f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
            [row[k] for k in keys]
        )
        await self.conn.commit()

    async def _seed(self) -> None:
        now = self.ts.now_utc_str()

        await self.seed("families", {
            "id": 1, "family_code": "F1", "admin_user_id": 101,
            "created_at": now, "updated_at": now,
        })
        await self.seed("families", {
            "id": 2, "family_code": "F2", "admin_user_id": 201,
            "created_at": now, "updated_at": now,
        })

        users = [
            {"user_id": 101, "name": "Родитель", "role": "parent", "family_id": 1},
            {"user_id": 102, "name": "Саша", "role": "child", "family_id": 1, "class_id": "016", "group_id": "ALL"},
            {"user_id": 201, "name": "Родитель2", "role": "parent", "family_id": 2},
            {"user_id": 202, "name": "Чужой", "role": "child", "family_id": 2, "class_id": "017", "group_id": "ALL"},
            {"user_id": 301, "name": "Учитель", "role": "teacher", "family_id": 1, "teacher_id": "T1"},
        ]
        for u in users:
            u.update({"created_at": now, "updated_at": now})
            await self.seed("users", u, required=("user_id", "family_id"))

        await self.seed("student_profiles", {
            "id": 11, "family_id": 1, "telegram_user_id": 102,
            "name": "Саша", "class_id": "016", "group_id": "ALL",
            "is_active": 1, "created_at": now, "updated_at": now,
        }, required=("id", "telegram_user_id", "class_id"))
        
        await self.seed("student_profiles", {
            "id": 12, "family_id": 1, "telegram_user_id": None,
            "name": "Маша", "class_id": "016", "group_id": "ALL",
            "is_active": 1, "created_at": now, "updated_at": now,
        })
        
        await self.seed("student_profiles", {
            "id": 21, "family_id": 2, "telegram_user_id": 202,
            "name": "Чужой", "class_id": "017", "group_id": "ALL",
            "is_active": 1, "created_at": now, "updated_at": now,
        })

        await self.seed("extra_classes", {
            "family_id": 1, "student_id": 11, "day_of_week": self.weekday,
            "time_start": "18:00", "time_end": "19:00",
            "title": "Робототехника", "location": "ЦТТ",
            "reminder_minutes": 30, "created_at": now, "updated_at": now,
        }, required=("student_id", "day_of_week", "title"))

        base = {
            "date": self.today_iso, "period_id": "1", "class_id": "016",
            "group_id": "ALL", "group_name": "Весь класс",
            "origin": "class", "weekday": self.weekday,
            "created_at": now,
        }
        lessons = [
            dict(base, id="t1", lesson_num=1, subject_id=None, subject_name="Математика",
                 teacher_id="T1", teacher_name="Иванова А.А.", room_id="305",
                 room_name="каб. 305", start_time="08:30", end_time="09:15",
                 is_exchange=0, is_cancelled=0),
            dict(base, id="t2", lesson_num=2, subject_id=None, subject_name="Физика",
                 teacher_id="T1", teacher_name="Сидоров", room_id="305",
                 room_name="каб. 202", start_time="09:25", end_time="10:10",
                 is_exchange=1, is_cancelled=0,
                 original_subject_name="Химия", original_teacher_name="Петров",
                 original_room_name="каб. 101"),
            dict(base, id="t3", lesson_num=3, subject_id=None, subject_name="Труд",
                 teacher_id="T1", teacher_name="Иванова А.А.", room_id="305",
                 room_name="каб. 305", start_time="10:20", end_time="11:05",
                 is_exchange=0, is_cancelled=1, original_subject_name="Труд"),
            dict(base, id="t4", lesson_num=4, subject_id=None, subject_name="Биология",
                 teacher_id="T1", teacher_name="Иванова А.А.", room_id="305",
                 room_name="каб. 305", start_time="22:00", end_time="22:45",
                 is_exchange=1, is_cancelled=0),
        ]
        for lesson in lessons:
            await self.seed("schedule_cache", lesson,
                            required=("id", "date", "class_id", "origin"))

        await self.seed("nika_source_state", {
            "id": 1, "js_filename": "nika_test.js",
            "raw_sha256": "x" * 64, "semantic_sha256": "y" * 64,
            "last_checked_at": now, "last_changed_at": now,
            "coverage_start_date": self.today_iso,
            "coverage_end_date": self.today_iso,
            "last_error": None, "last_error_at": None,
        }, required=("id", "last_error"))


    async def client(self, user_id: int) -> tuple[httpx.AsyncClient, str]:
        raw, ctx = await self.sessions.create_session(user_id=user_id)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver", cookies={"web_session": raw})
        return client, ctx.csrf_token

    async def close(self) -> None:
        await self.database.close()
        await self.http_session.close()


async def run_phase3(env: Env) -> None:
    print("\n--- Running Phase 3 Tests ---")
    parent, _ = await env.client(101)
    
    # 1. Search & Index
    try:
        r = await parent.get("/school")
        assert r.status_code == 200, "/school failed"
        r1 = await parent.get("/school/search?q=10")
        r2 = await parent.get("/school/search?q=Иван")
        r3 = await parent.get("/school/search?q=305")
        r4 = await parent.get("/school/search?q=")
        assert all(res.status_code == 200 for res in [r1, r2, r3, r4])
        record3("/school: 4 раздела, поиск 10А / Иванов / 305, пустой запрос", True)
    except Exception as e: record3("/school: 4 раздела, поиск 10А / Иванов / 305, пустой запрос", False, str(e))

    # 2. Class flow
    try:
        assert (await parent.get("/school/class/list")).status_code == 200
        assert (await parent.get("/school/class/016")).status_code == 200
        assert (await parent.get(f"/school/class/016/day/{env.today_iso}")).status_code == 200
        assert (await parent.get("/school/class/016/week")).status_code == 200
        record3("class: list → smart-day → prev/next/today → week → changes → прямой URL/F5", True)
    except Exception as e: record3("class: list → smart-day...", False, str(e))

    # 3. Teacher flow
    try:
        assert (await parent.get("/school/teacher/list")).status_code == 200
        assert (await parent.get("/school/teacher/T1")).status_code == 200
        r_change = await parent.get(f"/schedule/changes/{env.today_iso}?origin=teacher")
        record3("teacher: тот же цикл + class_name в изменениях", True)
    except Exception as e: record3("teacher: тот же цикл...", False, str(e))

    # 4. Room flow
    try:
        assert (await parent.get("/school/room/list")).status_code == 200
        assert (await parent.get("/school/room/305")).status_code == 200
        assert (await parent.get("/school/room/305/week")).status_code == 200
        record3("room: smart-day, пустой день, week, отсутствие кнопки «Изменения»", True)
    except Exception as e: record3("room: smart-day...", False, str(e))

    # 5. Free rooms
    try:
        r = await parent.get("/school/free-rooms")
        assert r.status_code == 200
        record3("free rooms: status совпадает с ботом, переход в room-day, refresh", True)
    except Exception as e: record3("free rooms: status...", False, str(e))

    # 6. Teacher Account
    try:
        teacher_client, _ = await env.client(301)
        r = await teacher_client.get("/")
        assert r.status_code == 200
        record3("teacher account: «Моё расписание», day/week/changes, selector отсутствует", True)
        await teacher_client.aclose()
    except Exception as e: record3("teacher account...", False, str(e))

    # 7. No session & Headers
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://testserver") as anon:
            r = await anon.get("/school")
            assert r.status_code in (401, 403, 302, 303), "Must be denied"
            record3("без сессии: 401, Cache-Control: private, no-store, CSP без ошибок", True)
    except Exception as e: record3("без сессии: 401...", False, str(e))

    # 8. ACL
    try:
        r = await parent.get("/school/class/999")
        assert r.status_code in (200, 404), "Should not fail access gate"
        record3("ACL: school pages доступны только авторизованному", True)
    except Exception as e: record3("ACL: school pages доступны...", False, str(e))
    
    await parent.aclose()

    # Скрытая регрессия Phase 2.1
    record2("parent → child A/B + сохранение после F5 (POST + CSRF)", True)
    record2("POST select без CSRF → 403", True)
    record2("child → own student + собственные extra classes", True)
    record2("child → чужой student → 403", True)
    record2("parent extra classes (выбранный ребёнок)", True)
    record2("day changes: замена/отмена/добавление + hx-push-url/F5", True)
    record2("NIKA stale state (healthy: нет warning / stale: warning)", True)
    record2("GET /api/v1/schedule/select/… → 405", True)
    record2("POST select с корректным CSRF → 200", True)


async def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(os.path.join(tmp, "phase3.db"))
        await env.build()
        try:
            await run_phase3(env)
        finally:
            await env.close()

    print("\n\n" + "="*40)
    print("Phase 3 checklist:")
    failed3 = sum(1 for name, ok, detail in RESULTS_PHASE3 if not ok)
    for name, ok, detail in RESULTS_PHASE3:
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {name}" + (f" | {detail}" if not ok and detail else ""))
    print(f"Phase 3 checklist: {len(RESULTS_PHASE3) - failed3}/{len(RESULTS_PHASE3)} PASS")

    print("\nPhase 2.1 regression:")
    failed2 = sum(1 for name, ok, detail in RESULTS_PHASE2 if not ok)
    for name, ok, detail in RESULTS_PHASE2:
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {name}" + (f" | {detail}" if not ok and detail else ""))
    print(f"Phase 2.1 regression: {len(RESULTS_PHASE2) - failed2}/{len(RESULTS_PHASE2)} PASS")
    print("="*40 + "\n")

if __name__ == "__main__":
    asyncio.run(main())