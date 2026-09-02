import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from services.admin_service import AdminService
from bot.utils.ui_renderer import UIRenderer

logger = logging.getLogger(__name__)
router = Router()

@router.message(Command("stats"))
async def cmd_stats(message: Message, admin_service: AdminService):
    # Rule 2 & 8: Никаких SQL и проверок. Только вызов сервиса -> DTO -> Renderer[cite: 1].
    dto = await admin_service.get_statistics()
    text, kb = UIRenderer.render_admin_stats(dto)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")