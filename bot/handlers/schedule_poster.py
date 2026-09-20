"""Image-First расписание дня (этап 3 ТЗ v2.2) — аддитивный роутер.

Роутер регистрируется ВЫШЕ schedule_child и перехватывает ТОЛЬКО
навигацию по дням (ScheduleDayCD) при включённой генерации постеров:

- глобальный рубильник выключен -> фильтр не пропускает апдейт, и его
  обрабатывает существующий текстовый хендлер schedule_child без правок;
- пользователь выбрал «текст» -> день рендерится тем же render_day из
  schedule_child (единая точка правды текстового вида);
- постер получен -> edit_media: картинка меняется без мерцания;
- rate limit -> alert «подождите пару минут» (не ошибка, раздел 4 ТЗ);
- сбой графики -> graceful degradation: удаление постера и отправка
  текста с припиской (раздел 5 ТЗ).

Тумблер формата (🖼/📝) добавляется последним рядом к стандартной
клавиатуре дня; состояние последнего дня хранится в FSM (poster_last_date).

main.py в этом PR не менялся — подключение см. wiring в описании PR
(5 строк: setup, workflow_data, include_router, warm-up job, shutdown).
"""

from __future__ import annotations

import logging
from datetime import date as date_type

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.callbacks import ScheduleDayCD
from bot.handlers.schedule_child import (
    _get_fsm_schedule_target,
    _get_schedule_targets,
    render_day,
)
from bot.keyboards.keyboard import Keyboards
from bot.utils.poster_delivery import (
    build_day_caption,
    edit_poster,
    fallback_to_text,
    send_poster,
)
from config import config
from core.models.dto import DayScheduleDTO, ScheduleViewTargetDTO
from core.repository.schedule_repository import ScheduleRepository
from services.extraclasses_service import ExtraClassesService
from services.image_preferences import ImagePreferencesService
from services.image_render.exceptions import ImageRenderError, RateLimitExceededError
from services.image_render.models import RenderedPoster
from services.image_render.poster_factory import (
    build_global_request_id,
    build_personal_request_id,
    build_poster_request,
    extra_classes_hash,
)
from services.image_render.service import ImageGenerationService
from services.image_render.version import get_schedule_version
from services.profiles_service import ProfileService
from services.schedule_service import ScheduleService
from services.students_service import StudentsService
from services.watch_targets_service import WatchTargetsService

logger = logging.getLogger(__name__)

router = Router()

_WEEKDAYS_RU = {
    1: "Понедельник", 2: "Вторник", 3: "Среда", 4: "Четверг",
    5: "Пятница", 6: "Суббота", 7: "Воскресенье",
}


class ScheduleFormatToggleCD(CallbackData, prefix="sft"):
    """Тумблер «🖼 Картинка / 📝 Текст» — формат расписания пользователя."""


async def _image_generation_enabled(event) -> bool:  # noqa: ANN001 — и Message, и CallbackQuery
    """Глобальный рубильник (раздел 2.1 ТЗ): False -> текстовые хендлеры."""
    return config.ENABLE_IMAGE_GENERATION


def _format_date_text(date_iso: str) -> str:
    value = date_type.fromisoformat(date_iso)
    weekday = _WEEKDAYS_RU.get(value.isoweekday(), "")
    return f"{weekday}, {value.strftime('%d.%m')}"


def _changes_count(day_dto: DayScheduleDTO) -> int:
    return sum(
        1
        for lesson in day_dto.lessons
        if not lesson.is_extra and (lesson.is_exchange or lesson.is_cancelled)
    )


def _child_subtitle(target: ScheduleViewTargetDTO, actor_user_id: int) -> str | None:
    """Имя ребёнка, когда расписание смотрит не сам ребёнок."""
    if target.kind == "student" and target.telegram_user_id != actor_user_id:
        return target.title
    return None


def _build_day_keyboard(
    *,
    date_iso: str,
    target: ScheduleViewTargetDTO,
    has_changes: bool,
    show_target_switch: bool,
    prefer_image: bool,
) -> InlineKeyboardMarkup:
    """Стандартная клавиатура дня + ряд с тумблером формата."""
    keyboard = Keyboards.get_schedule_day_kb(
        date_iso,
        show_target_switch=show_target_switch,
        has_changes=has_changes,
        target_kind=target.kind,
        target_id=target.target_id,
        class_id=target.class_id,
        group_id=target.group_id,
    )
    keyboard.inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="📝 Формат: текст" if prefer_image else "🖼 Формат: картинка",
                callback_data=ScheduleFormatToggleCD().pack(),
            )
        ]
    )
    return keyboard


async def _build_day_poster(
    *,
    actor_user_id: int,
    target: ScheduleViewTargetDTO,
    date_iso: str,
    schedule_service: ScheduleService,
    extra_classes_service: ExtraClassesService,
    schedule_repo: ScheduleRepository,
    image_service: ImageGenerationService,
) -> tuple[RenderedPoster, DayScheduleDTO]:
    """Собирает и рендерит постер дня (ключ — версионированный request_id)."""
    day_dto = await schedule_service.get_daily_schedule_for_student(
        class_id=target.class_id,
        group_id=target.group_id,
        date_iso=date_iso,
        student_id=target.target_id if target.kind == "student" else None,
    )
    version = await get_schedule_version(schedule_repo)

    # Персональный ключ — только если у ребёнка есть доп. занятия на этот
    # день: постер принадлежит профилю ребёнка, мама/папа/ребёнок шарят один.
    request_id = build_global_request_id(version, target.class_id, target.group_id, date_iso)
    if target.kind == "student":
        weekday = date_type.fromisoformat(date_iso).isoweekday()
        extras = await extra_classes_service.get_extra_classes_for_student(
            student_id=target.target_id, day_of_week=weekday
        )
        if extras:
            request_id = build_personal_request_id(
                version, target.target_id, date_iso, extra_classes_hash(extras)
            )

    request = build_poster_request(
        request_id=request_id,
        dto=day_dto,
        title=f"Расписание · {day_dto.class_name or target.class_id}",
        date_text=_format_date_text(date_iso),
        subtitle=_child_subtitle(target, actor_user_id),
        width=config.POSTER_WIDTH,
    )
    poster = await image_service.get_poster(request, user_id=actor_user_id)
    return poster, day_dto


async def _render_text_day(
    *,
    callback: CallbackQuery,
    target: ScheduleViewTargetDTO,
    date_iso: str,
    actor_user_id: int,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
    notice: str | None = None,
) -> None:
    """Текстовый вид дня — тот же конвейер, что в schedule_child."""
    text, keyboard = await render_day(
        actor_user_id=actor_user_id,
        target=target,
        date_iso=date_iso,
        profile_service=profile_service,
        schedule_service=schedule_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )
    if notice:
        text = f"{notice}\n\n{text}"
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest:
        # Текущее сообщение — постер-фото: edit_text невозможен
        await fallback_to_text(callback, text, keyboard)


@router.callback_query(ScheduleDayCD.filter(), _image_generation_enabled)
async def show_day_poster(
    callback: CallbackQuery,
    callback_data: ScheduleDayCD,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
    extra_classes_service: ExtraClassesService,
    schedule_repo: ScheduleRepository,
    image_service: ImageGenerationService,
    image_prefs: ImagePreferencesService,
) -> None:
    """Навигация по дням в image-first режиме: edit_media без мерцания."""
    actor_user_id = callback.from_user.id
    target = await _get_fsm_schedule_target(
        callback=callback,
        state=state,
        profile_service=profile_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )
    if target is None:
        await callback.answer("Сессия устарела. Откройте расписание заново.", show_alert=True)
        return

    date_iso = callback_data.date_iso
    await state.update_data(poster_last_date=date_iso)

    if not await image_prefs.prefers_image(actor_user_id):
        await _render_text_day(
            callback=callback,
            target=target,
            date_iso=date_iso,
            actor_user_id=actor_user_id,
            profile_service=profile_service,
            schedule_service=schedule_service,
            students_service=students_service,
            watch_targets_service=watch_targets_service,
        )
        await callback.answer()
        return

    try:
        poster, day_dto = await _build_day_poster(
            actor_user_id=actor_user_id,
            target=target,
            date_iso=date_iso,
            schedule_service=schedule_service,
            extra_classes_service=extra_classes_service,
            schedule_repo=schedule_repo,
            image_service=image_service,
        )
    except RateLimitExceededError:
        await callback.answer(
            "⏳ Слишком много запросов к графическому движку. Пожалуйста, подождите пару минут.",
            show_alert=True,
        )
        return
    except ImageRenderError:
        logger.warning("Графический движок деградировал — текстовый fallback", exc_info=True)
        await _render_text_day(
            callback=callback,
            target=target,
            date_iso=date_iso,
            actor_user_id=actor_user_id,
            profile_service=profile_service,
            schedule_service=schedule_service,
            students_service=students_service,
            watch_targets_service=watch_targets_service,
            notice="⚠️ Сервер графики перегружен. Вывожу текстовое расписание.",
        )
        await callback.answer()
        return

    targets = await _get_schedule_targets(
        actor_user_id=actor_user_id,
        profile_service=profile_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )
    keyboard = _build_day_keyboard(
        date_iso=date_iso,
        target=target,
        has_changes=_changes_count(day_dto) > 0,
        show_target_switch=len(targets) > 1,
        prefer_image=True,
    )
    caption = build_day_caption(
        _format_date_text(date_iso),
        _changes_count(day_dto),
        _child_subtitle(target, actor_user_id),
    )
    await edit_poster(callback, image_service, poster, caption, keyboard)
    await callback.answer()


@router.callback_query(ScheduleFormatToggleCD.filter(), _image_generation_enabled)
async def toggle_poster_format(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
    extra_classes_service: ExtraClassesService,
    schedule_repo: ScheduleRepository,
    image_service: ImageGenerationService,
    image_prefs: ImagePreferencesService,
) -> None:
    """Переключает формат «картинка/текст» и перерисовывает текущий день."""
    actor_user_id = callback.from_user.id
    prefer_image = await image_prefs.toggle(actor_user_id)

    data = await state.get_data()
    date_iso = data.get("poster_last_date")
    target = await _get_fsm_schedule_target(
        callback=callback,
        state=state,
        profile_service=profile_service,
        students_service=students_service,
        watch_targets_service=watch_targets_service,
    )
    if target is None or not date_iso:
        # Переключение из /format без открытого расписания — обновляем статус
        await callback.answer(f"Формат расписания: {'🖼 картинка' if prefer_image else '📝 текст'}")
        return

    if prefer_image:
        try:
            poster, day_dto = await _build_day_poster(
                actor_user_id=actor_user_id,
                target=target,
                date_iso=date_iso,
                schedule_service=schedule_service,
                extra_classes_service=extra_classes_service,
                schedule_repo=schedule_repo,
                image_service=image_service,
            )
        except ImageRenderError:
            # Откат: не оставляем пользователя без расписания
            await image_prefs.toggle(actor_user_id)
            await callback.answer(
                "⚠️ Графика недоступна — формат оставлен текстовым.",
                show_alert=True,
            )
            return
        keyboard = _build_day_keyboard(
            date_iso=date_iso,
            target=target,
            has_changes=_changes_count(day_dto) > 0,
            show_target_switch=False,
            prefer_image=True,
        )
        caption = build_day_caption(
            _format_date_text(date_iso),
            _changes_count(day_dto),
            _child_subtitle(target, actor_user_id),
        )
        await _delete_best_effort(callback)
        await send_poster(callback.message, image_service, poster, caption, keyboard)
        await callback.answer("Формат расписания: 🖼 картинка")
    else:
        text, keyboard = await render_day(
            actor_user_id=actor_user_id,
            target=target,
            date_iso=date_iso,
            profile_service=profile_service,
            schedule_service=schedule_service,
            students_service=students_service,
            watch_targets_service=watch_targets_service,
        )
        await _delete_best_effort(callback)
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer("Формат расписания: 📝 текст")


@router.message(Command("format"), _image_generation_enabled)
async def cmd_format(message: Message, image_prefs: ImagePreferencesService) -> None:
    """Показ текущего формата расписания и кнопка переключения."""
    prefer_image = await image_prefs.prefers_image(message.from_user.id)
    current = "🖼 картинка" if prefer_image else "📝 текст"
    other = "📝 текст" if prefer_image else "🖼 картинка"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Переключить на {other}",
                    callback_data=ScheduleFormatToggleCD().pack(),
                )
            ]
        ]
    )
    await message.answer(
        f"Текущий формат расписания: {current}.\n\n"
        "Картинка — наглядный постер, текст — экономия трафика "
        "на медленном интернете.",
        reply_markup=keyboard,
    )


async def _delete_best_effort(callback: CallbackQuery) -> None:
    """Удаление сообщения перед сменой формата (фото <-> текст)."""
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        logger.debug("Не удалось удалить сообщение при смене формата", exc_info=True)
