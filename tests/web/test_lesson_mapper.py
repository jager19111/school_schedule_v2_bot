from __future__ import annotations
from datetime import datetime

from core.models.dto import DayChangesDetailDTO, LessonDTO, ScheduleTargetDTO, ScheduleTargetKind
from web.mappers import changes_to_web, lesson_entry_to_web, lessons_to_web
from web.schemas import LessonKind, LessonStatus, LessonViewMode, WebLesson


def lesson(
    *,
    lesson_id: str = "lesson-1",
    date_iso: str = "2026-09-28",
    number: int = 4,
    start_time: str = "16:40",
    end_time: str = "17:20",
    subject: str = "Биология",
    teacher: str | None = "Потапова М.В.",
    group: str | None = "Группа 1",
    class_name: str | None = "6а",
    room: str | None = "305",
    is_exchange: bool = False,
    is_cancelled: bool = False,
    is_extra: bool = False,
    is_methodological: bool = False,
    original_subject: str | None = None,
    original_teacher: str | None = None,
    original_room: str | None = None,
) -> LessonDTO:
    return LessonDTO(
        id=lesson_id,
        date_iso=date_iso,
        lesson_num=number,
        start_time=start_time,
        end_time=end_time,
        subject_name=subject,
        teacher_name=teacher,
        group_name=group,
        class_name=class_name,
        room_name=room or "",
        is_exchange=is_exchange,
        is_cancelled=is_cancelled,
        is_extra=is_extra,
        is_methodological=is_methodological,
        original_subject_name=original_subject,
        original_teacher_name=original_teacher,
        original_room_name=original_room,
    )


def test_normal_student_lesson_is_typed() -> None:
    result = lessons_to_web(
        [lesson()],
        view_mode=LessonViewMode.STUDENT,
        show_profile_groups=False,
    )

    assert len(result) == 1
    assert isinstance(result[0], WebLesson)
    assert result[0].kind is LessonKind.REGULAR
    assert result[0].status is LessonStatus.NORMAL
    assert result[0].entries[0].subject.value == "Биология"
    assert result[0].entries[0].room.value == "305"


def test_long_subject_is_not_truncated_by_mapper() -> None:
    subject = "Основы естественно-научных исследований"
    result = lessons_to_web(
        [lesson(subject=subject)],
        view_mode=LessonViewMode.STUDENT,
        show_profile_groups=False,
    )

    assert result[0].entries[0].subject.value == subject


def test_empty_optional_values_become_none() -> None:
    entry = lesson_entry_to_web(
        lesson(
            teacher="",
            group="",
            class_name="",
            room="",
        ),
        view_mode=LessonViewMode.STUDENT,
        show_profile_groups=False,
    )

    assert entry.teacher is None
    assert entry.group is None
    assert entry.class_name is None
    assert entry.room is None


def test_same_subject_two_groups_keep_individual_rooms() -> None:
    result = lessons_to_web(
        [
            lesson(
                lesson_id="g1",
                group="Группа 1",
                room="230",
                subject="Английский",
            ),
            lesson(
                lesson_id="g2",
                group="Группа 2",
                room="324",
                subject="Английский",
            ),
        ],
        view_mode=LessonViewMode.CLASS,
        show_profile_groups=True,
    )

    assert len(result) == 1
    assert result[0].shared_subject is True
    assert [entry.room.value for entry in result[0].entries] == ["230", "324"]


def test_same_subject_three_groups_is_one_slot() -> None:
    result = lessons_to_web(
        [
            lesson(lesson_id="g1", group="Группа 1", room="230"),
            lesson(lesson_id="g2", group="Группа 2", room="324"),
            lesson(lesson_id="g3", group="Группа 3", room="325"),
        ],
        view_mode=LessonViewMode.CLASS,
        show_profile_groups=True,
    )

    assert len(result) == 1
    assert len(result[0].entries) == 3
    assert result[0].shared_subject is True


def test_different_subjects_remain_entries_in_one_slot() -> None:
    result = lessons_to_web(
        [
            lesson(
                lesson_id="g1",
                subject="Ин. язык",
                group="Группа 1",
                room="324а",
            ),
            lesson(
                lesson_id="g2",
                subject="Программирование",
                group="Группа 2",
                room="301",
            ),
        ],
        view_mode=LessonViewMode.CLASS,
        show_profile_groups=True,
    )

    assert len(result) == 1
    assert result[0].shared_subject is False
    assert [entry.subject.value for entry in result[0].entries] == [
        "Ин. язык",
        "Программирование",
    ]
    assert [entry.room.value for entry in result[0].entries] == ["324а", "301"]


def test_changed_subject_teacher_and_room_are_marked() -> None:
    entry = lesson_entry_to_web(
        lesson(
            subject="История",
            teacher="Петрова Е.В.",
            room="214",
            is_exchange=True,
            original_subject="Биология",
            original_teacher="Иванов И.И.",
            original_room="305",
        ),
        view_mode=LessonViewMode.STUDENT,
        show_profile_groups=False,
    )

    assert entry.subject.changed is True
    assert entry.teacher.changed is True
    assert entry.room.changed is True


def test_added_cancelled_and_extra_statuses() -> None:
    added = lessons_to_web(
        [
            lesson(
                is_exchange=True,
                original_subject=None,
            )
        ],
        view_mode=LessonViewMode.STUDENT,
        show_profile_groups=False,
    )[0]
    cancelled = lessons_to_web(
        [
            lesson(
                is_cancelled=True,
                room="305",
            )
        ],
        view_mode=LessonViewMode.STUDENT,
        show_profile_groups=False,
    )[0]
    extra = lessons_to_web(
        [
            lesson(
                lesson_id="extra-1",
                is_extra=True,
            )
        ],
        view_mode=LessonViewMode.STUDENT,
        show_profile_groups=False,
    )[0]

    assert added.status is LessonStatus.ADDED
    assert cancelled.status is LessonStatus.CANCELLED
    assert cancelled.entries[0].room is None
    assert extra.kind is LessonKind.EXTRA


def test_current_is_calculated_from_now_base() -> None:
    # Заменяем старый флаг is_current=True на вычисление из now_base
    result = lessons_to_web(
        [lesson(start_time="16:40", end_time="17:20", date_iso="2026-09-28")],
        view_mode=LessonViewMode.STUDENT,
        show_profile_groups=False,
        now_base=datetime(2026, 9, 28, 17, 0),
    )

    assert result[0].is_current is True


def test_teacher_two_classes_same_slot_are_aggregated() -> None:
    result = lessons_to_web(
        [
            lesson(
                lesson_id="teacher-1",
                class_name="6а",
                group="Группа 1",
                subject="Математика",
                room="201",
            ),
            lesson(
                lesson_id="teacher-2",
                class_name="6б",
                group="Группа 2",
                subject="Математика",
                room="201",
            ),
        ],
        view_mode=LessonViewMode.TEACHER,
        show_profile_groups=True,
    )

    assert len(result) == 1
    assert len(result[0].entries) == 2
    assert [
        entry.class_name.value
        for entry in result[0].entries
    ] == ["6а", "6б"]


def test_same_number_with_different_time_is_not_aggregated() -> None:
    result = lessons_to_web(
        [
            lesson(lesson_id="first", start_time="09:10", end_time="09:55"),
            lesson(lesson_id="second", start_time="10:15", end_time="11:00"),
        ],
        view_mode=LessonViewMode.TEACHER,
        show_profile_groups=True,
    )

    assert len(result) == 2


def test_changes_mapper_uses_existing_change_dto() -> None:
    target = ScheduleTargetDTO(
        kind=ScheduleTargetKind.STUDENT,
        selection_key="student:1",
        student_id=1,
        class_id="6a",
        group_id="1",
        name="Лиза",
    )
    dto = DayChangesDetailDTO(
        date_iso="2026-09-28",
        origin="class",
        lessons=[
            lesson(
                subject="История",
                is_exchange=True,
                original_subject="Биология",
            )
        ],
    )

    result = changes_to_web(dto, target=target)

    assert len(result.changes) == 1
    assert result.changes[0].lesson.status is LessonStatus.CHANGED
    assert result.changes[0].changes[0].field == "subject"
    assert result.changes[0].changes[0].old_value == "Биология"
    assert result.changes[0].changes[0].new_value == "История"


def test_teacher_three_classes_same_slot_are_aggregated() -> None:
    result = lessons_to_web(
        [
            lesson(
                lesson_id="teacher-1",
                class_name="6а",
                group="Группа 1",
                subject="Математика",
                room="201",
            ),
            lesson(
                lesson_id="teacher-2",
                class_name="6б",
                group="Группа 2",
                subject="Математика",
                room="201",
            ),
            lesson(
                lesson_id="teacher-3",
                class_name="7а",
                group="Группа 1",
                subject="Математика",
                room="201",
            ),
        ],
        view_mode=LessonViewMode.TEACHER,
        show_profile_groups=True,
    )

    assert len(result) == 1
    assert len(result[0].entries) == 3
    assert [
        entry.class_name.value
        for entry in result[0].entries
    ] == ["6а", "6б", "7а"]


def test_teacher_same_time_different_subjects_remain_separate_cards() -> None:
    result = lessons_to_web(
        [
            lesson(
                lesson_id="teacher-math",
                subject="Математика",
                class_name="6а",
                room="201",
            ),
            lesson(
                lesson_id="teacher-physics",
                subject="Физика",
                class_name="7а",
                room="201",
            ),
        ],
        view_mode=LessonViewMode.TEACHER,
        show_profile_groups=True,
    )

    assert len(result) == 2
    assert [
        item.entries[0].subject.value
        for item in result
    ] == ["Математика", "Физика"]


def test_teacher_same_time_different_rooms_remain_separate_cards() -> None:
    result = lessons_to_web(
        [
            lesson(
                lesson_id="teacher-room-201",
                subject="Математика",
                class_name="6а",
                room="201",
            ),
            lesson(
                lesson_id="teacher-room-202",
                subject="Математика",
                class_name="6б",
                room="202",
            ),
        ],
        view_mode=LessonViewMode.TEACHER,
        show_profile_groups=True,
    )

    assert len(result) == 2
    assert [
        item.entries[0].room.value
        for item in result
    ] == ["201", "202"]