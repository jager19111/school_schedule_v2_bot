from __future__ import annotations

from web.schemas import (
    LessonKind,
    LessonStatus,
    LessonViewMode,
    WebChange,
    WebChangeItem,
    WebChangedValue,
    WebLesson,
    WebLessonEntry,
    WebRoomBadge,
)


def _lesson(
    *,
    entries: list[WebLessonEntry] | None = None,
    kind: LessonKind = LessonKind.REGULAR,
    status: LessonStatus = LessonStatus.NORMAL,
) -> WebLesson:
    return WebLesson(
        key="lesson-2026-09-28-4",
        number=4,
        start_time="16:40",
        end_time="17:20",
        view_mode=LessonViewMode.STUDENT,
        kind=kind,
        status=status,
        entries=entries or [],
        shared_subject=False,
        history_url=None,
        aria_label="Урок 4. 16:40–17:20.",
    )


def test_lesson_enums_have_stable_values() -> None:
    assert LessonViewMode.STUDENT.value == "student"
    assert LessonViewMode.CLASS.value == "class"
    assert LessonViewMode.TEACHER.value == "teacher"
    assert LessonViewMode.ROOM.value == "room"

    assert LessonKind.REGULAR.value == "regular"
    assert LessonKind.EXTRA.value == "extra"
    assert LessonKind.WINDOW.value == "window"

    assert LessonStatus.NORMAL.value == "normal"
    assert LessonStatus.CHANGED.value == "changed"
    assert LessonStatus.ADDED.value == "added"
    assert LessonStatus.CANCELLED.value == "cancelled"


def test_changed_value_contract() -> None:
    unchanged = WebChangedValue(value="Биология")
    changed = WebChangedValue(value="История", changed=True)
    empty = WebChangedValue()

    assert unchanged.value == "Биология"
    assert unchanged.changed is False
    assert changed.value == "История"
    assert changed.changed is True
    assert empty.value is None
    assert empty.changed is False


def test_room_badge_supports_numeric_and_text_rooms() -> None:
    numeric_room = WebRoomBadge(value="305")
    text_room = WebRoomBadge(value="спортзал")
    changed_room = WebRoomBadge(value="214", changed=True)

    assert numeric_room.value == "305"
    assert text_room.value == "спортзал"
    assert changed_room.changed is True


def test_lesson_entry_keeps_room_at_entry_level() -> None:
    first_entry = WebLessonEntry(
        subject=WebChangedValue(value="Английский"),
        group=WebChangedValue(value="Группа 1"),
        room=WebRoomBadge(value="230"),
    )
    second_entry = WebLessonEntry(
        subject=WebChangedValue(value="Английский"),
        group=WebChangedValue(value="Группа 2"),
        room=WebRoomBadge(value="324"),
    )

    lesson = _lesson(entries=[first_entry, second_entry])

    assert lesson.entries[0].room is not None
    assert lesson.entries[0].room.value == "230"
    assert lesson.entries[1].room is not None
    assert lesson.entries[1].room.value == "324"
    assert lesson.entries[0].room.value != lesson.entries[1].room.value


def test_web_lesson_has_only_typed_entries() -> None:
    lesson = _lesson(
        entries=[
            WebLessonEntry(
                subject=WebChangedValue(value="Биология"),
                teacher=WebChangedValue(value="Потапова М.В."),
                room=WebRoomBadge(value="305"),
            )
        ]
    )

    assert isinstance(lesson.entries, list)
    assert isinstance(lesson.entries[0], WebLessonEntry)
    assert not isinstance(lesson.entries[0], dict)


def test_web_lesson_supports_current_extra_and_cancelled_states() -> None:
    extra = _lesson(kind=LessonKind.EXTRA)
    current = _lesson()
    current.is_current = True
    cancelled = _lesson(status=LessonStatus.CANCELLED)

    assert extra.kind is LessonKind.EXTRA
    assert current.is_current is True
    assert cancelled.status is LessonStatus.CANCELLED


def test_web_change_contract() -> None:
    change = WebChange(
        field="room",
        old_value="305",
        new_value="214",
        changed_at="2026-09-28T08:00:00+07:00",
    )

    assert change.field == "room"
    assert change.old_value == "305"
    assert change.new_value == "214"


def test_web_change_item_contains_current_lesson_and_changes() -> None:
    lesson = _lesson(
        status=LessonStatus.CHANGED,
        entries=[
            WebLessonEntry(
                subject=WebChangedValue(value="История", changed=True),
                room=WebRoomBadge(value="214", changed=True),
            )
        ],
    )

    item = WebChangeItem(
        lesson=lesson,
        changes=[
            WebChange(
                field="subject",
                old_value="Биология",
                new_value="История",
            ),
            WebChange(
                field="room",
                old_value="305",
                new_value="214",
            ),
        ],
    )

    assert item.lesson.status is LessonStatus.CHANGED
    assert len(item.changes) == 2
    assert item.changes[0].field == "subject"
    assert item.changes[1].field == "room"


def test_web_lesson_default_lists_are_not_shared() -> None:
    first = _lesson()
    second = _lesson()

    first.entries.append(
        WebLessonEntry(
            subject=WebChangedValue(value="Математика"),
        )
    )

    assert len(first.entries) == 1
    assert second.entries == []