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

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from bot import callbacks
from aiogram.filters.callback_data import CallbackData

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.callbacks import DayChangesCD, ScheduleDayCD, ScheduleTargetCD, ScheduleWatchCD, TeacherScheduleDayCD, ScheduleForceTextCD, TeacherForceTextCD
from bot.handlers.schedule_child import (
    _get_fsm_schedule_target,
    _get_schedule_targets,
    _render_day,
    _resolve_schedule_target, _save_schedule_target_to_fsm,
    _resolve_schedule_target,
    
)
from bot.handlers.schedule_teacher import _get_teacher_profile, _teacher_name, _render_teacher_day
from bot.utils.ui_renderer import UIRenderer
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
from services.extra_classes_service import ExtraClassesService
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
    text, keyboard = await _render_day(
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

async def _build_teacher_day_poster(
    *,
    actor_user_id: int,
    teacher_id: str,
    teacher_name: str,
    date_iso: str,
    schedule_service: ScheduleService,
    schedule_repo: ScheduleRepository,
    image_service: ImageGenerationService,
) -> tuple[RenderedPoster, DayScheduleDTO]:
    """Собирает постер для расписания Учителя."""
    day_dto = await schedule_service.get_daily_schedule_for_teacher(
        teacher_id=teacher_id, date_iso=date_iso
    )
    version = await get_schedule_version(schedule_repo)
    request_id = build_global_request_id(version, teacher_id, "TEACHER", date_iso)
    
    request = build_poster_request(
        request_id=request_id,
        dto=day_dto,
        title=f"Расписание · {teacher_name}",
        date_text=_format_date_text(date_iso),
        is_teacher=True,  
        width=config.POSTER_WIDTH,
    )
    poster = await image_service.get_poster(request, user_id=actor_user_id)
    return poster, day_dto

# ==========================================================
# ПЕРЕХВАТ ТОЧЕК ВХОДА И УМНЫХ ДНЕЙ (INTERCEPTORS)
# ==========================================================

@router.message(F.text.in_({"📅 Моё расписание", "📅 Мое расписание"}), _image_generation_enabled)
async def open_schedule_hub_poster(
    message: Message, state: FSMContext, profile_service: ProfileService,
    schedule_service: ScheduleService, students_service: StudentsService,
    watch_targets_service: WatchTargetsService, extra_classes_service: ExtraClassesService,
    schedule_repo: ScheduleRepository, image_service: ImageGenerationService,
    image_prefs: ImagePreferencesService,
) -> None:
    actor_user_id = message.from_user.id
    if not await image_prefs.prefers_image(actor_user_id):
        raise SkipHandler()

    actor = await profile_service.get_user_profile_dto(actor_user_id)
    if not actor.is_fully_registered:
        raise SkipHandler()

    # --- ВЕТВЬ УЧИТЕЛЯ ---
    if actor.role == "teacher":
        teacher = await _get_teacher_profile(user_id=actor_user_id, profile_service=profile_service)
        if not teacher: raise SkipHandler()
            
        teacher_name = await _teacher_name(teacher_id=teacher.teacher_id, schedule_service=schedule_service, fallback=teacher.name or "Учитель")
        date_iso = await schedule_service.get_smart_teacher_target_date(teacher_id=teacher.teacher_id)
        await state.update_data(poster_last_date=date_iso)
        
        try:
            poster, day_dto = await _build_teacher_day_poster(
                actor_user_id=actor_user_id, teacher_id=teacher.teacher_id, teacher_name=teacher_name,
                date_iso=date_iso, schedule_service=schedule_service, schedule_repo=schedule_repo, image_service=image_service
            )
        except RateLimitExceededError:
            await message.answer("⏳ Слишком много запросов к графическому движку. Пожалуйста, подождите пару минут.")
            return
        except ImageRenderError:
            raise SkipHandler()
            
        kb = Keyboards.get_teacher_schedule_day_kb(
            current_date_iso=date_iso, teacher_id=teacher.teacher_id, 
            has_changes=_changes_count(day_dto) > 0, is_image=True
        )
        caption = build_day_caption(_format_date_text(date_iso), _changes_count(day_dto))
        await send_poster(message, image_service, poster, caption, kb)
        return

    # --- ВЕТВЬ РЕБЕНКА / РОДИТЕЛЯ ---
    targets = await _get_schedule_targets(
        actor_user_id=actor_user_id, profile_service=profile_service,
        students_service=students_service, watch_targets_service=watch_targets_service
    )
    if len(targets) != 1:
        raise SkipHandler() # Если детей несколько, пропускаем к текстовому меню выбора
        
    target = targets[0]
    await _save_schedule_target_to_fsm(state=state, actor_user_id=actor_user_id, target=target)
    date_iso = await schedule_service.get_smart_target_date(
        class_id=target.class_id, group_id=target.group_id,
        student_id=target.target_id if target.kind == "student" else None
    )
    await state.update_data(poster_last_date=date_iso)
    
    try:
        poster, day_dto = await _build_day_poster(
            actor_user_id=actor_user_id, target=target, date_iso=date_iso,
            schedule_service=schedule_service, extra_classes_service=extra_classes_service,
            schedule_repo=schedule_repo, image_service=image_service
        )
    except RateLimitExceededError:
        await message.answer("⏳ Слишком много запросов...")
        return
    except ImageRenderError:
        raise SkipHandler()
        
    kb = Keyboards.get_schedule_day_kb(
        current_date_iso=date_iso, show_target_switch=False,
        has_changes=_changes_count(day_dto) > 0, target_kind=target.kind,
        target_id=target.target_id, class_id=target.class_id, group_id=target.group_id,
        origin="class", is_image=True
    )
    caption = build_day_caption(_format_date_text(date_iso), _changes_count(day_dto), _child_subtitle(target, actor_user_id))
    await send_poster(message, image_service, poster, caption, kb)


# ==========================================================
# ПЕРЕХВАТЧИКИ ЦЕЛЕЙ И НАВИГАЦИИ (ЧИСТЫЕ DTO)
# ==========================================================

async def _render_and_send_target_poster(
    callback: CallbackQuery, target: ScheduleViewTargetDTO, state: FSMContext,
    actor_user_id: int, profile_service: ProfileService, schedule_service: ScheduleService, 
    students_service: StudentsService, watch_targets_service: WatchTargetsService, 
    extra_classes_service: ExtraClassesService, schedule_repo: ScheduleRepository, image_service: ImageGenerationService,
    date_iso: str = None
):
    """Общий хелпер для отрисовки постера. Если date_iso не передан, ищет смарт-день."""
    if not date_iso:
        date_iso = await schedule_service.get_smart_target_date(
            class_id=target.class_id, group_id=target.group_id,
            student_id=target.target_id if target.kind == "student" else None
        )
    await state.update_data(poster_last_date=date_iso)
    
    try:
        poster, day_dto = await _build_day_poster(
            actor_user_id=actor_user_id, target=target, date_iso=date_iso,
            schedule_service=schedule_service, extra_classes_service=extra_classes_service,
            schedule_repo=schedule_repo, image_service=image_service
        )
    except RateLimitExceededError:
        await callback.answer("⏳ Слишком много запросов. Подождите пару минут.", show_alert=True)
        return
    except ImageRenderError:
        raise SkipHandler()
        
    targets = await _get_schedule_targets(
        actor_user_id=actor_user_id, profile_service=profile_service,
        students_service=students_service, watch_targets_service=watch_targets_service
    )
    
    kb = Keyboards.get_schedule_day_kb(
        current_date_iso=date_iso, show_target_switch=len(targets) > 1,
        has_changes=_changes_count(day_dto) > 0, target_kind=target.kind,
        target_id=target.target_id, class_id=target.class_id, group_id=target.group_id,
        origin="class", is_image=True
    )
    caption = build_day_caption(_format_date_text(date_iso), _changes_count(day_dto), _child_subtitle(target, actor_user_id))
    
    await edit_poster(callback, image_service, poster, caption, kb)
    await callback.answer()


@router.callback_query(ScheduleTargetCD.filter(), _image_generation_enabled)
async def select_schedule_target_poster(
    callback: CallbackQuery, callback_data: ScheduleTargetCD, state: FSMContext,
    profile_service: ProfileService, schedule_service: ScheduleService, students_service: StudentsService,
    watch_targets_service: WatchTargetsService, extra_classes_service: ExtraClassesService,
    schedule_repo: ScheduleRepository, image_service: ImageGenerationService, image_prefs: ImagePreferencesService
) -> None:
    """Перехват выбора ребенка из списка."""
    actor_user_id = callback.from_user.id
    if not await image_prefs.prefers_image(actor_user_id): raise SkipHandler()
        
    target = await _resolve_schedule_target(
        actor_user_id=actor_user_id, target_kind=callback_data.kind, target_id=callback_data.target_id,
        profile_service=profile_service, students_service=students_service, watch_targets_service=watch_targets_service
    )
    if not target: raise SkipHandler()
    await _save_schedule_target_to_fsm(state=state, actor_user_id=actor_user_id, target=target)
    await _render_and_send_target_poster(callback, target, state, actor_user_id, profile_service, schedule_service, students_service, watch_targets_service, extra_classes_service, schedule_repo, image_service)


@router.callback_query(ScheduleWatchCD.filter(), _image_generation_enabled)
async def select_watch_target_poster(
    callback: CallbackQuery, callback_data: ScheduleWatchCD, state: FSMContext,
    profile_service: ProfileService, schedule_service: ScheduleService, students_service: StudentsService,
    watch_targets_service: WatchTargetsService, extra_classes_service: ExtraClassesService,
    schedule_repo: ScheduleRepository, image_service: ImageGenerationService, image_prefs: ImagePreferencesService
) -> None:
    """Перехват выбора отслеживаемого класса."""
    actor_user_id = callback.from_user.id
    if not await image_prefs.prefers_image(actor_user_id): raise SkipHandler()
        
    target = await _resolve_schedule_target(
        actor_user_id=actor_user_id, target_kind="watch", target_id=callback_data.target_id,
        profile_service=profile_service, students_service=students_service, watch_targets_service=watch_targets_service
    )
    if not target: raise SkipHandler()
    await _save_schedule_target_to_fsm(state=state, actor_user_id=actor_user_id, target=target)
    await _render_and_send_target_poster(callback, target, state, actor_user_id, profile_service, schedule_service, students_service, watch_targets_service, extra_classes_service, schedule_repo, image_service)


@router.callback_query(F.data == callbacks.SCHEDULE_SMART_DAY, _image_generation_enabled)
async def select_smart_day_poster(
    callback: CallbackQuery, state: FSMContext,
    profile_service: ProfileService, schedule_service: ScheduleService, students_service: StudentsService,
    watch_targets_service: WatchTargetsService, extra_classes_service: ExtraClassesService,
    schedule_repo: ScheduleRepository, image_service: ImageGenerationService, image_prefs: ImagePreferencesService
) -> None:
    """Перехват 'К ближайшему дню'."""
    actor_user_id = callback.from_user.id
    if not await image_prefs.prefers_image(actor_user_id): raise SkipHandler()
        
    target = await _get_fsm_schedule_target(
        callback=callback, state=state, profile_service=profile_service,
        students_service=students_service, watch_targets_service=watch_targets_service
    )
    if not target: raise SkipHandler()
    await _render_and_send_target_poster(callback, target, state, actor_user_id, profile_service, schedule_service, students_service, watch_targets_service, extra_classes_service, schedule_repo, image_service)


@router.callback_query(ScheduleDayCD.filter(), _image_generation_enabled)
async def show_day_nav_poster(
    callback: CallbackQuery, callback_data: ScheduleDayCD, state: FSMContext,
    profile_service: ProfileService, schedule_service: ScheduleService, students_service: StudentsService,
    watch_targets_service: WatchTargetsService, extra_classes_service: ExtraClassesService,
    schedule_repo: ScheduleRepository, image_service: ImageGenerationService, image_prefs: ImagePreferencesService
) -> None:
    """Навигация по дням."""
    actor_user_id = callback.from_user.id
    if not await image_prefs.prefers_image(actor_user_id): raise SkipHandler()
        
    target = await _get_fsm_schedule_target(
        callback=callback, state=state, profile_service=profile_service,
        students_service=students_service, watch_targets_service=watch_targets_service
    )
    if not target: raise SkipHandler()
    
    await _render_and_send_target_poster(callback, target, state, actor_user_id, profile_service, schedule_service, students_service, watch_targets_service, extra_classes_service, schedule_repo, image_service, date_iso=callback_data.date_iso)


# ==========================================================
# ПЕРЕХВАТЧИКИ УЧИТЕЛЯ (ЧИСТЫЕ DTO)
# ==========================================================

async def _render_and_send_teacher_poster(
    callback: CallbackQuery, date_iso: str, teacher_id: str, teacher_name: str, state: FSMContext, actor_user_id: int, 
    schedule_service: ScheduleService, schedule_repo: ScheduleRepository, image_service: ImageGenerationService
):
    await state.update_data(poster_last_date=date_iso)
    
    try:
        poster, day_dto = await _build_teacher_day_poster(
            actor_user_id=actor_user_id, teacher_id=teacher_id, teacher_name=teacher_name,
            date_iso=date_iso, schedule_service=schedule_service, schedule_repo=schedule_repo, image_service=image_service
        )
    except RateLimitExceededError:
        await callback.answer("⏳ Слишком много запросов. Подождите пару минут.", show_alert=True)
        return
    except ImageRenderError:
        raise SkipHandler()
        
    kb = Keyboards.get_teacher_schedule_day_kb(
        current_date_iso=date_iso, teacher_id=teacher_id, 
        has_changes=_changes_count(day_dto) > 0, is_image=True
    )
    caption = build_day_caption(_format_date_text(date_iso), _changes_count(day_dto))
    
    await edit_poster(callback, image_service, poster, caption, kb)
    await callback.answer()


@router.callback_query(TeacherScheduleDayCD.filter(), _image_generation_enabled)
async def teacher_day_nav_poster(
    callback: CallbackQuery, callback_data: TeacherScheduleDayCD, state: FSMContext,
    profile_service: ProfileService, schedule_service: ScheduleService, schedule_repo: ScheduleRepository,
    image_service: ImageGenerationService, image_prefs: ImagePreferencesService,
) -> None:
    """Перехват навигации по дням для Учителя."""
    actor_user_id = callback.from_user.id
    if not await image_prefs.prefers_image(actor_user_id): raise SkipHandler()
        
    teacher = await _get_teacher_profile(user_id=actor_user_id, profile_service=profile_service)
    if not teacher: raise SkipHandler()
        
    teacher_name = await _teacher_name(teacher_id=teacher.teacher_id, schedule_service=schedule_service, fallback=teacher.name or "Учитель")
    await _render_and_send_teacher_poster(callback, callback_data.date_iso, teacher.teacher_id, teacher_name, state, actor_user_id, schedule_service, schedule_repo, image_service)


@router.callback_query(F.data == callbacks.TEACHER_SCHEDULE_SMART_DAY, _image_generation_enabled)
async def teacher_smart_day_poster(
    callback: CallbackQuery, state: FSMContext,
    profile_service: ProfileService, schedule_service: ScheduleService, schedule_repo: ScheduleRepository,
    image_service: ImageGenerationService, image_prefs: ImagePreferencesService,
) -> None:
    """Перехват 'К ближайшему дню' для Учителя."""
    actor_user_id = callback.from_user.id
    if not await image_prefs.prefers_image(actor_user_id): raise SkipHandler()
        
    teacher = await _get_teacher_profile(user_id=actor_user_id, profile_service=profile_service)
    if not teacher: raise SkipHandler()
        
    date_iso = await schedule_service.get_smart_teacher_target_date(teacher_id=teacher.teacher_id)
    teacher_name = await _teacher_name(teacher_id=teacher.teacher_id, schedule_service=schedule_service, fallback=teacher.name or "Учитель")
    
    await _render_and_send_teacher_poster(callback, date_iso, teacher.teacher_id, teacher_name, state, actor_user_id, schedule_service, schedule_repo, image_service)

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

    kb = Keyboards.get_schedule_day_kb(
        current_date_iso=date_iso, target_kind=target.kind, target_id=target.target_id,
        class_id=target.class_id, group_id=target.group_id, show_target_switch=len(targets) > 1,
        has_changes=_changes_count(day_dto) > 0, origin="class"
    )
    caption = build_day_caption(
        _format_date_text(date_iso),
        _changes_count(day_dto),
        _child_subtitle(target, actor_user_id),
    )
    await edit_poster(callback, image_service, poster, caption, kb)
    await callback.answer()

# ==========================================================
# ОДНОКРАТНЫЕ ТЕКСТОВЫЕ ФОЛБЭКИ (TRANSIENT STATE)
# ==========================================================

@router.callback_query(ScheduleForceTextCD.filter(), _image_generation_enabled)
async def force_text_schedule(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
    students_service: StudentsService,
    watch_targets_service: WatchTargetsService,
) -> None:
    """Однократный фолбэк на текст для ребенка/родителя. БД не меняется."""
    data = await state.get_data()
    date_iso = data.get("poster_last_date")
    if not date_iso:
        raise SkipHandler()

    target = await _get_fsm_schedule_target(
        callback=callback, state=state, profile_service=profile_service,
        students_service=students_service, watch_targets_service=watch_targets_service
    )
    if not target:
        raise SkipHandler()

    text, kb = await _render_day(
        actor_user_id=callback.from_user.id, target=target, date_iso=date_iso,
        profile_service=profile_service, schedule_service=schedule_service,
        students_service=students_service, watch_targets_service=watch_targets_service
    )
    
    await fallback_to_text(callback, text, kb)
    await callback.answer("Включен временный текстовый режим", show_alert=False)


@router.callback_query(TeacherForceTextCD.filter(), _image_generation_enabled)
async def force_text_teacher(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    schedule_service: ScheduleService,
) -> None:
    """Однократный фолбэк на текст для учителя. БД не меняется."""
    data = await state.get_data()
    date_iso = data.get("poster_last_date")
    actor_user_id = callback.from_user.id

    teacher = await _get_teacher_profile(user_id=actor_user_id, profile_service=profile_service)
    if not teacher or not date_iso:
        raise SkipHandler()

    teacher_name = await _teacher_name(
        teacher_id=teacher.teacher_id, schedule_service=schedule_service, fallback=teacher.name or "Учитель"
    )

    text, kb = await _render_teacher_day(
        teacher_id=teacher.teacher_id, date_iso=date_iso,
        teacher_name=teacher_name, schedule_service=schedule_service
    )

    await fallback_to_text(callback, text, kb)
    await callback.answer("Включен временный текстовый режим", show_alert=False)
    
@router.callback_query(ScheduleFormatToggleCD.filter())
async def toggle_poster_format(
    callback: CallbackQuery,
    image_prefs: ImagePreferencesService,
) -> None:
    """Переключает формат «картинка/текст» из команды /format."""
    if not config.ENABLE_IMAGE_GENERATION:
        await callback.answer(
            "⚠️ Сервис генерации картинок временно отключен администратором.",
            show_alert=True,
        )
        return

    prefer_image = await image_prefs.toggle(callback.from_user.id)
    current = "🖼 картинка" if prefer_image else "📝 текст"
    
    await callback.message.edit_text(
        f"Текущий формат расписания: {current}.\n\n"
        "Картинка — наглядный постер, текст — экономия трафика "
        "на медленном интернете.",
        reply_markup=Keyboards.get_format_toggle_kb(prefer_image),
    )
    await callback.answer(f"Формат изменен на: {current}")


@router.message(Command("format"))
async def cmd_format(message: Message, image_prefs: ImagePreferencesService) -> None:
    """Показ текущего формата расписания и кнопка переключения."""
    if not config.ENABLE_IMAGE_GENERATION:
        await message.answer(
            "⚠️ Сервис генерации картинок временно отключен администратором. "
            "Доступен только текстовый формат."
        )
        return

    prefer_image = await image_prefs.prefers_image(message.from_user.id)
    current = "🖼 картинка" if prefer_image else "📝 текст"
    
    await message.answer(
        f"Текущий формат расписания: {current}.\n\n"
        "Картинка — наглядный постер, текст — экономия трафика "
        "на медленном интернете.",
        reply_markup=Keyboards.get_format_toggle_kb(prefer_image),
    )
