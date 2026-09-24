import asyncio
from vkbottle.bot import Bot, Message

# Вставьте сюда токен, который вы получили в настройках группы VK
VK_TOKEN = "vk1.a.M5IFkPW9Y3AZlTLd0-AlgsT3OPNFmrPpbuX-EvCTEfru5mUxquit-0m_c8VTz_iKvdVzH2ZU4awgMHG0GWE7r9jxz24vAKHtDJshV6qklMzYGfVhNrxOp8uPja6oH72dYpd11hZ3X_OE2sCwN2xlGV9jog2z0_2O0ry7t5MOwK2r3F9xHnePGGJSBrSUjySvC9DwqkRbI8V8WZRwqtBbXA"

bot = Bot(token=VK_TOKEN)

@bot.on.message(text=["/start", "Привет", "test"])
async def hello_handler(message: Message):
    await message.answer("Привет! Я жив и успешно получаю сообщения!")

@bot.on.message()
async def echo_handler(message: Message):
    await message.answer(f"Ты написал: {message.text}. Тест пройден!")

if __name__ == "__main__":
    print("Запускаем VK-бота... Напишите сообщение в группу.")
    bot.run()  # <-- Правильный метод запуска в новых версиях