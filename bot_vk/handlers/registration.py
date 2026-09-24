import logging
import json
from vkbottle.bot import BotLabeler, Message
from vkbottle import BaseStateGroup
from vkbottle.dispatch.dispenser.builtin import BuiltinStateDispenser

from bot_vk.utils.ui_renderer import VKUIRenderer
from bot_vk.keyboards import VKKeyboards
from services.profiles_service import ProfileService

logger = logging.getLogger(__name__)
labeler = BotLabeler()

VK_ID_OFFSET = 100_000_000_000

class RegistrationStates(BaseStateGroup):
    WAITING_FOR_ROLE = 0
    WAITING_FOR_NAME = 1
    WAITING_FOR_FAMILY_CODE = 2  # <-- Новый шаг

@labeler.message(text=["/start", "Привет", "Начать", "Меню"])
async def cmd_start(message: Message, profile_service: ProfileService, state_dispenser: BuiltinStateDispenser):
    db_user_id = message.from_id + VK_ID_OFFSET
    
    await profile_service.register_user_initial(db_user_id)
    user_dto = await profile_service.get_user_profile_dto(db_user_id)
    
    if user_dto.is_fully_registered:
        text = VKUIRenderer.render_already_registered(user_dto.role)
        return await message.answer(text)
        
    text = VKUIRenderer.render_welcome_new_user()
    kb = VKKeyboards.get_role_selection()
    
    await message.answer(text, keyboard=kb)
    await state_dispenser.set(message.peer_id, RegistrationStates.WAITING_FOR_ROLE)


@labeler.message(state=RegistrationStates.WAITING_FOR_ROLE)
async def process_role(message: Message, profile_service: ProfileService, state_dispenser: BuiltinStateDispenser):
    db_user_id = message.from_id + VK_ID_OFFSET
    
    role = None
    if message.payload:
        try:
            role = json.loads(message.payload).get("role")
        except json.JSONDecodeError:
            pass

    if role not in ["parent", "child", "observer"]:
        return await message.answer("Пожалуйста, воспользуйтесь кнопками ниже.", keyboard=VKKeyboards.get_role_selection())

    await profile_service.update_user_role(db_user_id, role)
    await message.answer("Как к вам обращаться? Введите ваше имя (например, Иван или Лиза):")
    await state_dispenser.set(message.peer_id, RegistrationStates.WAITING_FOR_NAME)


@labeler.message(state=RegistrationStates.WAITING_FOR_NAME)
async def process_name(message: Message, profile_service: ProfileService, state_dispenser: BuiltinStateDispenser):
    db_user_id = message.from_id + VK_ID_OFFSET
    name = message.text.strip()
    
    await profile_service.update_user_name(db_user_id, name)
    
    # Вместо обрыва регистрации — просим код из Telegram
    await message.answer(
        f"Отлично, {name}!\n\n"
        "Чтобы бот знал, чье расписание вам присылать, привяжите этот аккаунт к вашей семье.\n\n"
        "Зайдите в наш основной Telegram-бот ➔ Настройки ➔ Управление семьей ➔ скопируйте КОД СЕМЬИ и отправьте его сюда:"
    )
    await state_dispenser.set(message.peer_id, RegistrationStates.WAITING_FOR_FAMILY_CODE)


@labeler.message(state=RegistrationStates.WAITING_FOR_FAMILY_CODE)
async def process_family_code(message: Message, profile_service: ProfileService, state_dispenser: BuiltinStateDispenser):
    db_user_id = message.from_id + VK_ID_OFFSET
    code = message.text.strip().upper()
    
    user_dto = await profile_service.get_user_profile_dto(db_user_id)
    role = user_dto.role or "observer"
    
    # Пытаемся привязать пользователя к семье по коду
    success = await profile_service.link_child_to_parent(user_id=db_user_id, family_code=code, role=role)
    
    if not success:
        return await message.answer("❌ Код не найден или неверен. Проверьте правильность в Telegram и отправьте его снова:")
        
    await state_dispenser.delete(message.peer_id)
    await message.answer(
        "✅ Вы успешно подключились к семье!\n\n"
        "Теперь ВКонтакте работает как шлюз уведомлений: вы будете получать утренние сводки и алерты об изменениях в расписании.\n\n"
        "Для добавления кружков или тонкой настройки окон уведомлений используйте Telegram-бот."
    )

@labeler.message()
async def echo_handler(message: Message):
    text = VKUIRenderer.render_echo(message.text)
    await message.answer(text)