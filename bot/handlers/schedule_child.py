import datetime
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.types import Message
from services.profiles import ProfileService
from services.schedule_v2 import ScheduleServiceV2

router = Router()
tz = ZoneInfo("Asia/Novosibirsk") # Жесткая изоляция таймзоны[cite: 5, 7]

@router.message(F.text == "📅 Сегодня")
async def show_today(message: Message, profile_service: ProfileService, schedule_service: ScheduleServiceV2):
    user = await profile_service.get_user_profile(message.from_user.id)
    if not user or not user.get('class_id'):
        return await message.answer("Пожалуйста, сначала выберите класс в настройках или через /start.")
    
    today_iso = datetime.datetime.now(tz).date().isoformat()
    
    # Фильтрация расписания по конкретному классу и группе (без хардкода)[cite: 7]
    lessons = await schedule_service.get_daily_schedule_for_child(
        class_id=user['class_id'], 
        group_id=user['group_id'], 
        date_iso=today_iso
    )
    
    if not lessons:
        return await message.answer("На сегодня уроков не найдено или расписание еще не загружено.")
        
    text_lines = [f"📅 <b>Расписание на сегодня ({today_iso})</b>\n"]
    for l in lessons:
        status = "🚫 ОТМЕНЕН" if l['is_cancelled'] else (f"🔄 (Замена)" if l['is_exchange'] else "")
        # Используем .get() для защиты от пустых значений[cite: 7]
        room = f"каб. {l.get('room_name', '—')}" 
        text_lines.append(f"{l['lesson_num']}. {l['start_time']}-{l['end_time']} | <b>{l['subject_name']}</b> {room} {status}")
        
    await message.answer("\n".join(text_lines), parse_mode="HTML")