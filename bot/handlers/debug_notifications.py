# bot/handlers/debug_notifications.py
#
# DEBUG-команды для быстрой проверки UI уведомлений.
#/debug_ui            — всё сразу
#/debug_ui morning    — утренние сводки: вид родителя, вид ребёнка,
#/debug_ui change     — замена (родитель), отмена (ребёнок),
#                        два ребёнка в одном сообщении, день без уроков
#                        замена по watch-target, замена у учителя
#/debug_ui lesson     — начало урока (ребёнок/родитель), доп. занятие

# варианты уведомлений, отрендеренные ТЕМИ ЖЕ методами UIRenderer,
# что и боевые отправки NotificationService. Что видишь здесь —
# то увидят пользователи.
#
# Данные mock: команда ничего не читает из БД и не пишет в
# notification_deliverylog, поэтому безопасна для повторного запуска
# и не рассылает ничего другим пользователям.
#
# Доступ: только ADMIN_IDS (AdminService.is_admin).
#
# Регистрация в main.py (строго ДО fallback):
#   from bot.handlers import debug_notifications
#   dp.include_router(debug_notifications.router)
#
# Команду можно оставить в production: она admin-only и оперирует
# только мок-данными.

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.utils.ui_renderer import UIRenderer
from core.models.dto import (
    ChangeReminderDTO,
    LessonReminderDTO,
    MorningLessonDTO,
    MorningSummaryDTO,
)
from services.admin_service import AdminService

logger = logging.getLogger(__name__)
router = Router()

MAX_MESSAGE_LEN = 4000


def _lesson(
    lesson_num: int | None,
    start: str,
    end: str,
    subject: str,
    room: str,
    *,
    cancelled: bool = False,
    exchange: bool = False,
    extra: bool = False,
    group: str | None = None,
    orig_subj: str | None = None,
    orig_room: str | None = None,
    is_methodological: bool = False,
) -> MorningLessonDTO:
    return MorningLessonDTO(
        lesson_num=lesson_num,
        start_time=start,
        end_time=end,
        subject_name=subject,
        room_name=room,
        is_cancelled=cancelled,
        is_exchange=exchange,
        is_extra=extra,
        group_name=group,
        original_subject_name=orig_subj,
        original_room_name=orig_room,
        is_methodological=is_methodological,
        day_permutation=False,
    )


def _morning_variants() -> list[tuple[str, str]]:
    lessons = [
        _lesson(1, "08:30", "09:15", "Математика", "204"),
        _lesson(2, "09:25", "10:10", "Физика", "112", cancelled=True, orig_subj="Физика"),
        _lesson(3, "10:25", "11:10", "Английский", "305", exchange=True, group="2", orig_subj="История", orig_room="101"),
        _lesson(4, "11:25", "12:10", "Методический час", "—", is_methodological=True),
        _lesson(None, "16:00", "17:00", "Плавание", "Бассейн", extra=True),
    ]
    
    child_view = MorningSummaryDTO(date_iso="2026-09-11", lessons=lessons, child_name=None, class_id="9А", has_permutation=False)
    parent_view = MorningSummaryDTO(date_iso="2026-09-11", lessons=lessons, child_name="Маша", class_id="9А", has_permutation=False)
    empty_day = MorningSummaryDTO(date_iso="2026-09-11", lessons=[], child_name="Маша", class_id="9А", has_permutation=False)
    
    rendered_parent = UIRenderer.render_morning_summary(parent_view)
    rendered_child = UIRenderer.render_morning_summary(child_view)
    rendered_empty = UIRenderer.render_morning_summary(empty_day)
    rendered_multi = "\n".join([rendered_parent, rendered_child])
    
    return [
        ("Сводка: вид родителя (полная)", rendered_parent),
        ("Сводка: вид ребёнка (без имени)", rendered_child),
        ("Сводка: мульти-дети", rendered_multi),
        ("Сводка: пустой день", rendered_empty),
    ]


def _change_variants() -> list[tuple[str, str]]:
    dtos = [
        ("Замена урока и кабинета (родитель)", ChangeReminderDTO(
            change_id=1, date="2026-09-11", lesson_num=2, subject_name="Физика", is_cancelled=False, 
            child_name="Маша", watch_target_title=None,
            original_subject_name="Литература", new_subject_name="Физика",
            original_room_name="101", new_room_name="204", group_changed=False
        )),
        ("Отмена урока (класс)", ChangeReminderDTO(
            change_id=2, date="2026-09-11", lesson_num=3, subject_name="Химия", is_cancelled=True, 
            child_name=None, watch_target_title="8Б", original_subject_name="Химия", group_changed=False
        )),
        ("Смена учителя (ребёнок)", ChangeReminderDTO(
            change_id=3, date="2026-09-11", lesson_num=4, subject_name="Информатика", is_cancelled=False, 
            child_name=None, watch_target_title=None, original_teacher_name="Иванова А.П.", 
            new_teacher_name="Петров В.В.", new_subject_name="Информатика", new_room_name="303", group_changed=False
        )),
    ]
    
    result = []
    for caption, dto in dtos:
        result.append((caption, UIRenderer.render_change_reminder(dto)))
    return result


def _lesson_variants() -> list[tuple[str, str]]:
    dtos = [
        ("Урок: ребёнок/учитель", LessonReminderDTO(
            subject_name="Математика", start_time="08:30", room_name="204", is_extra=False, child_name=None,
        )),
        ("Урок: родитель", LessonReminderDTO(
            subject_name="Математика", start_time="08:30", room_name="204", is_extra=False, child_name="Маша",
        )),
        ("Доп: ребёнок", LessonReminderDTO(
            subject_name="Робототехника", start_time="15:00", room_name="Лаборатория", is_extra=True, child_name=None,
        )),
        ("Доп: родитель", LessonReminderDTO(
            subject_name="Плавание", start_time="16:00", room_name="Бассейн", is_extra=True, child_name="Маша",
        )),
    ]
    return [(caption, UIRenderer.render_lesson_reminder(dto)) for caption, dto in dtos]


async def _send_variants(message: Message, variants: list[tuple[str, str]]) -> None:
    for caption, text in variants:
        payload = f"🧪 <i>{caption}</i>\n\n{text}"
        if len(payload) > MAX_MESSAGE_LEN:
            payload = payload[:MAX_MESSAGE_LEN]
        await message.answer(payload, parse_mode="HTML")


@router.message(Command("debug_ui"))
async def cmd_debug_ui(message: Message, command: CommandObject, admin_service: AdminService) -> None:
    if not admin_service.is_admin(user_id=message.from_user.id):
        logger.warning("Debug UI denied: user_id=%s", message.from_user.id)
        await message.answer("⛔ Команда доступна только администратору.")
        return

    section = (command.args or "").strip().lower()
    sections = {
        "morning": _morning_variants,
        "change": _change_variants,
        "lesson": _lesson_variants,
    }

    if section and section not in sections:
        await message.answer("Использование: /debug_ui [morning|change|lesson] — без аргумента присылаю всё.")
        return

    if section:
        await _send_variants(message, sections[section]())
        return

    for builder in (_morning_variants, _change_variants, _lesson_variants):
        await _send_variants(message, builder())
        
    await message.answer("✅ Превью отправлено.")