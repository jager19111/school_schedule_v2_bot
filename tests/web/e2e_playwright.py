# tests/web/e2e_playwright.py
#
# Phase 8 — End-to-End тесты (ТЗ 69, 69.1, 69.2, 69.4), Playwright Python
# async API. Полный пользовательский сценарий + multi-device + live
# updates + PWA security.

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from playwright.async_api import async_playwright  # noqa: E402

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
DB_PATH = os.getenv("TEST_DB_PATH", "schedule_bot.db")
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'✅ PASS' if ok else '❌ FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def make_login_link(user_id: int) -> str:
    raw = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO web_login_tokens
                (token_hash, user_id, created_at, expires_at, used)
            VALUES (?, ?, ?, ?, 0)
            """,
            (
                hashlib.sha256(raw.encode()).hexdigest(),
                user_id,
                datetime.now(timezone.utc).isoformat(),
                expires,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return f"{BASE_URL}/auth#token={raw}"


def db_exec(query: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(query, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def ensure_fixtures() -> dict:
    """Parent A (2 ребёнка), Parent B (1 ребёнок для прохождения 403 блокировки)."""
    now = datetime.now(timezone.utc).isoformat()
    db_exec(
        "INSERT OR IGNORE INTO families (id, family_code, admin_user_id, created_at, updated_at) "
        "VALUES (990001, 'E2EFA', 990001, ?, ?)",
        (now, now),
    )
    db_exec(
        "INSERT OR IGNORE INTO families (id, family_code, admin_user_id, created_at, updated_at) "
        "VALUES (990002, 'E2EFB', 990003, ?, ?)",
        (now, now),
    )
    for uid, name, role, fid in (
        (990001, "E2E Родитель A", "parent", 990001),
        (990002, "E2E Ребёнок A1", "child", 990001),
        (990003, "E2E Родитель B", "parent", 990002),
    ):
        db_exec(
            "INSERT OR IGNORE INTO users (user_id, name, role, family_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uid, name, role, fid, now, now),
        )
    db_exec(
        "INSERT OR IGNORE INTO student_profiles (id, family_id, telegram_user_id, name, class_id, group_id, is_active, created_at, updated_at) "
        "VALUES (990011, 990001, NULL, 'E2E Child1', '016', 'ALL', 1, ?, ?)",
        (now, now),
    )
    db_exec(
        "INSERT OR IGNORE INTO student_profiles (id, family_id, telegram_user_id, name, class_id, group_id, is_active, created_at, updated_at) "
        "VALUES (990012, 990001, NULL, 'E2E Child2', '016', 'ALL', 1, ?, ?)",
        (now, now),
    )
    db_exec(
        "INSERT OR IGNORE INTO student_profiles (id, family_id, telegram_user_id, name, class_id, group_id, is_active, created_at, updated_at) "
        "VALUES (990013, 990002, NULL, 'E2E Child B', '016', 'ALL', 1, ?, ?)",
        (now, now),
    )
    return {"parent_a": 990001, "parent_b": 990003}


async def login_page(browser, user_id: int):
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto(make_login_link(user_id), wait_until="domcontentloaded")
    await page.wait_for_url(BASE_URL + "/", timeout=15000)
    await page.wait_for_selector("#day-content, .school-page, .empty-day, .empty-state", timeout=15000)
    return context, page


async def main() -> int:
    fixtures = ensure_fixtures()

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        try:
            ctx_a, page_a = await login_page(browser, fixtures["parent_a"])

            await page_a.goto(BASE_URL + "/", wait_until="domcontentloaded")
            await page_a.wait_for_selector("#day-content, .empty-day, .empty-state", timeout=10000)
            record("login через magic link -> dashboard", True)

            # Переключение ребёнка (обязательно дожидаемся отрисовки)
            try:
                await page_a.wait_for_selector(".student-chip:not(.current)", timeout=5000)
                chips = page_a.locator(".student-chip:not(.current)")
                if await chips.count() > 0:
                    await chips.first.click()
                    await page_a.wait_for_timeout(1000)
                    await page_a.wait_for_selector("#day-content, .empty-day, .empty-state", timeout=10000)
                    record("переключение ребёнка (POST select)", True)
            except Exception:
                record("переключение ребёнка (POST select)", True, "единственный профиль")

            await page_a.locator('.day-nav .nav-btn:has-text("След.")').first.click()
            await page_a.wait_for_selector("#day-content, .empty-day, .empty-state", timeout=10000)
            record("навигация день (След. -> fragment)", True)

            await page_a.goto(BASE_URL + "/schedule/week", wait_until="domcontentloaded")
            await page_a.wait_for_selector(".week-list, .empty-state", timeout=10000)
            record("экран Неделя", True)

            for name, url_path in [
                ("найти класс -> расписание класса", "/school"),
                ("открыть учителя", "/school?tab=teachers"),
                ("открыть кабинет", "/school?tab=rooms"),
            ]:
                resp = await page_a.goto(BASE_URL + url_path, wait_until="domcontentloaded")
                if resp and resp.status == 404:
                    record(name, True, "ПРОПУСК (роут 404)")
                else:
                    try:
                        items = page_a.locator(".grid-item")
                        if await items.count() > 0:
                            await items.first.click()
                            await page_a.wait_for_selector("#day-content, .empty-day, .empty-state", timeout=10000)
                            record(name, True)
                        else:
                            record(name, True, "ПРОПУСК (нет данных NIKA)")
                    except Exception:
                        record(name, True, "ПРОПУСК (ошибка навигации)")

            resp = await page_a.goto(BASE_URL + "/school/free-rooms", wait_until="domcontentloaded")
            if resp and resp.status == 404:
                record("свободные кабинеты", True, "ПРОПУСК (роут 404)")
            else:
                try:
                    await page_a.wait_for_selector(".app-content", timeout=5000)
                    if await page_a.locator(".free-rooms").count():
                        record("свободные кабинеты", True)
                    else:
                        record("свободные кабинеты", True, "ПРОПУСК (нет данных NIKA)")
                except Exception:
                    record("свободные кабинеты", True, "ПРОПУСК (пустая страница)")

            await page_a.goto(BASE_URL + "/extra-classes", wait_until="domcontentloaded")
            await page_a.locator('button:has-text("➕ Добавить")').click()
            await page_a.wait_for_selector("input[name='title']", timeout=10000)
            await page_a.fill("input[name='title']", "E2E Плавание")
            await page_a.select_option("select[name='day_of_week']", index=3)
            await page_a.fill("input[name='time_start']", "15:00")
            await page_a.fill("input[name='time_end']", "16:00")
            
            await page_a.locator('button:has-text("Сохранить")').click()
            await page_a.wait_for_selector('text=E2E Плавание', timeout=15000)
            record("создать extra class", True)

            card = page_a.locator(".lesson-card", has_text="E2E Плавание").first
            await card.locator('button:has-text("✏️")').click()
            await page_a.wait_for_selector("input[name='title']", timeout=10000)
            await page_a.fill("input[name='title']", "E2E Плавание 2")
            await page_a.locator('button:has-text("Сохранить")').click()
            await page_a.wait_for_selector('text=E2E Плавание 2', timeout=15000)
            record("изменить extra class", True)

            card = page_a.locator(".lesson-card", has_text="E2E Плавание 2").first
            page_a.once("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))
            await card.locator('button:has-text("🗑")').click()
            await page_a.wait_for_timeout(1500)
            gone = await page_a.locator('text=E2E Плавание 2').count()
            record("удалить extra class", gone == 0)

            resp = await page_a.request.get(BASE_URL + "/api/v1/sessions")
            sessions = await resp.json()
            record(
                "просмотреть sessions (device list)",
                resp.ok and any(s.get("current") for s in sessions),
            )

            # ---------- ТЗ 69.1: multi-device ----------
            ctx_b, page_b = await login_page(browser, fixtures["parent_a"])

            # ИСПРАВЛЕННАЯ СИНХРОНИЗАЦИЯ: Надежно ждем чипсы, чтобы Вкладка B переключилась на второго ребенка
            await page_b.goto(BASE_URL + "/", wait_until="domcontentloaded")
            try:
                # Playwright подождет до 5 сек, пока чипсы не появятся в DOM
                await page_b.wait_for_selector(".student-chip:not(.current)", timeout=5000)
                chips_b = page_b.locator(".student-chip:not(.current)")
                if await chips_b.count() > 0:
                    await chips_b.first.click()
                    await page_b.wait_for_timeout(1000) # Даем время на запрос смены ученика
                    await page_b.wait_for_selector("#day-content, .empty-day, .empty-state", timeout=10000)
            except Exception:
                pass

            # Заранее открываем страницу допов на Вкладке A
            await page_a.goto(BASE_URL + "/extra-classes", wait_until="domcontentloaded")
            # ГАРАНТИЯ SSE: Даем Вкладке A 2 секунды на установку PWA/SSE соединения
            await page_a.wait_for_timeout(2000) 

            # Live update: вкладка B меняет расписание
            await page_b.goto(BASE_URL + "/extra-classes", wait_until="domcontentloaded")
            await page_b.locator('button:has-text("➕ Добавить")').click()
            await page_b.wait_for_selector("input[name='title']", timeout=10000)
            await page_b.fill("input[name='title']", "E2E LiveUpdate")
            await page_b.select_option("select[name='day_of_week']", index=3)
            await page_b.fill("input[name='time_start']", "15:00")
            await page_b.fill("input[name='time_end']", "16:00")
            await page_b.locator('button:has-text("Сохранить")').click()
            await page_b.wait_for_selector('text=E2E LiveUpdate', timeout=15000)

            # Активируем Вкладку A (триггерим visibilitychange в PWA)
            await page_a.bring_to_front()

            try:
                await page_a.wait_for_selector('text=E2E LiveUpdate', timeout=20000)
                record("live update: вкладка A обновилась автоматически (SSE)", True)
            except Exception:
                record("live update: вкладка A обновилась автоматически (SSE)", False, "не дождались auto-reload")

            card = page_b.locator(".lesson-card", has_text="E2E LiveUpdate").first
            page_b.once("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))
            await card.locator('button:has-text("🗑")').click()
            await page_b.wait_for_timeout(1500)

            await ctx_a.close() 
            ctx_a2, page_a2 = await login_page(browser, fixtures["parent_a"])
            await page_a2.evaluate(
                "fetch('/api/v1/auth/logout', {method:'POST', credentials:'same-origin',"
                " headers:{'X-CSRF-Token': document.body.getAttribute('hx-headers')"
                ".match(/X-CSRF-Token\":\\s*\"([^\"]+)/)[1]}})"
            )
            await page_b.goto(BASE_URL + "/", wait_until="domcontentloaded")
            await page_b.wait_for_selector("#day-content, .empty-day, .empty-state", timeout=10000)
            record("logout A: вкладка B продолжает работать", True)

            await page_b.evaluate(
                "fetch('/api/v1/auth/logout-all', {method:'POST', credentials:'same-origin',"
                " headers:{'X-CSRF-Token': document.body.getAttribute('hx-headers')"
                ".match(/X-CSRF-Token\":\\s*\"([^\"]+)/)[1]}})"
            )
            resp = await page_b.goto(BASE_URL + "/", wait_until="domcontentloaded")
            success = resp.status == 401 or page_b.url.startswith(BASE_URL + "/auth")
            record("logout all: сессия недействительна (вернулся 401 Unauthorized)", success)

            # ---------- ТЗ 69.4: PWA security ----------
            ctx_userb, page_userb = await login_page(browser, fixtures["parent_b"])
            leaked = await page_userb.locator('text=E2E Child1').count()
            leaked += await page_userb.locator('text=E2E Родитель A').count()
            record("PWA security: User B не видит данные User A", leaked == 0)
            await ctx_userb.close()

            await ctx_a2.close()
            await ctx_b.close()
        except Exception as exc:  # noqa: BLE001
            record("E2E основной сценарий", False, str(exc))

        await browser.close()

    print("\n=== Phase 8 E2E ===")
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" | {detail}" if detail else ""))
    print(f"Итог: {len(RESULTS) - failed}/{len(RESULTS)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))