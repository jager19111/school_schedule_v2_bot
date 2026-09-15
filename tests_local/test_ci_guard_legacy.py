# tests/test_guard_legacy.py
#
# Guard-тест: защищает проект от возврата legacy callback-протокола.
# Падает, если в bot/, services/, core/ появились:
#   callbacks.parse_*, callbacks.build_*,
#   F.data.startswith(...), callback.data.split(...),
#   литеральные префиксы старого протокола ("role:", "sched:", ...)
# а также если fallback-роутер перестал быть последним в main.py.
#
# Запуск: pytest tests/test_guard_legacy.py -v

from __future__ import annotations

import importlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = [REPO_ROOT / "bot", REPO_ROOT / "services", REPO_ROOT / "core"]
MAIN_PY = REPO_ROOT / "main.py"

BANNED_SUBSTRINGS = [
    "callbacks.parse_",
    "callbacks.build_",
    "F.data.startswith(",
    "callback.data.split(",
]

# Литеральные префиксы старого протокола (проверяются вне комментариев).
OLD_LITERAL_PREFIXES = [
    '"role:', '"class:', '"group:', '"reg_teacher:', '"help:',
    '"family:create', '"family:join', '"family:skip',
    '"family:invite', '"family:students',
    '"claim:', '"student:', '"student_tg:', '"student_perm:', '"psn:',
    '"extra:', '"extraday:', '"edit_ext:', '"skip_location', '"skip_reminder',
    '"sched:', '"teacher_sched:', '"teacher_change:',
    '"srch_cls:', '"srch_tch:', '"sch_c', '"sch_t',
    '"settings:', '"set_notif:', '"set_time:', '"auth:',
    '"watch:', '"self_edit:',
]

HANDLER_MODULES = [
    "bot.callbacks",
    "bot.keyboards.keyboard",
    "bot.handlers.registration",
    "bot.handlers.help",
    "bot.handlers.admin",
    "bot.handlers.fallback",
    "bot.handlers.schedule_child",
    "bot.handlers.schedule_teacher",
    "bot.handlers.search",
    "bot.handlers.settings",
    "bot.handlers.extra_classes",
]


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        files.extend(p for p in scan_dir.rglob("*.py") if not p.name.endswith(".bak"))
    return sorted(files)


def test_no_legacy_callback_calls():
    violations: list[str] = []
    for path in iter_python_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for banned in BANNED_SUBSTRINGS:
                if banned in line:
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {banned} -> {line.strip()}")
    assert not violations, "Обнаружен legacy callback-код:\n" + "\n".join(violations)


def test_no_old_literal_prefixes():
    violations: list[str] = []
    for path in iter_python_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for prefix in OLD_LITERAL_PREFIXES:
                if prefix in line:
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {prefix} -> {stripped}")
    assert not violations, "Обнаружены литералы старого протокола:\n" + "\n".join(violations)


def test_fallback_router_is_last():
    assert MAIN_PY.exists(), "main.py не найден"
    source = MAIN_PY.read_text(encoding="utf-8")
    routers = re.findall(r"include_router\(\s*(\w+)\.router", source)
    assert routers, "не найдено ни одного include_router в main.py"
    assert routers[-1] == "fallback", (
        f"fallback должен регистрироваться последним, фактически: {routers}"
    )


def test_handler_modules_importable():
    problems: list[str] = []
    for module_name in HANDLER_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 — тесту нужен любой сбой импорта
            problems.append(f"{module_name}: {exc!r}")
    assert not problems, "Модули не импортируются:\n" + "\n".join(problems)
