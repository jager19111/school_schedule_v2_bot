# tests/test_callback_protocol.py
#
# Тесты протокола CallbackData: целостность нового формата.
#
# Интроспекция aiogram defensively: имя атрибута prefix зависит
# от версии aiogram, поэтому сначала перебираются известные имена,
# затем fallback через pack() реального экземпляра.
#
# Запуск: pytest tests/test_callback_protocol.py -v

from __future__ import annotations

from pathlib import Path

from aiogram.filters.callback_data import CallbackData

import bot.callbacks as callbacks

REPO_ROOT = Path(__file__).resolve().parent.parent
TELEGRAM_CALLBACK_LIMIT = 64


def _all_cd_classes() -> dict[str, type[CallbackData]]:
    found = {}
    for name in dir(callbacks):
        obj = getattr(callbacks, name)
        if isinstance(obj, type) and issubclass(obj, CallbackData) and obj is not CallbackData:
            found[name] = obj
    return found


def _sample_kwargs(cls: type[CallbackData]) -> dict:
    kwargs = {}
    for field_name, annotation in cls.__annotations__.items():
        if annotation is int:
            kwargs[field_name] = 42
        else:
            kwargs[field_name] = "016"
    return kwargs


def _cd_prefix(cls: type[CallbackData]) -> str:
    for attr in ("callback_prefix", "__callback_prefix__", "__prefix__", "prefix"):
        value = getattr(cls, attr, None)
        if isinstance(value, str) and value:
            return value
    # Fallback: pack реального экземпляра и взять первый сегмент.
    return cls(**_sample_kwargs(cls)).pack().split(":")[0]


def _all_static_constants() -> dict[str, str]:
    out = {}
    for name in dir(callbacks):
        if name.isupper() and isinstance(getattr(callbacks, name), str):
            out[name] = getattr(callbacks, name)
    return out


def test_no_colon_inside_prefixes():
    """`:` зарезервирован aiogram как разделитель."""
    bad = [
        f"{name}={_cd_prefix(cls)!r}"
        for name, cls in _all_cd_classes().items()
        if ":" in _cd_prefix(cls)
    ]
    assert not bad, f"Префиксы содержат `:`: {bad}"


def test_prefixes_unique():
    seen: dict[str, str] = {}
    for name, cls in _all_cd_classes().items():
        prefix = _cd_prefix(cls)
        assert prefix, f"{name} без prefix"
        assert prefix not in seen, f"Дубликат prefix {prefix!r}: {name} и {seen[prefix]}"
        seen[prefix] = name


def test_prefixes_do_not_shadow_each_other():
    ordered = sorted(
        _all_cd_classes().items(), key=lambda kv: len(_cd_prefix(kv[1]))
    )
    for i, (first_name, first) in enumerate(ordered):
        for second_name, second in ordered[i + 1:]:
            assert not _cd_prefix(second).startswith(_cd_prefix(first)), (
                f"prefix {first_name}({_cd_prefix(first)!r}) тенит "
                f"{second_name}({_cd_prefix(second)!r})"
            )


def test_static_constants_short_unique_and_not_colliding():
    constants = _all_static_constants()
    assert constants, "в callbacks.py нет статических констант"
    values = list(constants.values())
    assert len(values) == len(set(values)), "дубликаты значений статических констант"
    prefixes = {_cd_prefix(cls) for cls in _all_cd_classes().values()}
    for const_name, value in constants.items():
        assert ":" not in value, f"{const_name}={value!r} содержит `:`"
        assert value not in prefixes, (
            f"{const_name}={value!r} конфликтует с prefix параметризованного callback"
        )


def test_required_constants_present():
    required = {
        "SETTINGS_MAIN", "SETTINGS_FAMILY", "SETTINGS_NOTIFICATIONS",
        "STUDENT_ADD", "FAMILY_STUDENTS", "FAMILY_INVITE_MENU",
        "WATCH_MENU", "WATCH_ADD", "EXTRA_STUDENTS", "EXTRA_CANCEL",
        "SCHEDULE_TARGETS", "SCHEDULE_SMART_DAY", "SEARCH_BACK",
        "AUTH_RESTART", "SET_NOTIF_CHANGES", "CLAIM_CANCEL",
    }
    missing = required - set(_all_static_constants())
    assert not missing, f"отсутствуют константы: {sorted(missing)}"


def test_roundtrip_all_cd_classes():
    """pack -> unpack возвращает исходные значения для КАЖДОГО класса."""
    classes = _all_cd_classes()
    assert len(classes) >= 30, f"подозрительно мало CD-классов: {len(classes)}"
    for name, cls in classes.items():
        kwargs = _sample_kwargs(cls)
        packed = cls(**kwargs).pack()
        parsed = cls.unpack(packed)
        for field_name, value in kwargs.items():
            assert getattr(parsed, field_name) == value, (
                f"{name}.{field_name}: {getattr(parsed, field_name)!r} != {value!r}"
            )


def test_nika_ids_survive_roundtrip():
    """ID NIKA — строго str: '016' не должен превращаться в '16'."""
    cases = [
        (callbacks.StudentEditClassCD, {"student_id": 42, "class_id": "016"}),
        (callbacks.RegistrationClassCD, {"class_id": "016"}),
        (callbacks.WatchGroupCD, {"group_id": "ALL"}),
        (callbacks.TeacherChangeCD, {"teacher_id": "031"}),
        (callbacks.SearchClassDayCD, {"class_id": "016", "date_iso": "2026-09-11"}),
    ]
    for cls, kwargs in cases:
        packed = cls(**kwargs).pack()
        parsed = cls.unpack(packed)
        for field_name, value in kwargs.items():
            assert getattr(parsed, field_name) == value, (
                f"{cls.__name__}.{field_name}: {getattr(parsed, field_name)!r} != {value!r}"
            )


def test_packed_size_within_telegram_limit():
    """Максимально длинные валидные payload не превышают 64 байта."""
    worst_cases = [
        callbacks.SearchTeacherFullWeekCD(
            teacher_id="999", week_start_iso="2026-09-14",
        ).pack(),
        callbacks.StudentEditClassCD(student_id=999999, class_id="016").pack(),
        callbacks.AdultExtraPermissionToggleCD(
            student_id=999999, adult_user_id=999999999,
        ).pack(),
        callbacks.SearchClassFullWeekCD(
            class_id="016", week_start_iso="2026-09-14",
        ).pack(),
    ]
    for packed in worst_cases:
        assert len(packed.encode("utf-8")) <= TELEGRAM_CALLBACK_LIMIT, (
            f"callback_data превышает лимит Telegram: {packed!r}"
        )


def test_unpack_rejects_foreign_prefix():
    """unpack чужого формата либо падает, либо не выдаёт чужие данные."""
    packed = callbacks.RegistrationClassCD(class_id="016").pack()
    try:
        parsed = callbacks.RegistrationGroupCD.unpack(packed)
    except Exception:
        return
    assert parsed.group_id != "016", "unpack принял чужой prefix как свой"


def test_keyboard_uses_pack_only():
    """keyboard.py не должен строить callback_data вручную."""
    keyboard_path = REPO_ROOT / "bot" / "keyboards" / "keyboard.py"
    source = keyboard_path.read_text(encoding="utf-8")
    for lineno, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for banned in ("callback_data=f\"", "callback_data='", ".split("):
            assert banned not in line, (
                f"keyboard.py:{lineno}: ручная сборка callback_data: {stripped}"
            )
