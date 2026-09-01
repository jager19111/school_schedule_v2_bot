import logging
import datetime
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from services.profiles import ProfileService
from services.schedule_v2 import ScheduleServiceV2

logger = logging.getLogger(__name__)
router = Router()
tz = ZoneInfo("Asia/Novosibirsk")

async def get_children_keyboard(profile_service: ProfileService, parent_user_id: int, action: str) -> InlineKeyboardMarkup:
    """Формирует клавиатуру со списком детей родителя[cite: 4, 8]."""
    children = await profile_service.get_children_for_parent(parent_user_id)
    buttons = []
    for child in children:
        # child - словарь с ключами user_id, name, class_name
        btn_text = f"👦/👧 {child.get('name', 'Ребенок')} ({child.get('class_id', '')})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"p_{action}:{child['user_id']}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(F.text == "👨‍👩‍👧 Расписание детей")
async def parent_schedule_menu(message: Message, profile_service: ProfileService):
    user = await profile_service.get_user_profile(message.from_user.id)
    if not user or user.get('role') not in ('parent', 'observer'):
        return await message.answer("Эта команда доступна только родителям и наблюдателям.")
        
    kb = await get_children_keyboard(profile_service, message.from_user.id, "sched")
    if not kb.inline_keyboard:
        return await message.answer("К вашему профилю пока не привязан ни один ребенок. Используйте настройки семьи.")
        
    await message.answer("Выберите ребенка для просмотра расписания на сегодня:", reply_markup=kb)

@router.callback_query(F.data.startswith("p_sched:"))
async def show_child_schedule_today(callback: CallbackQuery, profile_service: ProfileService, schedule_service: ScheduleServiceV2):
    child_user_id = int(callback.data.split(":")[1])
    child_profile = await profile_service.get_user_profile(child_user_id)
    
    if not child_profile or not child_profile.get('class_id'):
        return await callback.answer("Профиль ребенка не настроен.", show_alert=True)
        
    today_iso = datetime.datetime.now(tz).date().isoformat()
    lessons = await schedule_service.get_daily_schedule_for_child(
        class_id=child_profile['class_id'], 
        group_id=child_profile['group_id'], 
        date_iso=today_iso
    )
    
    if not lessons:
        await callback.message.edit_text(f"На сегодня ({today_iso}) для этого ребенка уроков не найдено.")
        return await callback.answer()
        
    text_lines = [f"📅 <b>Расписание на сегодня ({today_iso})</b>\n"]
    for l in lessons:
        status = "🚫 ОТМЕНЕН" if l['is_cancelled'] else (f"🔄 (Замена)" if l['is_exchange'] else "")
        room = f"каб. {l.get('room_name', '—')}" 
        text_lines.append(f"{l['lesson_num']}. {l['start_time']}-{l['end_time']} | <b>{l['subject_name']}</b> {room} {status}")
        
    await callback.message.edit_text("\n".join(text_lines), parse_mode="HTML")
    await callback.answer()