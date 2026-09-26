# tests/web/phase21_checklist.py
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

# ВАЖНАЯ ПРОВЕРКА: Защита от несохраненных в редакторе файлов
project_root = Path(__file__).resolve().parents[2]
base_html = project_root / "web" / "templates" / "base.html"
day_html = project_root / "web" / "templates" / "schedule" / "day.html"

if base_html.exists() and base_html.stat().st_size < 10:
    print("\n" + "!"*70)
    print("🛑 КРИТИЧЕСКАЯ ОШИБКА: Файл web/templates/base.html ПУСТОЙ!")
    print("Вы вставили в него код, но забыли нажать Cmd+S (Ctrl+S) в VS Code.")
    print("Пожалуйста, сохраните ВСЕ HTML-файлы и запустите тест снова!")
    print("!"*70 + "\n")
    sys.exit(1)

if day_html.exists() and day_html.stat().st_size < 10:
    print("\n🛑 ОШИБКА: Файл day.html ПУСТОЙ! Сохраните его в VS Code!\n")
    sys.exit(1)

sys.path.insert(0, str(project_root))

import httpx  # noqa: E402
import aiosqlite  # noqa: E402
import aiohttp  # noqa: E402

from core.models.metadata import SchoolMetadata  # noqa: E402
from core.repository.extra_classes_repository import ExtraClassesRepository  # noqa: E402
from core.repository.profile_repository import ProfileRepository  # noqa: E402
from core.repository.schedule_repository import ScheduleRepository  # noqa: E402
from core.repository.student_repository import StudentRepository  # noqa: E402
from core.repository.web_auth_repository import WebAuthRepository  # noqa: E402
from core.repository.audit_repository import AuditRepository  # noqa: E402

from database.db import Database  # noqa: E402
from services.extra_classes_service import ExtraClassesService  # noqa: E402
from services.profiles_service import ProfileService  # noqa: E402
from services.schedule_service import ScheduleService  # noqa: E402
from services.schedule_targets_service import ScheduleTargetsService  # noqa: E402
from services.students_service import StudentsService  # noqa: E402
from services.time_service import TimeService, TimeServiceConfig  # noqa: E402
from services.web_sessions_service import WebSessionsService  # noqa: E402
from services.audit_service import AuditService  # noqa: E402

from web.app import WebSettings, create_web_app  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
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

        original_now = self.ts.get_now_base
        def mock_now():
            return original_now().replace(hour=8, minute=0, second=0)
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
            db_path=self.conn,
            http_session=self.http_session,
            time_service=self.ts,
            nika_base_url="https://lyceum.nstu.ru/rasp",
            history_days=7,
            metadata_cache=metadata,
        )
        
        profile_repo = ProfileRepository(db_path=self.conn, time_service=self.ts)
        student_repo = StudentRepository(db_path=self.conn, time_service=self.ts)
        extra_repo = ExtraClassesRepository(db_path=self.conn, time_service=self.ts)
        audit_repo = AuditRepository(db_path=self.conn, time_service=self.ts)

        self.audit_service = AuditService(
            audit_repo=audit_repo,
            profile_repo=profile_repo,
            time_service=self.ts,
            log_dir=os.path.dirname(self.db_path)
        )

        profile_service = ProfileService(profile_repo, audit_service=self.audit_service)
        students_service = StudentsService(student_repo, profile_service=profile_service, audit_service=self.audit_service)
        
        extra_service = ExtraClassesService(
            extra_classes_repo=extra_repo,
            profile_service=profile_service,
            students_service=students_service,
            time_service=self.ts,
            audit_service=self.audit_service
        )
        
        self.schedule_service = ScheduleService(
            schedule_repo=self.schedule_repo,
            time_service=self.ts,
            extra_classes_service=extra_service,
        )
        
        self.schedule_service.get_nika_health_status = self.schedule_repo.get_nika_health_status
        
        self.targets_service = ScheduleTargetsService(
            profile_service, students_service, student_repo
        )
        
        self.sessions = WebSessionsService(
            WebAuthRepository(db_path=self.conn, time_service=self.ts),
            self.ts,
            csrf_secret="phase2-1-checklist-secret-0123456789abcdef",
        )

        self.app = create_web_app(
            web_settings=WebSettings(
                public_url="http://testserver",
                allowed_hosts=["testserver"],
                gateway_key=None,
                access_mode="public",
                cookie_secure=False,
            ),
            sessions_service=self.sessions,
            profile_service=profile_service,
            schedule_service=self.schedule_service,
            students_service=students_service,
            schedule_targets_service=self.targets_service,
            time_service=self.ts,
            db_liveness=self._db_alive,
        )

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
            if "context" in kwargs:
                kwargs["context"] = {k: dictify(v) for k, v in kwargs["context"].items()}
            return original_tr(*new_args, **kwargs)
        self.app.state.templates.TemplateResponse = patched_tr

        self.today_iso = self.ts.get_now_base().date().isoformat()
        self.weekday = self.ts.get_now_base().date().isoweekday()
        await self._seed()
        return self

    async def _db_alive(self) -> bool:
        await self.conn.execute("SELECT 1")
        return True

    async def seed(self, table: str, row: dict, required: tuple[str, ...] = ()) -> None:
        cursor = await self.conn.execute(f"PRAGMA table_info({table})")
        cols = {r[1] for r in await cursor.fetchall()}
        missing = [k for k in required if k not in cols]
        if missing:
            raise RuntimeError(f"{table}: нет колонок {missing}")
        keys = [k for k in row if k in cols]
        await self.conn.execute(
            f"INSERT INTO {table} ({','.join(keys)}) "
            f"VALUES ({','.join('?' * len(keys))})",
            [row[k] for k in keys],
        )
        await self.conn.commit()

    async def _seed(self) -> None:
        now = self.ts.now_utc_str()

        await self.seed("families", {
            "id": 1, "family_code": "FAM001", "admin_user_id": 101,
            "created_at": now, "updated_at": now,
        })
        await self.seed("families", {
            "id": 2, "family_code": "FAM002", "admin_user_id": 201,
            "created_at": now, "updated_at": now,
        })

        users = [
            {"user_id": 101, "name": "Родитель", "role": "parent", "family_id": 1},
            {"user_id": 102, "name": "Саша", "role": "child", "family_id": 1,
             "class_id": "016", "group_id": "ALL"},
            {"user_id": 201, "name": "Родитель2", "role": "parent", "family_id": 2},
            {"user_id": 202, "name": "Чужой", "role": "child", "family_id": 2,
             "class_id": "017", "group_id": "ALL"},
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
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
            cookies={"web_session": raw},
        )
        return client, ctx.csrf_token

    async def close(self) -> None:
        await self.database.close()
        if hasattr(self, "http_session"):
            await self.http_session.close()


async def run(env: Env) -> None:
    # --- 1. parent -> child A/B + сохранение после F5 + POST+CSRF ---
    try:
        parent, csrf = await env.client(101)
        r = await parent.get("/")
        assert r.status_code == 200, r.status_code
        default_name = "Маша" if "Маша" in r.text else "Саша"
        other_id, other_name = (11, "Саша") if default_name == "Маша" else (12, "Маша")
        default_id = 12 if default_name == "Маша" else 11
        
        if default_name not in r.text:
            raise AssertionError(f"HTML не содержит {default_name}. Получено: {r.text[:500]}")

        r = await parent.post(f"/api/v1/schedule/select/{other_id}",
                              headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code == 200 and r.headers.get("HX-Redirect") == "/", (r.status_code, r.headers.get("HX-Redirect"))

        r = await parent.get("/")  
        if f'hx-post="/api/v1/schedule/select/{other_id}"' in r.text:
            raise AssertionError(f"Переключение на {other_name} не сработало")
        if f'hx-post="/api/v1/schedule/select/{default_id}"' not in r.text:
            raise AssertionError(f"Предыдущий ребенок {default_name} не стал кликабельным")
            
        r = await parent.get("/")  
        if f'hx-post="/api/v1/schedule/select/{other_id}"' in r.text:
            raise AssertionError(f"Выбор {other_name} не сохранился после F5")
            
        record("parent → child A/B + сохранение после F5 (POST + CSRF)", True)
        await parent.aclose()
    except Exception as exc:
        record("parent → child A/B + сохранение после F5 (POST + CSRF)", False, str(exc))

    # --- 2. POST select без CSRF -> 403 ---
    try:
        client, csrf = await env.client(101)
        r = await client.post("/api/v1/schedule/select/11")  
        assert r.status_code == 403, f"ожидали 403, получили {r.status_code}"
        record("POST select без CSRF → 403", True)
        await client.aclose()
    except Exception as exc:
        record("POST select без CSRF → 403", False, str(exc))

    # --- 3. child -> own student + собственные extra classes ---
    try:
        child, _ = await env.client(102)
        r = await child.get("/")
        assert r.status_code == 200, r.status_code
        if "Робототехника" not in r.text:
            raise AssertionError(f"у child не видно собственное доп. занятие. HTML: {r.text[:500]}")
        assert "доп." in r.text, "нет бейджа доп. занятия"
        record("child → own student + собственные extra classes", True)
        await child.aclose()
    except Exception as exc:
        record("child → own student + собственные extra classes", False, str(exc))

    # --- 4. child -> чужой student -> 403 ---
    try:
        child, csrf = await env.client(102)
        r = await child.post("/api/v1/schedule/select/21",
                              headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code == 403, f"ожидали 403, получили {r.status_code}"
        record("child → чужой student → 403", True)
        await child.aclose()
    except Exception as exc:
        record("child → чужой student → 403", False, str(exc))

    # --- 5. parent extra classes (занятия выбранного ребёнка) ---
    try:
        parent, csrf = await env.client(101)
        await parent.post("/api/v1/schedule/select/11",
                          headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        r = await parent.get("/")
        if "Робототехника" not in r.text:
            raise AssertionError(f"у parent не видно доп. занятие выбранного ребёнка. HTML: {r.text[:500]}")
        assert "доп." in r.text
        record("parent extra classes (выбранный ребёнок)", True)
        await parent.aclose()
    except Exception as exc:
        record("parent extra classes (выбранный ребёнок)", False, str(exc))

    # --- 6. changes: замена/отмена/добавление + hx-push-url/F5 ---
    try:
        parent, _ = await env.client(101)
        url = f"/schedule/changes/{env.today_iso}"
        r = await parent.get(url)
        assert r.status_code == 200, r.status_code
        html = r.text
        if "Химия" not in html or "Физика" not in html:
            raise AssertionError(f"нет замены «было → стало». HTML: {html[:500]}")
        assert "➔" in html, "нет стрелки замены"
        assert "Отменён" in html or "отмена" in html, "нет отмены"
        assert "добавлен" in html, "нет бейджа добавленного урока"
        assert "hx-push-url" in html, "нет hx-push-url"
        r = await parent.get(url) 
        assert r.status_code == 200 and "Химия" in r.text
        r = await parent.get(f"/schedule/day/{env.today_iso}")
        assert "Изменения" in r.text or "изменени" in r.text.lower()
        record("day changes: замена/отмена/добавление + hx-push-url/F5", True)
        await parent.aclose()
    except Exception as exc:
        record("day changes: замена/отмена/добавление + hx-push-url/F5", False, str(exc))

    # --- 7. NIKA healthy/stale ---
    try:
        parent, _ = await env.client(101)
        r = await parent.get("/")
        assert "Последнее обновление" not in r.text, "false-positive stale warning"
        await env.conn.execute(
            "UPDATE nika_source_state SET last_error = 'TestOutage' WHERE id = 1"
        )
        await env.conn.commit()
        r = await parent.get("/")
        if "Последнее обновление" not in r.text:
            raise AssertionError(f"stale warning не появился. HTML: {r.text[:500]}")
        assert "неактуальным" in r.text
        record("NIKA stale state (healthy: нет warning / stale: warning)", True)
        await parent.aclose()
    except Exception as exc:
        record("NIKA stale state (healthy: нет warning / stale: warning)", False, str(exc))

    # --- 8. GET select -> 405 ---
    try:
        client, _ = await env.client(101)
        r = await client.get("/api/v1/schedule/select/11")
        assert r.status_code == 405, f"ожидали 405, получили {r.status_code}"
        record("GET /api/v1/schedule/select/… → 405", True)
        await client.aclose()
    except Exception as exc:
        record("GET /api/v1/schedule/select/… → 405", False, str(exc))


async def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        env = Env(os.path.join(tmp, "checklist.db"))
        await env.build()
        try:
            await run(env)
        finally:
            await env.close()

    print("\n=== Phase 2.1 checklist ===")
    failed = 0
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" | {detail}" if detail else ""))
        failed += 0 if ok else 1
    print(f"Итог: {len(RESULTS) - failed}/{len(RESULTS)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))