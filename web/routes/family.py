# web/routes/family.py
#
# Экран «Семья» (Phase 4, ТЗ 33-34): участники, student profiles (CRUD),
# приглашения, права взрослых на доп. занятия.
#
# Правила:
# - только существующие методы ProfileService / StudentsService
#   (SQL и бизнес-логика — там); routes не дублируют её;
# - admin-проверки выполняют сами сервисы (None/False => 403 здесь);
# - все mutations — POST + CSRF (глобальный hx-headers);
# - actor — из сессии; family_id — только из профиля actor'а.

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from services.web_sessions_service import WebSessionContext
from web.deps import require_family_allowed
from web.mappers import (
    family_members_to_web,
    invite_result_to_web,
    invites_to_web,
    permissions_to_web,
    student_cards_to_web,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _profile_service(request: Request):
    return request.app.state.profile_service


def _students_service(request: Request):
    return request.app.state.students_service


def _schedule_service(request: Request):
    return request.app.state.schedule_service


def _templates(request: Request):
    return request.app.state.templates


def _bot_username(request: Request) -> Optional[str]:
    return getattr(request.app.state.web_settings, "bot_username", None)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


async def _family_ctx(
    request: Request, context: WebSessionContext
) -> Optional[dict]:
    """Профиль actor'а + family_id + admin-флаг + участники. None => не в семье."""
    profile_service = _profile_service(request)
    dto = await profile_service.get_user_profile_dto(context.user_id)
    family_id = getattr(dto, "family_id", None) if dto else None
    if not family_id:
        return None
    is_admin = await profile_service.is_family_admin(
        user_id=context.user_id, family_id=family_id
    )
    members = await profile_service.get_family_members(family_id)
    return {
        "dto": dto,
        "family_id": int(family_id),
        "is_admin": bool(is_admin),
        "members": members or [],
    }


async def _family_view(
    request: Request,
    context: WebSessionContext,
    *,
    invite_result=None,
) -> dict:
    """Контекст шаблона _family_content.html (страница и fragment)."""
    fctx = await _family_ctx(request, context)
    if fctx is None:
        return {"no_family": True, "csrf_token": context.csrf_token}

    profile_service = _profile_service(request)
    students_service = _students_service(request)
    dicts = await _schedule_service(request).get_school_dictionaries()

    # Student profiles: только взрослым (как в боте).
    students = []
    if getattr(fctx["dto"], "role", None) in ("parent", "observer"):
        students = await students_service.get_students_for_adult(
            adult_user_id=context.user_id
        )

    invites = []
    if fctx["is_admin"]:
        active = await profile_service.get_active_family_invites(
            admin_user_id=context.user_id, family_id=fctx["family_id"]
        )
        invites = active or []

    members_web = family_members_to_web(fctx["members"], current_user_id=context.user_id)
    return {
        "no_family": False,
        "is_admin": fctx["is_admin"],
        "members": members_web,
        "students": student_cards_to_web(
            students, classes=dict(dicts.classes), groups=dict(dicts.groups)
        ),
        "invites": invites_to_web(invites),
        "invite_result": invite_result,
        "classes": sorted(dicts.classes.items(), key=lambda kv: kv[1]),
        "groups": sorted(dicts.groups.items(), key=lambda kv: kv[1]),
        "csrf_token": context.csrf_token,
    }


def _render_family(request: Request, context: WebSessionContext, view: dict):
    """Fragment для HTMX, полная страница для обычного запроса."""
    template = (
        "family/_family_content.html"
        if _is_htmx(request)
        else "family/family.html"
    )
    return _templates(request).TemplateResponse(request, template, view)


# ==============================================================
# Экран «Семья»
# ==============================================================


@router.get("/family", response_class=HTMLResponse)
async def family_page(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    view = await _family_view(request, context)
    return _render_family(request, context, view)


# ==============================================================
# Приглашения (ТЗ 34; admin-only — проверяет сам сервис)
# ==============================================================


@router.post("/family/invites")
async def create_invite(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
    role: str = Form(...),
):
    if role not in ("child", "parent", "observer"):
        raise HTTPException(status_code=422, detail="Недопустимая роль.")

    fctx = await _family_ctx(request, context)
    if fctx is None:
        raise HTTPException(status_code=403, detail="Вы не состоите в семье.")

    invite = await _profile_service(request).create_family_invite(
        created_by_user_id=context.user_id,
        family_id=fctx["family_id"],
        intended_role=role,
        expires_in_hours=24,
    )
    if invite is None:
        # Сервис уже проверил admin-права: без объяснения деталей.
        raise HTTPException(status_code=403, detail="Только администратор семьи может создавать приглашения.")

    result = invite_result_to_web(invite, kind="family", bot_username=_bot_username(request))
    view = await _family_view(request, context, invite_result=result)
    return _render_family(request, context, view)


@router.post("/family/invites/{invite_id}/revoke")
async def revoke_invite(
    request: Request,
    invite_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
):
    fctx = await _family_ctx(request, context)
    if fctx is None:
        raise HTTPException(status_code=403, detail="Вы не состоите в семье.")

    revoked = await _profile_service(request).revoke_family_invite(
        invite_id=invite_id, family_id=fctx["family_id"], admin_user_id=context.user_id
    )
    if not revoked:
        raise HTTPException(status_code=403, detail="Приглашение уже недействительно.")

    view = await _family_view(request, context)
    return _render_family(request, context, view)


# ==============================================================
# Student profiles: создание / правка / удаление / claim-ссылка
# ==============================================================


def _require_admin(fctx: dict) -> None:
    if fctx is None:
        raise HTTPException(status_code=403, detail="Вы не состоите в семье.")
    if not fctx["is_admin"]:
        raise HTTPException(status_code=403, detail="Только администратор семьи.")


@router.get("/family/students/new", response_class=HTMLResponse)
async def new_student_form(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
):
    fctx = await _family_ctx(request, context)
    _require_admin(fctx)
    dicts = await _schedule_service(request).get_school_dictionaries()
    return _templates(request).TemplateResponse(
        request,
        "family/_student_form.html",
        {
            "mode": "create",
            "student": None,
            "classes": sorted(dicts.classes.items(), key=lambda kv: kv[1]),
            "groups": sorted(dicts.groups.items(), key=lambda kv: kv[1]),
            "csrf_token": context.csrf_token,
        },
    )


@router.post("/family/students")
async def create_student(
    request: Request,
    context: WebSessionContext = Depends(require_family_allowed),
    name: str = Form(...),
    class_id: str = Form(...),
    group_id: str = Form(...),
):
    fctx = await _family_ctx(request, context)
    _require_admin(fctx)

    name = name.strip()
    if not name or len(name) > 64:
        raise HTTPException(status_code=422, detail="Имя: 1-64 символа.")

    response = await _students_service(request).create_virtual_student(
        admin_user_id=context.user_id,
        family_id=fctx["family_id"],
        name=name,
        class_id=class_id,
        group_id=group_id,
    )
    if not getattr(response, "success", False):
        raise HTTPException(status_code=403, detail="Не удалось добавить ученика.")

    # Полный возврат на экран семьи: обновятся и карточки, и selector.
    if _is_htmx(request):
        from fastapi.responses import Response

        return Response(status_code=200, headers={"HX-Redirect": "/family"})
    from fastapi.responses import Response

    return Response(status_code=303, headers={"Location": "/family"})


async def _student_for_admin(
    request: Request, context: WebSessionContext, student_id: int
):
    """Доступ к student profile: get_student_for_adult (проверка в сервисе)."""
    result = await _students_service(request).get_student_for_adult(
        adult_user_id=context.user_id, student_id=student_id
    )
    if result is None:
        raise HTTPException(status_code=403, detail="Профиль недоступен.")
    student, access = result
    if not getattr(access, "is_family_admin", False):
        raise HTTPException(status_code=403, detail="Только администратор семьи.")
    return student


@router.get("/family/students/{student_id}/edit", response_class=HTMLResponse)
async def edit_student_form(
    request: Request,
    student_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
):
    student = await _student_for_admin(request, context, student_id)
    dicts = await _schedule_service(request).get_school_dictionaries()
    return _templates(request).TemplateResponse(
        request,
        "family/_student_form.html",
        {
            "mode": "edit",
            "student": student,
            "classes": sorted(dicts.classes.items(), key=lambda kv: kv[1]),
            "groups": sorted(dicts.groups.items(), key=lambda kv: kv[1]),
            "csrf_token": context.csrf_token,
        },
    )


@router.post("/family/students/{student_id}/edit")
async def update_student(
    request: Request,
    student_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
    class_id: str = Form(...),
    group_id: str = Form(...),
):
    await _student_for_admin(request, context, student_id)
    response = await _students_service(request).update_student_profile(
        admin_user_id=context.user_id,
        student_id=student_id,
        class_id=class_id,
        group_id=group_id,
    )
    if not getattr(response, "success", False):
        raise HTTPException(status_code=403, detail="Не удалось сохранить профиль.")
    from fastapi.responses import Response

    return Response(status_code=200, headers={"HX-Redirect": "/family"})


@router.post("/family/students/{student_id}/delete")
async def delete_student(
    request: Request,
    student_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
):
    await _student_for_admin(request, context, student_id)
    response = await _students_service(request).delete_virtual_student(
        admin_user_id=context.user_id, student_id=student_id
    )
    if not getattr(response, "success", False):
        raise HTTPException(
            status_code=403,
            detail="Нельзя удалить ученика с подключённым Telegram.",
        )
    from fastapi.responses import Response

    return Response(status_code=200, headers={"HX-Redirect": "/family"})


@router.post("/family/students/{student_id}/claim")
async def create_claim_link(
    request: Request,
    student_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
):
    await _student_for_admin(request, context, student_id)
    invite = await _students_service(request).create_student_claim_invite(
        admin_user_id=context.user_id,
        student_id=student_id,
        expires_in_hours=24,
    )
    if invite is None:
        raise HTTPException(
            status_code=403,
            detail="Ссылка доступна только для виртуального ученика.",
        )
    result = invite_result_to_web(invite, kind="claim", bot_username=_bot_username(request))
    view = await _family_view(request, context, invite_result=result)
    return _render_family(request, context, view)


# ==============================================================
# Права взрослых на доп. занятия student profile
# ==============================================================


async def _permissions_view(
    request: Request, context: WebSessionContext, student_id: int, admin_user_id: int
) -> dict:
    permissions = await _profile_service(request).get_adult_student_extra_classes_permissions(
        admin_user_id=admin_user_id, student_id=student_id
    )
    if permissions is None:
        raise HTTPException(status_code=403, detail="Нет доступа к правам.")
    fctx = await _family_ctx(request, context)
    members_by_id = {
        m.user_id: m.name for m in family_members_to_web(fctx["members"], current_user_id=admin_user_id)
    }
    student = await _student_for_admin(request, context, student_id)
    return {
        "student_id": student_id,
        "student_name": str(getattr(student, "name", "") or "Ученик"),
        "permissions": permissions_to_web(
            permissions, admin_user_id=admin_user_id, members_by_id=members_by_id
        ),
        "csrf_token": context.csrf_token,
    }


@router.get("/family/students/{student_id}/permissions", response_class=HTMLResponse)
async def student_permissions(
    request: Request,
    student_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
):
    view = await _permissions_view(request, context, student_id, context.user_id)
    return _templates(request).TemplateResponse(
        request, "family/_permissions.html", view
    )


@router.post("/family/students/{student_id}/permissions/{adult_user_id}")
async def toggle_permission(
    request: Request,
    student_id: int,
    adult_user_id: int,
    context: WebSessionContext = Depends(require_family_allowed),
):
    # Текущее состояние — из сервиса, toggle атомарно применяет сервис.
    view = await _permissions_view(request, context, student_id, context.user_id)
    current = next(
        (p for p in view["permissions"] if p.adult_user_id == adult_user_id), None
    )
    if current is None:
        raise HTTPException(status_code=403, detail="Участник не найден.")

    changed = await _profile_service(request).set_adult_student_extra_classes_permission(
        admin_user_id=context.user_id,
        adult_user_id=adult_user_id,
        student_id=student_id,
        can_manage=not current.can_manage,
    )
    if not changed:
        raise HTTPException(status_code=403, detail="Не удалось изменить право.")

    view = await _permissions_view(request, context, student_id, context.user_id)
    return _templates(request).TemplateResponse(
        request, "family/_permissions.html", view
    )
