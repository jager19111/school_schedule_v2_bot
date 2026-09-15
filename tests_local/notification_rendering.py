# tests/test_notification_rendering.py
#
# Тесты рендеринга уведомлений: то, что видит пользователь,
# обязано быть непустым, информативным и HTML-безопасным.
#
# Проверяется УИ-слой без Telegram и БД: только DTO + UIRenderer.
# Если тест падает после правки UI — Regression поймана до пользователей.
#
# Запуск: pytest tests/test_notification_rendering.py -v

from __future__ import annotations

from bot.utils.ui_renderer import UIRenderer
from core.models.dto import (
    ChangeReminderDTO,
    LessonReminderDTO,
    MorningLessonDTO,
    MorningSummaryDTO,
)


def _sample_morning(child_name: str | None) -> MorningSummaryDTO:
    return MorningSummaryDTO(
        date_iso="2026-09-11",
        lessons=[
            MorningLessonDTO(
                lesson_num=1,
                start_time="08:30",
                end_time="09:15",
                subject_name="Математика",
                room_name="204",
                is_cancelled=False,
                is_exchange=False,
                is_extra=False,
                group_name=None,
            ),
            MorningLessonDTO(
                lesson_num=2,
                start_time="09:25",
                end_time="10:10",
                subject_name="Физика",
                room_name="112",
                is_cancelled=True,
                is_exchange=False,
                is_extra=False,
                group_name=None,
            ),
            MorningLessonDTO(
                lesson_num=3,
                start_time="10:25",
                end_time="11:10",
                subject_name="Английский (подгруппа 2)",
                room_name="305",
                is_cancelled=False,
                is_exchange=True,
                is_extra=False,
                group_name="2",
            ),
            MorningLessonDTO(
                lesson_num=None,
                start_time="16:00",
                end_time="17:00",
                subject_name="Плавание",
                room_name="Бассейн",
                is_cancelled=False,
                is_exchange=False,
                is_extra=True,
                group_name=None,
            ),
        ],
        child_name=child_name,
        class_id="9А",
    )


def test_morning_summary_child_view_not_empty():
    text = UIRenderer.render_morning_summary(_sample_morning(child_name=None))
    assert isinstance(text, str) and text.strip(), "Сводка для ребёнка пуста"


def test_morning_summary_parent_view_contains_child_name():
    text = UIRenderer.render_morning_summary(_sample_morning(child_name="Маша"))
    assert "Маша" in text, "В сводке для родителя нет имени ребёнка"


def test_morning_summary_contains_all_lessons():
    text = UIRenderer.render_morning_summary(_sample_morning(child_name=None))
    for subject in ("Математика", "Физика", "Английский", "Плавание"):
        assert subject in text, f"В сводке нет предмета: {subject}"


def test_morning_summary_html_injection_safe():
    """Название предмета из NIKA не должно ломать HTML-разметку."""
    malicious = MorningSummaryDTO(
        date_iso="2026-09-11",
        lessons=[
            MorningLessonDTO(
                lesson_num=1,
                start_time="08:30",
                end_time="09:15",
                subject_name='<script>alert("xss")</script>',
                room_name="<b>&",
                is_cancelled=False,
                is_exchange=False,
                is_extra=False,
                group_name=None,
            ),
        ],
        child_name=None,
        class_id="9А",
    )
    text = UIRenderer.render_morning_summary(malicious)
    assert "<script>" not in text, "HTML-инъекция не экранирована в сводке"
    assert isinstance(text, str)


def test_change_reminder_variants():
    variants = [
        ChangeReminderDTO(
            date="2026-09-11", lesson_num=2, subject_name="Физика",
            is_cancelled=False, child_name="Маша", watch_target_title=None,
        ),
        ChangeReminderDTO(
            date="2026-09-11", lesson_num=3, subject_name="Химия",
            is_cancelled=True, child_name=None, watch_target_title=None,
        ),
        ChangeReminderDTO(
            date="2026-09-11", lesson_num=4, subject_name="Биология",
            is_cancelled=False, child_name=None, watch_target_title="5Б",
        ),
    ]
    for dto in variants:
        text = UIRenderer.render_change_reminder(dto)
        assert isinstance(text, str) and text.strip(), "Пустое уведомление замены"
        assert dto.subject_name in text, "В уведомлении замены нет предмета"


def test_lesson_reminder_variants():
    variants = [
        LessonReminderDTO(
            subject_name="Математика", start_time="08:30",
            room_name="204", is_extra=False, child_name=None,
        ),
        LessonReminderDTO(
            subject_name="Плавание", start_time="16:00",
            room_name="Бассейн", is_extra=True, child_name="Маша",
        ),
    ]
    for dto in variants:
        text = UIRenderer.render_lesson_reminder(dto)
        assert isinstance(text, str) and text.strip(), "Пустое напоминание об уроке"
        assert dto.subject_name in text, "В напоминании нет предмета"
        assert dto.start_time in text, "В напоминании нет времени начала"


def test_lesson_reminder_html_injection_safe():
    dto = LessonReminderDTO(
        subject_name='<script>x</script> & "кавычки"',
        start_time="08:30",
        room_name="<b>",
        is_extra=False,
        child_name=None,
    )
    text = UIRenderer.render_lesson_reminder(dto)
    assert "<script>" not in text, "HTML-инъекция не экранирована в напоминании"
