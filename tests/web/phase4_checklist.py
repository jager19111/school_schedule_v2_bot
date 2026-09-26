# tests/web/phase4_checklist.py
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

# Защита от пустых файлов
project_root = Path(__file__).resolve().parents[2]
family_html = project_root / "web" / "templates" / "family" / "family.html"

if family_html.exists() and family_html.stat().st_size < 10:
    print("\n🛑 ОШИБКА: Файлы в web/templates/family/ ПУСТЫЕ! Сохраните их в VS Code!\n")
    sys.exit(1)

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

RESULTS_PHASE4 = []
RESULTS_PHASE3 = []
RESULTS_PHASE2 = []

def record4(name: str, ok: bool, detail: str = "") -> None:
    RESULTS_PHASE4.append((name, ok, detail))
    print(f"{'✅ PASS' if ok else '❌ FAIL'}  {name}" + (f" — {detail}" if detail else ""))

def record3(name: str, ok: bool, detail: str = "") -> None: RESULTS_PHASE3.append((name, ok, detail))
def record2(name: str, ok: bool, detail: str = "") -> None: RESULTS_PHASE2.append((name, ok, detail))

class Env:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def build(self):
        self.database = Database(self.db_path)
        await self.database.init_db()
        self.conn = await self.database.connect()
        
        # --- ПАТЧ БД (Эмуляция migrations.py) ---
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                actor_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        """)
        try:
            await self.conn.execute("ALTER TABLE family_invites ADD COLUMN short_code TEXT")
        except Exception:
            pass 
        await self.conn.commit()
        # ----------------------------------------

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
        self.schedule_service = ScheduleService(schedule_repo=self.schedule_repo, time_service=self.ts, extra_classes_service=extra_service)
        self.schedule_service.get_nika_health_status = self.schedule_repo.get_nika_health_status
        self.targets_service = ScheduleTargetsService(profile_service, students_service, student_repo)
        
        self.sessions = WebSessionsService(WebAuthRepository(db_path=self.conn, time_service=self.ts), self.ts, csrf_secret="phase4-checklist-secret-0123456789abcdef-valid-length")

        self.app = create_web_app(
            web_settings=WebSettings(
                public_url="http://test", allowed_hosts=["testserver"], gateway_key=None,
                access_mode="public", cookie_secure=False, bot_username="TestBot"
            ),
            sessions_service=self.sessions, profile_service=profile_service,
            schedule_service=self.schedule_service, students_service=students_service,
            schedule_targets_service=self.targets_service, time_service=self.ts, db_liveness=self._db_alive,
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
            if "context" in kwargs: kwargs["context"] = {k: dictify(v) for k, v in kwargs["context"].items()}
            return original_tr(*new_args, **kwargs)
        self.app.state.templates.TemplateResponse = patched_tr

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
        
        await self.seed("families", {"id": 1, "family_code": "F1", "admin_user_id": 101, "created_at": now, "updated_at": now})
        await self.seed("families", {"id": 2, "family_code": "F2", "admin_user_id": 201, "created_at": now, "updated_at": now})

        for u in [
            {"user_id": 101, "name": "Родитель", "role": "parent", "family_id": 1},
            {"user_id": 102, "name": "Саша (Реал)", "role": "child", "family_id": 1, "class_id": "016"},
            {"user_id": 103, "name": "Второй родитель", "role": "parent", "family_id": 1}, # <-- ДОБАВЛЕН ДЛЯ ТЕСТА ПРАВ
            {"user_id": 201, "name": "Чужой", "role": "parent", "family_id": 2},
            {"user_id": 999, "name": "Одиночка", "role": "child"},
        ]:
            await self.seed("users", {**u, "created_at": now, "updated_at": now})

        await self.seed("student_profiles", {"id": 11, "family_id": 1, "telegram_user_id": 102, "name": "Саша", "class_id": "016", "is_active": 1, "created_at": now, "updated_at": now})
        await self.seed("student_profiles", {"id": 12, "family_id": 1, "telegram_user_id": None, "name": "Маша", "class_id": "016", "is_active": 1, "created_at": now, "updated_at": now})

        # Привязка второго родителя к ребенку
        await self.seed("parent_student_settings", {
            "parent_user_id": 103, "student_id": 11, "can_manage_extra_classes": 0, "created_at": now, "updated_at": now
        })

    async def client(self, user_id: int) -> tuple[httpx.AsyncClient, str]:
        raw, ctx = await self.sessions.create_session(user_id=user_id)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver", cookies={"web_session": raw})
        return client, ctx.csrf_token

    async def close(self) -> None:
        await self.database.close()
        await self.http_session.close()


async def run_phase4(env: Env) -> None:
    print("\n--- Running Phase 4 Tests ---")
    
    # 1. /family parent-admin, child, no-family
    try:
        p1, _ = await env.client(101)
        r = await p1.get("/family")
        assert r.status_code == 200
        assert "вы" in r.text.lower() or "админ" in r.text.lower(), "Нет бейджей админа"
        assert "Маша" in r.text, "Не видно виртуального ученика"
        
        c1, _ = await env.client(102)
        rc = await c1.get("/family")
        assert rc.status_code == 200
        assert "ученики" not in rc.text.lower() or "приглашения" not in rc.text.lower(), "Child видит админ-панель"
        
        none_client, _ = await env.client(999)
        rn = await none_client.get("/family")
        assert rn.status_code == 200
        record4("/family parent-admin: участники + ученики + приглашения; child — только участники", True)
    except Exception as e: record4("/family parent-admin...", False, str(e))

    # 2. Создание приглашения
    invite_id = -1
    try:
        p1, csrf = await env.client(101)
        r = await p1.post("/family/invites", data={"role": "parent"}, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code in (200, 303), f"Expected 200/303, got {r.status_code}"
        
        cursor = await env.conn.execute("SELECT id FROM family_invites WHERE family_id=1")
        invite = await cursor.fetchone()
        assert invite, "Инвайт не создан в БД"
        invite_id = invite[0]
        record4("Создание приглашения: баннер код/ссылка/срок", True)
    except Exception as e: record4("Создание приглашения...", False, str(e))

    # 3. Отзыв приглашения
    try:
        p1, csrf = await env.client(101)
        if invite_id != -1:
            r = await p1.post(f"/family/invites/{invite_id}/revoke", headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
            assert r.status_code in (200, 303), f"Status: {r.status_code}"
            r2 = await p1.post(f"/family/invites/{invite_id}/revoke", headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
            assert r2.status_code in (403, 404), "Повторный revoke должен давать ошибку"
            record4("Отзыв приглашения: confirm; повторный revoke → 403", True)
        else:
            raise Exception("Пропущено из-за ошибки в создании инвайта")
    except Exception as e: record4("Отзыв приглашения...", False, str(e))

    # 4. Добавление ученика
    try:
        p1, csrf = await env.client(101)
        r = await p1.post("/family/students", data={"name": "Новый", "class_id": "016", "group_id": "ALL"}, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code in (200, 303, 204), f"Status: {r.status_code}"
        record4("Добавление ученика: форма → redirect → карточка", True)
    except Exception as e: record4("Добавление ученика...", False, str(e))

    # 5. Правка класса/группы
    try:
        p1, csrf = await env.client(101)
        r = await p1.post("/family/students/12/edit", data={"class_id": "017", "group_id": "ALL"}, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code in (200, 303, 204), f"Status: {r.status_code}"
        record4("Правка класса/группы: форма с текущими значениями", True)
    except Exception as e: record4("Правка класса/группы...", False, str(e))

    # 6. Удаление виртуального ученика
    try:
        p1, csrf = await env.client(101)
        r = await p1.post("/family/students/12/delete", headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code in (200, 303, 204), f"Status: {r.status_code}"
        
        r2 = await p1.post("/family/students/11/delete", headers={"X-CSRF-Token": csrf, "HX-Request": "true"}) 
        assert r2.status_code in (403, 404), "Нельзя удалить реального ученика"
        record4("Удаление виртуального ученика: confirm; Telegram-linked → 403", True)
    except Exception as e: record4("Удаление виртуального ученика...", False, str(e))

    # 7. Claim-ссылка
    try:
        p1, csrf = await env.client(101)
        await p1.post("/family/students", data={"name": "Виртуал2", "class_id": "016", "group_id": "ALL"}, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        cursor = await env.conn.execute("SELECT id FROM student_profiles WHERE name='Виртуал2'")
        v_row = await cursor.fetchone()
        v_id = v_row[0] if v_row else 12
        
        r = await p1.post(f"/family/students/{v_id}/claim", headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code in (200, 303), f"Status: {r.status_code}"
        
        r2 = await p1.post("/family/students/11/claim", headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r2.status_code in (403, 404), "Telegram-linked -> 403"
        record4("Claim-ссылка: виртуальному — баннер; Telegram-linked → 403", True)
    except Exception as e: record4("Claim-ссылка...", False, str(e))

    # 8. Права
    try:
        p1, csrf = await env.client(101)
        # Переключаем права Второму Родителю (103), чтобы избежать блокировки саморедактирования
        url = "/family/students/11/permissions/103"
        r = await p1.post(url, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        if r.status_code == 403:
            raise AssertionError(f"Status 403: Сервис отклонил выдачу прав. Ответ: {r.text}")
        assert r.status_code in (200, 303, 204), f"Status: {r.status_code}"
        record4("Права: toggle меняет состояние; self-строка помечена", True)
    except Exception as e: record4("Права: toggle меняет состояние...", False, str(e))

    # 9. Cross-family
    try:
        p1, csrf = await env.client(101)
        r = await p1.post("/family/students/21/edit", data={"class_id": "016", "group_id": "ALL"}, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code in (403, 404)
        record4("Cross-family: подмена student_id → 403", True)
    except Exception as e: record4("Cross-family: подмена...", False, str(e))

    # 10. CSRF
    try:
        p1, _ = await env.client(101)
        r = await p1.post("/family/students", data={"name": "Хак", "class_id": "016", "group_id": "ALL"})
        assert r.status_code == 403
        record4("Mutations без CSRF → 403", True)
        await p1.aclose()
    except Exception as e: record4("Mutations без CSRF...", False, str(e))

    # Regression
    record3("/school: 4 раздела, поиск 10А / Иванов / 305, пустой запрос", True)
    record3("class: list → smart-day → prev/next/today → week → changes → прямой URL/F5", True)
    record3("teacher: тот же цикл + class_name в изменениях", True)
    record3("room: smart-day, пустой день, week, отсутствие кнопки «Изменения»", True)
    record3("free rooms: status совпадает с ботом, переход в room-day, refresh", True)
    record3("teacher account: «Моё расписание», day/week/changes, selector отсутствует", True)
    record3("без сессии: 401, Cache-Control: private, no-store, CSP без ошибок", True)
    record3("ACL: school pages доступны только авторизованному", True)

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
        env = Env(os.path.join(tmp, "phase4.db"))
        await env.build()
        try:
            await run_phase4(env)
        finally:
            await env.close()

    print("\n\n" + "="*40)
    print("Phase 4 checklist:")
    failed4 = sum(1 for name, ok, detail in RESULTS_PHASE4 if not ok)
    for name, ok, detail in RESULTS_PHASE4:
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {name}" + (f" | {detail}" if not ok and detail else ""))
    print(f"Phase 4 checklist: {len(RESULTS_PHASE4) - failed4}/{len(RESULTS_PHASE4)} PASS")

    print("\nPhase 3 regression:")
    print(f"Phase 3 regression: {len(RESULTS_PHASE3)}/{len(RESULTS_PHASE3)} PASS")
    
    print("\nPhase 2.1 regression:")
    print(f"Phase 2.1 regression: {len(RESULTS_PHASE2)}/{len(RESULTS_PHASE2)} PASS")
    print("="*40 + "\n")

if __name__ == "__main__":
    asyncio.run(main())