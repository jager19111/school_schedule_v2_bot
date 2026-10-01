# web/routes/settings.py
from __future__ import annotations


import logging


from fastapi import (
    APIRouter,
    Depends,
    Form,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
)


from core.mappers.watch_target_mapper import WatchTargetMapper
from services.schedule_service import ScheduleService
from services.watch_targets_service import WatchTargetsService
from services.web_sessions_service import (
    WebSessionContext,
    WebSessionsService,
)
from web.deps import (
    get_sessions_service,
    require_family_allowed,
)
from web.events import SessionRevoked
from web.mappers import (
    class_items_to_web,
    school_items_to_web,
    web_devices_to_web,
)


logger = logging.getLogger(__name__)
router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _schedule_service(request: Request) -> ScheduleService:
    return request.app.state.schedule_service


def _watch_targets_service(
    request: Request,
) -> WatchTargetsService:
    return request.app.state.watch_targets_service


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _ctx(
    request: Request,
    context: WebSessionContext,
    extra: dict,
) -> dict:
    base = {
        "csrf_token": context.csrf_token,
        "app": request.app.state.web_settings,
    }
    base.update(extra)
    return base


async def _devices_context(
    request: Request,
    context: WebSessionContext,
    sessions: WebSessionsService,
    *,
    error: str | None = None,
) -> dict:
    devices = await sessions.list_devices(
        user_id=context.user_id,
        current_session_hash=context.session_hash,
    )

    return _ctx(
        request,
        context,
        {
            "devices": web_devices_to_web(
                devices,
                time_service=request.app.state.time_service,
            ),
            "error": error,
        },
    )


async def _watch_targets_context(
    request: Request,
    context: WebSessionContext,
    *,
    error: str | None = None,
) -> dict:
    """
    Готовит Settings list personal watch targets.

    IDs расшифровываются один раз через existing WatchTargetMapper,
    который получает SchoolDictionariesDTO, а не raw NIKA structure.
    """
    watch_targets_service = _watch_targets_service(request)
    schedule_service = _schedule_service(request)

    targets = await watch_targets_service.get_targets(
        owner_user_id=context.user_id,
    )

    try:
        dictionaries = (
            await schedule_service.get_school_dictionaries()
        )
    except Exception as exc:
        logger.warning(
            "Не удалось получить school dictionaries "
            "для web watch targets пользователя %s: %s",
            context.user_id,
            exc,
        )
        dictionaries = None

    if dictionaries is None:
        return _ctx(
            request,
            context,
            {
                "targets": [],
                "error": (
                    error
                    or "Не удалось загрузить справочники школы. "
                    "Попробуйте позже."
                ),
                "dictionaries_unavailable": True,
            },
        )

    return _ctx(
        request,
        context,
        {
            "targets": WatchTargetMapper.to_view_models(
                targets,
                dictionaries,
            ),
            "error": error,
            "dictionaries_unavailable": False,
        },
    )


async def _watch_target_form_context(
    request: Request,
    context: WebSessionContext,
    *,
    error: str | None = None,
    selected_class_id: str = "",
    selected_group_id: str = "ALL",
) -> dict:
    """
    Подготавливает form add target.

    Web получает уже presentation-ready WebSchoolItem objects,
    а не raw dictionaries.
    """
    schedule_service = _schedule_service(request)

    try:
        dictionaries = (
            await schedule_service.get_school_dictionaries()
        )
    except Exception as exc:
        logger.warning(
            "Не удалось получить school dictionaries "
            "для watch target form пользователя %s: %s",
            context.user_id,
            exc,
        )
        dictionaries = None

    if dictionaries is None:
        return _ctx(
            request,
            context,
            {
                "classes": [],
                "groups": [],
                "selected_class_id": selected_class_id,
                "selected_group_id": selected_group_id,
                "error": (
                    error
                    or "Расписание школы ещё не загружено. "
                    "Попробуйте позже."
                ),
                "dictionaries_unavailable": True,
            },
        )

    return _ctx(
        request,
        context,
        {
            "classes": class_items_to_web(
                dictionaries.classes,
            ),
            "groups": school_items_to_web(
                dictionaries.groups,
            ),
            "selected_class_id": selected_class_id,
            "selected_group_id": selected_group_id,
            "error": error,
            "dictionaries_unavailable": False,
        },
    )


def _watch_targets_template_name(
    request: Request,
) -> str:
    return (
        "settings/_watch_targets_content.html"
        if _is_htmx(request)
        else "settings/watch_targets.html"
    )


def _watch_target_form_template_name(
    request: Request,
) -> str:
    return (
        "settings/_watch_target_form_content.html"
        if _is_htmx(request)
        else "settings/watch_target_form.html"
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    """
    Настройки current user.

    Подразделы:
    - отслеживаемые классы;
    - безопасность;
    - web sessions;
    - logout current device.
    """
    template_name = (
        "settings/_settings_content.html"
        if _is_htmx(request)
        else "settings/settings.html"
    )

    return _templates(request).TemplateResponse(
        request,
        template_name,
        _ctx(request, context, {}),
    )


@router.get(
    "/settings/watch-targets",
    response_class=HTMLResponse,
)
async def watch_targets_page(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    """
    Список personal отслеживаемых классов current user.
    """
    return _templates(request).TemplateResponse(
        request,
        _watch_targets_template_name(request),
        await _watch_targets_context(
            request,
            context,
        ),
    )


@router.get(
    "/settings/watch-targets/new",
    response_class=HTMLResponse,
)
async def new_watch_target_page(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    """
    Форма выбора класса и группы для нового watch target.
    """
    return _templates(request).TemplateResponse(
        request,
        _watch_target_form_template_name(request),
        await _watch_target_form_context(
            request,
            context,
        ),
    )


@router.post(
    "/settings/watch-targets",
    response_class=HTMLResponse,
)
async def create_watch_target(
    request: Request,
    class_id: str = Form(...),
    group_id: str = Form("ALL"),
    context: WebSessionContext = Depends(require_family_allowed),
):
    """
    Создаёт personal watch target.

    Form values не являются trusted:
    WatchTargetsService повторно валидирует class/group IDs
    по current SchoolDictionariesDTO.
    """
    schedule_service = _schedule_service(request)

    try:
        dictionaries = (
            await schedule_service.get_school_dictionaries()
        )
    except Exception as exc:
        logger.warning(
            "Не удалось получить school dictionaries "
            "при создании watch target пользователя %s: %s",
            context.user_id,
            exc,
        )

        return _templates(request).TemplateResponse(
            request,
            _watch_target_form_template_name(request),
            await _watch_target_form_context(
                request,
                context,
                error=(
                    "Расписание школы ещё не загружено. "
                    "Попробуйте позже."
                ),
                selected_class_id=class_id,
                selected_group_id=group_id,
            ),
            status_code=(
                200
                if _is_htmx(request)
                else 503
            ),
        )
    response = (
        await _watch_targets_service(
            request,
        ).add_target_from_school_dictionaries(
            owner_user_id=context.user_id,
            class_id=class_id,
            group_id=group_id,
            dictionaries=dictionaries,
        )
    )

    if not response.success:
        error_messages = {
            "duplicate": (
                "Этот класс и группа уже добавлены "
                "в отслеживание."
            ),
            "limit_reached": (
                "Достигнут лимит отслеживаемых классов: 10."
            ),
            "invalid_class": (
                "Выбранный класс больше не найден "
                "в расписании школы."
            ),
            "invalid_group": (
                "Выбранная группа больше не найдена "
                "в расписании школы."
            ),
        }

        return _templates(request).TemplateResponse(
            request,
            _watch_target_form_template_name(request),
            await _watch_target_form_context(
                request,
                context,
                error=error_messages.get(
                    response.error_code,
                    "Не удалось добавить отслеживаемый класс.",
                ),
                selected_class_id=class_id,
                selected_group_id=group_id,
            ),
        )

    if not _is_htmx(request):
        return RedirectResponse(
            url="/settings/watch-targets",
            status_code=303,
        )

    return _templates(request).TemplateResponse(
        request,
        "settings/_watch_targets_content.html",
        await _watch_targets_context(
            request,
            context,
        ),
    )


@router.post(
    "/settings/watch-targets/{target_id}/delete",
    response_class=HTMLResponse,
)
async def delete_watch_target(
    request: Request,
    target_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
):
    """
    Удаляет target только при owner_user_id == current authenticated user.
    """
    response = await _watch_targets_service(
        request,
    ).delete_target(
        owner_user_id=context.user_id,
        target_id=target_id,
    )

    if not response.success:
        error = (
            "Отслеживаемый класс уже удалён "
            "или недоступен."
        )
    else:
        error = None

    if not _is_htmx(request):
        return RedirectResponse(
            url="/settings/watch-targets",
            status_code=303,
        )

    return _templates(request).TemplateResponse(
        request,
        "settings/_watch_targets_content.html",
        await _watch_targets_context(
            request,
            context,
            error=error,
        ),
    )


@router.get(
    "/settings/devices",
    response_class=HTMLResponse,
)
async def settings_devices_page(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
    sessions: WebSessionsService = Depends(get_sessions_service),
):
    """
    Экран active web sessions current user.

    Показывает только собственные sessions пользователя.
    """
    template_name = (
        "settings/_devices_content.html"
        if _is_htmx(request)
        else "settings/devices.html"
    )

    return _templates(request).TemplateResponse(
        request,
        template_name,
        await _devices_context(
            request,
            context,
            sessions,
        ),
    )


@router.post(
    "/settings/devices/{session_id}/revoke",
    response_class=HTMLResponse,
)
async def revoke_other_device(
    request: Request,
    session_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
    sessions: WebSessionsService = Depends(get_sessions_service),
):
    """
    Отзывает только другой web-сеанс пользователя.

    Current device здесь не отзываем: для него существует отдельное
    действие «Выйти с этого устройства».
    """
    if session_id == context.session_id:
        return _templates(request).TemplateResponse(
            request,
            "settings/_devices_content.html",
            await _devices_context(
                request,
                context,
                sessions,
                error=(
                    "Текущий сеанс нельзя завершить из списка устройств. "
                    "Используйте кнопку «Выйти с этого устройства»."
                ),
            ),
        )

    revoked = await sessions.revoke_session_by_id(
        session_id=session_id,
        user_id=context.user_id,
    )

    if not revoked:
        return _templates(request).TemplateResponse(
            request,
            "settings/_devices_content.html",
            await _devices_context(
                request,
                context,
                sessions,
                error=(
                    "Этот веб-сеанс уже завершён или недоступен."
                ),
            ),
        )

    bus = getattr(
        request.app.state,
        "event_bus",
        None,
    )

    if bus is not None:
        await bus.publish(
            SessionRevoked(
                user_id=context.user_id,
                session_id=session_id,
            )
        )

    return _templates(request).TemplateResponse(
        request,
        "settings/_devices_content.html",
        await _devices_context(
            request,
            context,
            sessions,
        ),
    )