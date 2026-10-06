from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

BASE_TEMPLATE = ROOT / "web/templates/base.html"
SERVICE_WORKER = ROOT / "web/static/service-worker.js"

CACHE_VERSION_PATTERN = re.compile(
    r'(const CACHE_VERSION = "school-schedule-shell-v)(\d+)(";)',
)

ASSET_VERSION_PATTERN = re.compile(
    r"(\?v=)(\d+)",
)


def read_current_version(service_worker_text: str) -> int:
    match = CACHE_VERSION_PATTERN.search(service_worker_text)

    if match is None:
        raise RuntimeError(
            "Не найден CACHE_VERSION вида "
            'const CACHE_VERSION = "school-schedule-shell-vN";'
        )

    return int(match.group(2))


def replace_versions(text: str, version: int) -> str:
    return ASSET_VERSION_PATTERN.sub(
        lambda match: f"{match.group(1)}{version}",
        text,
    )


def main() -> None:
    if len(sys.argv) > 2:
        raise SystemExit(
            "Использование: python scripts/bump_pwa_version.py [VERSION]"
        )

    base_text = BASE_TEMPLATE.read_text(encoding="utf-8")
    worker_text = SERVICE_WORKER.read_text(encoding="utf-8")

    current_version = read_current_version(worker_text)

    new_version = (
        int(sys.argv[1])
        if len(sys.argv) == 2
        else current_version + 1
    )

    if new_version <= current_version:
        raise SystemExit(
            f"Новая версия должна быть больше {current_version}."
        )

    updated_base = replace_versions(base_text, new_version)
    updated_worker = replace_versions(worker_text, new_version)

    updated_worker = CACHE_VERSION_PATTERN.sub(
        rf"\g<1>{new_version}\g<3>",
        updated_worker,
        count=1,
    )

    BASE_TEMPLATE.write_text(
        updated_base,
        encoding="utf-8",
    )

    SERVICE_WORKER.write_text(
        updated_worker,
        encoding="utf-8",
    )

    print(
        f"PWA build version: {current_version} -> {new_version}"
    )
    print(f"Updated: {BASE_TEMPLATE.relative_to(ROOT)}")
    print(f"Updated: {SERVICE_WORKER.relative_to(ROOT)}")


if __name__ == "__main__":
    main()