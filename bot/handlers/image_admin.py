"""Админские хендлеры статистики рендера.

Этот модуль подключается в main.py после admin.router или объединяется
с существующим bot/handlers/admin.py на этапе ревью.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services.admin_service import AdminService
from services.image_render.admin import get_image_stats_view
from services.image_render.admin_stats import render_image_stats
from services.image_render.service import ImageGenerationService

router = Router()


async def require_admin(message: Message, admin_service: AdminService) -> bool:
    if admin_service.is_admin(user_id=message.from_user.id):
        return True
    await message.answer("⛔ Команда доступна только администратору.")
    return False


@router.message(Command("img_stats"))
async def cmd_image_stats(
    message: Message,
    admin_service: AdminService,
    image_service: ImageGenerationService,
) -> None:
    if not await require_admin(message, admin_service):
        return
    view = get_image_stats_view(image_service)
    await message.answer(render_image_stats(view), parse_mode="HTML")
