import logging
from typing import Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.keyboard import Keyboards
from bot.utils.ui_renderer import UIRenderer
from core.models.dto import ScheduleViewTargetDTO
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.watch_targets_service import WatchTargetsService
from services.students_service import StudentsService

from bot.handlers.schedule_teacher import (
    open_teacher_schedule_for_message,
)

logger = logging.getLogger(__name__)
router = Router()


async def _safe_edit_schedule_message(
    callback: CallbackQuery,
    text: str,
    keyboard,
) -> None:
    """
    Безопасно обновляет Schedule Hub message.
    """
    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        logger.debug(
            "Schedule message edit skipped: %s",
            exc,
        )


async def _get_schedule_targets(
    *,
    actor_user_id: int,
    profile_service: ProfileService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
) -> list[ScheduleViewTargetDTO]:
    """
    Возвращает все доступные цели Schedule Hub.

    Child:
    - только свой student_profile.

    Parent / observer:
    - доступные student_profiles семьи;
    - собственные активные watch targets.
    """
    actor_dto = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    targets: list[ScheduleViewTargetDTO] = []

    # Telegram-ребёнок видит только свой student profile.
    if actor_dto.role == "child":
        student = await students_service.get_student_by_telegram_user_id(
            telegram_user_id=actor_user_id,
        )

        if student is None:
            logger.warning(
                "Child user_id=%s has no student_profile",
                actor_user_id,
            )
            return []

        targets.append(
            ScheduleViewTargetDTO(
                kind="student",
                target_id=student.id,
                class_id=student.class_id,
                group_id=student.group_id,
                title=student.name,
                telegram_user_id=student.telegram_user_id,
            )
        )

        return targets

    # Parent / observer получают доступных student profiles.
    if actor_dto.role in ("parent", "observer"):
        students = await students_service.get_students_for_adult(
            adult_user_id=actor_user_id,
        )

        for student in students:
            targets.append(
                ScheduleViewTargetDTO(
                    kind="student",
                    target_id=student.id,
                    class_id=student.class_id,
                    group_id=student.group_id,
                    title=student.name,
                    telegram_user_id=student.telegram_user_id,
                    is_enabled=student.is_active,
                )
            )

    # Любой пользователь может иметь личные watch targets.
    watch_targets = await watch_targets_service.get_targets(
        owner_user_id=actor_user_id,
        enabled_only=True,
    )

    for watch_target in watch_targets:
        targets.append(
            ScheduleViewTargetDTO(
                kind="watch",
                target_id=watch_target.id,
                class_id=watch_target.class_id,
                group_id=watch_target.group_id,
                title=watch_target.title or (
                    f"Класс {watch_target.class_id}"
                ),
                telegram_user_id=None,
                is_enabled=watch_target.is_enabled,
            )
        )

    return targets

async def _resolve_schedule_target(
    *,
    actor_user_id: int,
    target_kind: str,
    target_id: int,
    profile_service: ProfileService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
) -> Optional[ScheduleViewTargetDTO]:
    """
    Проверяет доступ пользователя к конкретной цели Schedule Hub.

    Это обязательная security boundary для callbacks и FSM.
    """
    if target_kind == "watch":
        watch_target = await watch_targets_service.get_target(
            owner_user_id=actor_user_id,
            target_id=target_id,
        )

        if watch_target is None or not watch_target.is_enabled:
            return None

        return ScheduleViewTargetDTO(
            kind="watch",
            target_id=watch_target.id,
            class_id=watch_target.class_id,
            group_id=watch_target.group_id,
            title=watch_target.title or (
                f"Класс {watch_target.class_id}"
            ),
            telegram_user_id=None,
            is_enabled=True,
        )

    if target_kind != "student":
        return None

    actor_dto = await profile_service.get_user_profile_dto(
        actor_user_id,
    )

    # Child может открыть только student_profile,
    # связанный с его Telegram account.
    if actor_dto.role == "child":
        student = await students_service.get_student_by_telegram_user_id(
            telegram_user_id=actor_user_id,
        )

        if student is None or student.id != target_id:
            return None

        return ScheduleViewTargetDTO(
            kind="student",
            target_id=student.id,
            class_id=student.class_id,
            group_id=student.group_id,
            title=student.name,
            telegram_user_id=student.telegram_user_id,
            is_enabled=student.is_active,
        )

    # Parent / observer используют parent_student_settings.
    result = await students_service.get_student_for_adult(
        adult_user_id=actor_user_id,
        student_id=target_id,
    )

    if result is None:
        return None

    student, _access = result

    return ScheduleViewTargetDTO(
        kind="student",
        target_id=student.id,
        class_id=student.class_id,
        group_id=student.group_id,
        title=student.name,
        telegram_user_id=student.telegram_user_id,
        is_enabled=student.is_active,
    )

async def _render_day(
    *,
    actor_user_id: int,
    target: ScheduleViewTargetDTO,
    date_iso: str,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
):
    """
    Строит дневное расписание для child или watch target.
    """
    day_dto = await schedule_service.get_daily_schedule_for_student(
        class_id=target.class_id,
        group_id=target.group_id,
        date_iso=date_iso,
        student_id=(
            target.target_id
            if target.kind == "student"
            else None
        ),
    )

    child_name = None

    if target.kind == "student" and target.telegram_user_id != actor_user_id:
        child_name = target.title

    rendered = UIRenderer.render_child_day_schedule(
        day_dto,
        child_name,
    )

    text = rendered[0] if isinstance(rendered, tuple) else rendered

    if target.kind == "watch":
        text = (
            "🎓 <b>Отслеживаемый класс</b>\n"
            f"📌 {UIRenderer.escape_html(target.title)}\n\n"
            f"{text}"
        )

    elif target.kind == "student" and target.telegram_user_id is None:
        text = (
            "🧒 <b>Ученик без Telegram</b>\n"
            f"👤 {UIRenderer.escape_html(target.title)}\n\n"
            f"{text}"
        )
        
    available_targets = await _get_schedule_targets(
        actor_user_id=actor_user_id,
        profile_service=profile_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )

    keyboard = Keyboards.get_schedule_day_kb(
        current_date_iso=date_iso,
        show_target_switch=len(available_targets) > 1,
    )

    return text, keyboard


async def _render_week(
    *,
    actor_user_id: int,
    target: ScheduleViewTargetDTO,
    week_start_iso: str,
    is_full: bool,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
):
    """
    Строит краткое или подробное недельное расписание.
    """
    if is_full:
        week_dto = await schedule_service.get_full_week_schedule(
            class_id=target.class_id,
            group_id=target.group_id,
            week_start_iso=week_start_iso,
            student_id=(
                target.target_id
                if target.kind == "student"
                else None
            )
        )

        rendered = UIRenderer.render_full_week_schedule(
            week_dto,
        )
    else:
        week_dto = await schedule_service.get_week_schedule_summary(
            class_id=target.class_id,
            group_id=target.group_id,
            week_start_iso=week_start_iso,
            student_id=(
                target.target_id
                if target.kind == "student"
                else None
            )
        )

        rendered = UIRenderer.render_week_summary(
            week_dto,
        )

    text = rendered[0] if isinstance(rendered, tuple) else rendered

    if target.kind == "watch":
        text = (
            "🎓 <b>Отслеживаемый класс</b>\n"
            f"📌 {UIRenderer.escape_html(target.title)}\n\n"
            f"{text}"
        )

    elif target.kind == "student":
        if target.telegram_user_id is None:
            prefix = (
                "🧒 <b>Ученик без Telegram</b>\n"
                f"👤 {UIRenderer.escape_html(target.title)}\n\n"
            )
        elif target.telegram_user_id != actor_user_id:
            prefix = (
                f"🧒 <b>{UIRenderer.escape_html(target.title)}</b>\n\n"
            )
        else:
            prefix = ""

        text = prefix + text
        
    available_targets = await _get_schedule_targets(
        actor_user_id=actor_user_id,
        profile_service=profile_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )

    keyboard = Keyboards.get_schedule_week_kb(
        week_start_iso=week_start_iso,
        show_target_switch=len(available_targets) > 1,
        is_full=is_full,
    )

    return text, keyboard


async def _save_schedule_target_to_fsm(
    *,
    state: FSMContext,
    actor_user_id: int,
    target: ScheduleViewTargetDTO,
) -> None:
    await state.update_data(
        schedule_actor_user_id=actor_user_id,
        schedule_target_kind=target.kind,
        schedule_target_id=target.target_id,
    )


async def _get_fsm_schedule_target(
    *,
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
) -> Optional[ScheduleViewTargetDTO]:
    """
    Загружает target из FSM и повторно проверяет доступ.
    """
    data = await state.get_data()

    actor_user_id = callback.from_user.id

    if data.get("schedule_actor_user_id") != actor_user_id:
        return None

    target_kind = data.get("schedule_target_kind")
    target_id = data.get("schedule_target_id")

    if not target_kind or not target_id:
        return None

    return await _resolve_schedule_target(
        actor_user_id=actor_user_id,
        target_kind=target_kind,
        target_id=target_id,
        profile_service=profile_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )


@router.message(F.text.in_({
    "📅 Моё расписание",
    "📅 Мое расписание",
}))
async def open_schedule_hub(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
) -> None:
    """
    Единственная точка входа в расписание.

    Если доступна одна цель — открывается сразу.
    Если доступно несколько целей — пользователь выбирает.
    """
    
    actor_user_id = message.from_user.id
    
    actor = await profile_service.get_user_profile_dto(actor_user_id)

    if not actor.is_fully_registered:
        await message.answer(UIRenderer.render_unregistered_error())
        return

    if actor.role == "teacher":
        opened = await open_teacher_schedule_for_message(
            message=message,
            profile_service=profile_service,
            schedule_service=schedule_service,
        )

        if not opened:
            await message.answer(
                "❌ Не удалось открыть расписание учителя. "
                "Проверьте выбранный профиль учителя в настройках."
            )

        return

    targets = await _get_schedule_targets(
        actor_user_id=actor_user_id,
        profile_service=profile_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )

    if not targets:
        await message.answer(
            "У вас пока нет доступных учеников или "
            "отслеживаемых классов.\n\n"
            "Добавьте класс через:\n"
            "⚙️ Настройки → 🎓 Мои отслеживаемые классы."
        )
        return

    if len(targets) > 1:
        await state.update_data(
            schedule_actor_user_id=actor_user_id,
            schedule_target_kind=None,
            schedule_target_id=None,
        )
        
        # 1. Запрашиваем справочники школы единым запросом
        dicts_dto = await schedule_service.get_school_dictionaries()
        
        await message.answer(
            "🎯 <b>Выберите расписание</b>",
            reply_markup=Keyboards.get_schedule_targets_kb(
                targets=targets,
                classes_dict=dicts_dto.classes,
                groups_dict=dicts_dto.groups,
            ),
            parse_mode="HTML",
        )
        return

    target = targets[0]

    logger.warning(
        "Schedule Hub targets: actor_id=%s count=%s targets=%r",
        actor_user_id,
        len(targets),
        [
            (
                target.kind,
                target.target_id,
                target.title,
                target.class_id,
                target.group_id,
            )
            for target in targets
        ],
    )

    await _save_schedule_target_to_fsm(
        state=state,
        actor_user_id=actor_user_id,
        target=target,
    )

    target_date_iso = await schedule_service.get_smart_target_date(
        class_id=target.class_id,
        group_id=target.group_id,
        student_id=(
            target.target_id
            if target.kind == "student"
            else None
        ),
    )

    text, keyboard = await _render_day(
        actor_user_id=actor_user_id,
        target=target,
        date_iso=target_date_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )

    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(F.data == "sched:targets")
async def show_schedule_targets(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
    schedule_service: ScheduleService,
) -> None:
    """
    Показывает selector цели из day/week schedule screen.
    """
    targets = await _get_schedule_targets(
        actor_user_id=callback.from_user.id,
        profile_service=profile_service,
        watch_targets_service=watch_targets_service,
        students_service=students_service,
    )

    if not targets:
        await callback.answer(
            "Нет доступных целей расписания.",
            show_alert=True,
        )
        return

    await state.update_data(
        schedule_actor_user_id=callback.from_user.id,
        schedule_target_kind=None,
        schedule_target_id=None,
    )
    
    # 1. Запрашиваем справочники школы единым запросом
    dicts_dto = await schedule_service.get_school_dictionaries()
    
    # 2. Передаем сырые словари напрямую из свойств dicts_dto в клавиатуру
    await _safe_edit_schedule_message(
        callback,
        "🎯 <b>Выберите расписание</b>",
        Keyboards.get_schedule_targets_kb(
            targets=targets,
            classes_dict=dicts_dto.classes,
            groups_dict=dicts_dto.groups,
        ),
    )

    await callback.answer()


@router.callback_query(F.data.startswith("sched:target:"))
async def select_schedule_target(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
) -> None:
    """
    Выбирает child или watch target.
    """
    try:
        _, _, target_kind, target_id_raw = callback.data.split(":")

        target_id = int(target_id_raw)
    except (IndexError, ValueError):
        await callback.answer(
            "Некорректная цель расписания.",
            show_alert=True,
        )
        return

    actor_user_id = callback.from_user.id

    target = await _resolve_schedule_target(
        actor_user_id=actor_user_id,
        target_kind=target_kind,
        target_id=target_id,
        profile_service=profile_service,
        watch_targets_service=watch_targets_service,
        students_service=students_service,
    )

    if target is None:
        await callback.answer(
            "Цель недоступна или была удалена.",
            show_alert=True,
        )
        return

    await _save_schedule_target_to_fsm(
        state=state,
        actor_user_id=actor_user_id,
        target=target,
    )

    target_date_iso = await schedule_service.get_smart_target_date(
        class_id=target.class_id,
        group_id=target.group_id,
        student_id=(
            target.target_id
            if target.kind == "student"
            else None
        ),
    )

    text, keyboard = await _render_day(
        actor_user_id=actor_user_id,
        target=target,
        date_iso=target_date_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()


@router.callback_query(F.data.startswith("sched:watch:"))
async def open_watch_target_schedule(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
) -> None:
    """
    Открывает watch target из карточки отслеживаемого класса.
    """
    try:
        target_id = int(
            callback.data.split(":")[2]
        )
    except (IndexError, ValueError):
        await callback.answer(
            "Некорректный класс.",
            show_alert=True,
        )
        return

    actor_user_id = callback.from_user.id

    target = await _resolve_schedule_target(
        actor_user_id=actor_user_id,
        target_kind="watch",
        target_id=target_id,
        profile_service=profile_service,
        watch_targets_service=watch_targets_service,
        students_service=students_service,
    )

    if target is None:
        await callback.answer(
            "Класс недоступен или отслеживание выключено.",
            show_alert=True,
        )
        return

    await _save_schedule_target_to_fsm(
        state=state,
        actor_user_id=actor_user_id,
        target=target,
    )

    target_date_iso = await schedule_service.get_smart_target_date(
        class_id=target.class_id,
        group_id=target.group_id,
        student_id=None,
    )

    text, keyboard = await _render_day(
        actor_user_id=actor_user_id,
        target=target,
        date_iso=target_date_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
        watch_targets_service=watch_targets_service,
        students_service=students_service,
    )

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()


@router.callback_query(F.data == "sched:smart_day")
async def go_to_smart_day(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
) -> None:
    target = await _get_fsm_schedule_target(
        callback=callback,
        state=state,
        profile_service=profile_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )

    if target is None:
        await callback.answer(
            "Сессия просмотра устарела. "
            "Откройте расписание заново.",
            show_alert=True,
        )
        return

    target_date_iso = await schedule_service.get_smart_target_date(
        class_id=target.class_id,
        group_id=target.group_id,
        student_id=(
            target.target_id
            if target.kind == "student"
            else None
        ),
    )

    text, keyboard = await _render_day(
        actor_user_id=callback.from_user.id,
        target=target,
        date_iso=target_date_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()


@router.callback_query(F.data.startswith("sched:day:"))
async def show_schedule_day(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
) -> None:
    try:
        date_iso = callback.data.split(":")[2]
    except IndexError:
        await callback.answer(
            "Некорректная дата.",
            show_alert=True,
        )
        return

    target = await _get_fsm_schedule_target(
        callback=callback,
        state=state,
        profile_service=profile_service,
        watch_targets_service=watch_targets_service,
        students_service=students_service,
    )

    if target is None:
        await callback.answer(
            "Сессия просмотра устарела. "
            "Откройте расписание заново.",
            show_alert=True,
        )
        return

    text, keyboard = await _render_day(
        actor_user_id=callback.from_user.id,
        target=target,
        date_iso=date_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()


@router.callback_query(F.data.startswith("sched:week:"))
async def show_schedule_week(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
) -> None:
    try:
        week_start_iso = callback.data.split(":")[2]
    except IndexError:
        await callback.answer(
            "Некорректная дата недели.",
            show_alert=True,
        )
        return

    target = await _get_fsm_schedule_target(
        callback=callback,
        state=state,
        profile_service=profile_service,
        watch_targets_service=watch_targets_service,
        students_service=students_service,
    )

    if target is None:
        await callback.answer(
            "Сессия просмотра устарела. "
            "Откройте расписание заново.",
            show_alert=True,
        )
        return

    text, keyboard = await _render_week(
        actor_user_id=callback.from_user.id,
        target=target,
        week_start_iso=week_start_iso,
        is_full=False,
        profile_service=profile_service,
        schedule_service=schedule_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()


@router.callback_query(F.data.startswith("sched:full_week:"))
async def show_full_schedule_week(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
) -> None:
    try:
        week_start_iso = callback.data.split(":")[2]
    except IndexError:
        await callback.answer(
            "Некорректная дата недели.",
            show_alert=True,
        )
        return

    target = await _get_fsm_schedule_target(
        callback=callback,
        state=state,
        profile_service=profile_service,
        watch_targets_service=watch_targets_service,
        students_service=students_service,
    )

    if target is None:
        await callback.answer(
            "Сессия просмотра устарела. "
            "Откройте расписание заново.",
            show_alert=True,
        )
        return

    text, keyboard = await _render_week(
        actor_user_id=callback.from_user.id,
        target=target,
        week_start_iso=week_start_iso,
        is_full=True,
        profile_service=profile_service,
        schedule_service=schedule_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )

    if len(text) > 3900:
        await callback.answer(
            "Подробная неделя слишком длинная. "
            "Используйте просмотр по дням.",
            show_alert=True,
        )
        return

    await _safe_edit_schedule_message(
        callback,
        text,
        keyboard,
    )

    await callback.answer()