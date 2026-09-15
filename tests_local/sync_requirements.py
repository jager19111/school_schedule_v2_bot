# sync_requirements.py
#
# Этап «Аудит», пункт 3: requirements.txt из фактических импортов
# кода и фактически установленных версий окружения.
#
# Что делает:
# 1. Сканирует import-ы во всём коде проекта (bot/, core/, services/,
#    database/, main.py, config.py); tests/ — отдельно, как dev-зависимости.
# 2. Отбрасывает стандартную библиотеку и локальные пакеты проекта.
# 3. Сопоставляет имя импорта с дистрибутивом (aiosqlite, APScheduler,
#    python-dotenv и т.п.) и берёт фактическую установленную версию.
# 4. Пишет requirements.txt (runtime) и requirements-dev.txt (только тесты),
#    печатает пакеты из старого requirements, которые код больше
#    нигде не импортирует (кандидаты на удаление).
#
# Запись происходит ТОЛЬКО если все найденные зависимости установлены
# в текущем окружении — иначе молчаливая потеря была бы хуже неверной версии.
#
# Запуск из корня репозитория: python sync_requirements.py

from __future__ import annotations

import ast
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

REPO = Path(__file__).resolve().parent

RUNTIME_PATHS = [
    REPO / "bot", REPO / "core", REPO / "services",
    REPO / "database", REPO / "main.py", REPO / "config.py",
]

IMPORT_TO_DIST = {
    "aiogram": "aiogram",
    "aiohttp": "aiohttp",
    "aiosqlite": "aiosqlite",
    "apscheduler": "APScheduler",
    "dotenv": "python-dotenv",
    "bs4": "beautifulsoup4",
    "requests": "requests",
    "pytest": "pytest",
    "pytest_asyncio": "pytest-asyncio",
}

LOCAL_PACKAGES = {"bot", "core", "services", "database", "config"}


def collect_imports(paths) -> tuple[set[str], int]:
    found: set[str] = set()
    scanned = 0
    for path in paths:
        files = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for file in files:
            if file.name.endswith(".bak") or not file.exists():
                continue
            scanned += 1
            try:
                tree = ast.parse(file.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                raise SystemExit(f"{file}: SyntaxError: {exc}")
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    found.add(node.module.split(".")[0])
    if scanned == 0:
        raise SystemExit(
            "Не найдено ни одного .py в ожидаемых путях. "
            "Запусти скрипт из корня репозитория: python sync_requirements.py"
        )
    return found, scanned


def resolve(imported: set[str]) -> tuple[list[tuple[str, str, str]], list[str]]:
    """-> ([(имя_импорта, дистрибутив, версия)], [неустановленные])."""
    resolved: list[tuple[str, str, str]] = []
    missing: list[str] = []
    for module in sorted(imported):
        if module in sys.stdlib_module_names or module in LOCAL_PACKAGES:
            continue
        dist = IMPORT_TO_DIST.get(module, module)
        try:
            resolved.append((module, dist, version(dist)))
        except PackageNotFoundError:
            missing.append(dist)
    return resolved, missing


def main() -> None:
    existing = [p for p in RUNTIME_PATHS if p.exists()]
    missing_paths = [p.name for p in RUNTIME_PATHS if not p.exists()]
    if missing_paths:
        print(f"ПРЕДУПРЕЖДЕНИЕ: не найдены: {', '.join(missing_paths)}")

    runtime, scanned_runtime = collect_imports(existing)
    dev, _ = (
        collect_imports([REPO / "tests"]) if (REPO / "tests").exists()
        else (set(), 0)
    )

    print(f"=== Найденные импорты (runtime: {scanned_runtime} файлов) ===")
    print("runtime:", ", ".join(sorted(runtime)))
    print("tests:  ", ", ".join(sorted(dev)))

    runtime_resolved, runtime_missing = resolve(runtime)
    dev_resolved, dev_missing = resolve(dev - runtime)

    print("\n=== Runtime-зависимости (фактические версии) ===")
    lines = []
    for module, dist, ver in runtime_resolved:
        lines.append(f"{dist}=={ver}")
        print(f"  {dist}=={ver}   (import {module})")

    print("\n=== Dev-зависимости (только тесты) ===")
    dev_lines = []
    for module, dist, ver in dev_resolved:
        dev_lines.append(f"{dist}=={ver}")
        print(f"  {dist}=={ver}   (import {module})")

    all_missing = sorted(set(runtime_missing) | set(dev_missing))
    if all_missing:
        print("\nОШИБКА: пакеты импортируются кодом, но НЕ установлены "
              "в текущем окружении:", ", ".join(all_missing))
        print("Установи их (pip install ...) и перезапусти скрипт — "
              "иначе requirements.txt потерял бы зависимости.")
        raise SystemExit(1)

    new_map = {line.split("==")[0].lower(): line.split("==")[1]
               for line in lines}
    old_req = REPO / "requirements.txt"
    if old_req.exists():
        old = {}
        for line in old_req.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                name, _, ver = line.partition("==")
                old[name.strip().lower()] = ver.strip()
        dropped = [n for n in old if n not in new_map]
        if dropped:
            print("\n=== В старом requirements, но код больше не импортирует ===")
            for name in dropped:
                print(f"  {name}=={old[name]}  -> кандидат на удаление")
        changed = [(n, old[n], new_map[n]) for n in old
                   if n in new_map and old[n] != new_map[n]]
        if changed:
            print("\n=== Версии изменятся ===")
            for name, was, now in changed:
                print(f"  {name}: {was} -> {now}")

    (REPO / "requirements.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    (REPO / "requirements-dev.txt").write_text(
        "\n".join(dev_lines) + "\n", encoding="utf-8"
    )
    print(f"\nOK: requirements.txt ({len(lines)} runtime) и "
          f"requirements-dev.txt ({len(dev_lines)} dev) записаны.")
    print("Проверь git diff requirements.txt перед коммитом.")


if __name__ == "__main__":
    main()
