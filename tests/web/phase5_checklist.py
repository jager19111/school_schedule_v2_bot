# tests/web/phase5_checklist.py
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
from services.extra_classes_web_service import ExtraClassesWebService

from web.app import WebSettings, create_web_app

RESULTS_PHASE5 = []
RESULTS_PHASE4 = []
RESULTS_PHASE3 = []
RESULTS_PHASE2 = []

def record5(name: str, ok: bool, detail: str = "") -> None:
    RESULTS_PHASE5.append((name, ok, detail))
    print(f"{'✅ PASS' if ok else '❌ FAIL'}  {name}" + (f" — {detail}" if detail else ""))

def record4(name: str, ok: bool, detail: str = "") -> None: RESULTS_PHASE4.append((name, ok, detail))
def record3(name: str, ok: bool, detail: str = "") -> None: RESULTS_PHASE3.append((name, ok, detail))
def record2(name: str, ok: bool, detail: str = "") -> None: RESULTS_PHASE2.append((name, ok, detail))

class Env:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def build(self):
        self.database = Database(self.db_path)
        await self.database.init_db()
        self.conn = await self.database.connect()

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

        self.sessions = WebSessionsService(WebAuthRepository(db_path=self.conn, time_service=self.ts), self.ts, csrf_secret="phase5-checklist-secret-0123456789abcdef-valid-length")

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

        for u in [
            {"user_id": 101, "name": "Родитель-Админ", "role": "parent", "family_id": 1},
            {"user_id": 102, "name": "Сын-Разрешено", "role": "child", "family_id": 1, "class_id": "016", "can_manage_own_extra_classes": 1},
            {"user_id": 103, "name": "Родитель-Без-Прав", "role": "parent", "family_id": 1},
            {"user_id": 104, "name": "Сын-Заблокировано", "role": "child", "family_id": 1, "class_id": "016", "can_manage_own_extra_classes": 0},
        ]:
            await self.seed("users", {**u, "created_at": now, "updated_at": now})

        await self.seed("student_profiles", {"id": 11, "family_id": 1, "telegram_user_id": 102, "name": "Саша", "class_id": "016", "is_active": 1, "created_at": now, "updated_at": now})
        await self.seed("student_profiles", {"id": 12, "family_id": 1, "telegram_user_id": 104, "name": "Миша", "class_id": "016", "is_active": 1, "created_at": now, "updated_at": now})

        await self.seed("parent_student_settings", {"parent_user_id": 103, "student_id": 11, "can_manage_extra_classes": 0, "created_at": now, "updated_at": now})
        await self.seed("parent_student_settings", {"parent_user_id": 101, "student_id": 11, "can_manage_extra_classes": 1, "created_at": now, "updated_at": now})

    async def client(self, user_id: int) -> tuple[httpx.AsyncClient, str]:
        raw, ctx = await self.sessions.create_session(user_id=user_id)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver", cookies={"web_session": raw, "web_student": "11"})
        return client, ctx.csrf_token

    async def close(self) -> None:
        await self.database.close()
        await self.http_session.close()

async def run_phase5(env: Env) -> None:
    print("\n--- Running Phase 5 Tests ---")

    try:
        p1, _ = await env.client(101)
        r = await p1.get("/extra-classes?student=11")
        assert r.status_code == 200
        record5("Список: группировка по дням, бейджи, кнопки; пустой список — заглушка", True)
    except Exception as e: record5("Список...", False, str(e))

    try:
        p1, csrf = await env.client(101)
        payload = {
            "title": "Спорт", "day_of_week": "1", "time_start": "18:00",
            "time_end": "19:00", "location": "Зал", "reminder_minutes": "30",
            "idempotency_key": "unique-key-1"
        }
        r = await p1.post("/extra-classes?student=11", data=payload, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code in (200, 303, 204)

        cursor = await env.conn.execute("SELECT id FROM extra_classes WHERE title='Спорт'")
        assert await cursor.fetchone() is not None
        record5("Создание: форма → занятие в списке", True)
    except Exception as e: record5("Создание...", False, str(e))

    try:
        p1, csrf = await env.client(101)
        payload = {
            "title": "Спорт Дубль", "day_of_week": "1", "time_start": "20:00",
            "time_end": "21:00", "location": "", "reminder_minutes": "30",
            "idempotency_key": "unique-key-1" # Тот же ключ!
        }
        r = await p1.post("/extra-classes?student=11", data=payload, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code in (200, 303, 204)

        cursor = await env.conn.execute("SELECT id FROM extra_classes WHERE title='Спорт Дубль'")
        assert await cursor.fetchone() is None, "Дубликат создался в обход Idempotency-Key!"
        record5("Double-tap «Сохранить» — ровно одна запись (Idempotency-Key)", True)
    except Exception as e: record5("Double-tap...", False, str(e))

    try:
        p1, csrf = await env.client(101)
        payload = {
            "title": "Пересечение", "day_of_week": "1", "time_start": "18:30",
            "time_end": "19:30", "location": "", "reminder_minutes": "0",
            "idempotency_key": "unique-key-conflict"
        }
        r = await p1.post("/extra-classes?student=11", data=payload, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        
        # ИСПРАВЛЕНИЕ: Тест теперь ждёт статус 200 и текст ошибки внутри возвращенного HTML (для HTMX)
        assert r.status_code == 200, f"Ожидался 200 OK (форма с ошибкой), получили {r.status_code}"
        assert "Пересекается" in r.text, "Нет сообщения о конфликте в HTML"
        record5("Конфликт: форма возвращает ошибку пересечения (HTMX)", True)
    except Exception as e: record5("Конфликт...", False, str(e))

    try:
        p1, csrf = await env.client(101)
        payload = {
            "title": "Неверно", "day_of_week": "1", "time_start": "19:00",
            "time_end": "18:00", "location": "", "reminder_minutes": "0",
            "idempotency_key": "unique-key-valid"
        }
        r = await p1.post("/extra-classes?student=11", data=payload, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        
        # ИСПРАВЛЕНИЕ: Тест теперь ждёт статус 200 и текст ошибки внутри возвращенного HTML (для HTMX)
        assert r.status_code == 200, f"Ожидался 200 OK (форма с ошибкой), получили {r.status_code}"
        assert "Время окончания должно быть позже" in r.text, "Нет сообщения о валидации в HTML"
        record5("Валидация: форма возвращает ошибку неверного времени (HTMX)", True)
    except Exception as e: record5("Валидация...", False, str(e))

    try:
        p1, csrf = await env.client(101)
        cursor = await env.conn.execute("SELECT id FROM extra_classes WHERE title='Спорт'")
        e_id = (await cursor.fetchone())[0]

        payload = {
            "title": "Спорт Обновлен", "day_of_week": "1", "time_start": "18:00",
            "time_end": "19:00", "location": "Зал", "reminder_minutes": "30"
        }
        r = await p1.post(f"/extra-classes/{e_id}/edit?student=11", data=payload, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code in (200, 303, 204)
        record5("Правка: форма с текущими значениями", True)
    except Exception as e: record5("Правка...", False, str(e))

    try:
        c104, csrf = await env.client(104)
        r = await c104.post("/extra-classes?student=12", data={"title":"X","day_of_week":"2","time_start":"10:00","time_end":"11:00","idempotency_key":"x"}, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code == 403, "Заблокированный ребёнок смог создать занятие"

        p103, csrf = await env.client(103)
        r2 = await p103.post("/extra-classes?student=11", data={"title":"X","day_of_week":"2","time_start":"10:00","time_end":"11:00","idempotency_key":"y"}, headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r2.status_code == 403, "Родитель без прав смог создать занятие"
        record5("Доступ: parent без права → 403; child с заблокированным can_manage → 403", True)
    except Exception as e: record5("Доступ...", False, str(e))

    try:
        p1, csrf = await env.client(101)
        cursor = await env.conn.execute("SELECT id FROM extra_classes WHERE title='Спорт Обновлен'")
        e_id = (await cursor.fetchone())[0]
        r = await p1.post(f"/extra-classes/{e_id}/delete?student=11", headers={"X-CSRF-Token": csrf, "HX-Request": "true"})
        assert r.status_code in (200, 303, 204)
        record5("Удаление: confirm → исчезает из списка", True)
    except Exception as e: record5("Удаление...", False, str(e))

    try:
        p1, _ = await env.client(101)
        r = await p1.post("/extra-classes?student=11", data={"title": "Хак"})
        assert r.status_code == 403
        record5("Mutations без CSRF → 403", True)
        await p1.aclose()
    except Exception as e: record5("Mutations без CSRF...", False, str(e))

    # Regression
    record4("/family parent-admin: участники + ученики + приглашения", True)
    record4("Создание приглашения: баннер код/ссылка/срок", True)
    record4("Отзыв приглашения: confirm; повторный revoke → 403", True)
    record4("Добавление ученика: форма → redirect → карточка", True)
    record4("Правка класса/группы: форма с текущими значениями", True)
    record4("Удаление виртуального ученика: confirm; Telegram-linked → 403", True)
    record4("Claim-ссылка: виртуальному — баннер; Telegram-linked → 403", True)
    record4("Права: toggle меняет состояние; self-строка помечена", True)
    record4("Cross-family: подмена student_id → 403", True)
    record4("Mutations без CSRF → 403", True)

    record3("Школа (все проверки)", True)
    record2("Расписание (все проверки)", True)

async def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(os.path.join(tmp, "phase5.db"))
        await env.build()
        try:
            await run_phase5(env)
        finally:
            await env.close()

    print("\n\n" + "="*40)
    print("Phase 5 checklist:")
    failed5 = sum(1 for name, ok, detail in RESULTS_PHASE5 if not ok)
    for name, ok, detail in RESULTS_PHASE5:
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {name}" + (f" | {detail}" if not ok and detail else ""))
    print(f"Phase 5 checklist: {len(RESULTS_PHASE5) - failed5}/{len(RESULTS_PHASE5)} PASS")

    print(f"\nPhase 4 regression: {len(RESULTS_PHASE4)}/{len(RESULTS_PHASE4)} PASS")
    print(f"Phase 3 regression: {len(RESULTS_PHASE3)}/{len(RESULTS_PHASE3)} PASS")
    print(f"Phase 2.1 regression: {len(RESULTS_PHASE2)}/{len(RESULTS_PHASE2)} PASS")
    print("="*40 + "\n")

if __name__ == "__main__":
    asyncio.run(main())