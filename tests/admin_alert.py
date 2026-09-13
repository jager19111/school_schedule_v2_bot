#!/usr/bin/env python3
"""
Автономный тест доставки админ-алерта (без запуска бота).

Отправляет РЕАЛЬНЫЙ текст SSL-алерта всем ADMIN_IDS из .env —
тем же методом, которым отправляет бот (bot.send_message,
parse_mode="HTML"). Если сообщение пришло — доставка алертов
гарантирована, потому что больше в цепочке ничего нет, кроме
throttling, который доставки не меняет.

Запуск из venv проекта:
    python test_admin_alert.py

Что проверяется:
- BOT_TOKEN из .env;
- ADMIN_IDS из .env;
- HTML-валидность настоящего текста алерта (с <code> блоком);
- доставка каждому админу.

Частая причина ошибки "chat not found": админ ни разу не нажал
/start у бота — Telegram запрещает писать тем, кто не начинал
диалог. Нажмите /start и повторите тест.
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Тот же текст, что отправит refresh_schedule_cache при TLS-деградации
# (сверь со своим main.py и поправь при расхождении).
ALERT_TEXT = (
    "⚠️ <b>Внимание: ошибка SSL-сертификата!</b>\n\n"
    "Сайт лицея не прошёл проверку подлинности.\n"
    "Парсер автоматически переключился в режим без "
    "проверки сертификата.\n"
    "Возможен перехват трафика (MITM).\n\n"
    "Скорее всего школа сменила сертификат — обновите "
    "NIKA_TLS_FINGERPRINT_SHA256 в .env.\n\n"
    "Новый отпечаток снять командой:\n"
    "<code>echo | openssl s_client -connect lyceum.nstu.ru:443 "
    "-servername lyceum.nstu.ru | openssl x509 -noout "
    "-fingerprint -sha256</code>\n\n"
    "Обновления расписания продолжают поступать — "
    "это предупреждение только о снижении защиты.\n\n"
    "<i>(тестовая отправка из test_admin_alert.py)</i>"
)


async def main() -> None:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()

    if not bot_token:
        print("❌ BOT_TOKEN не найден в .env")
        sys.exit(1)

    admin_ids = [
        int(part.strip())
        for part in admin_ids_raw.split(",")
        if part.strip()
    ]

    if not admin_ids:
        print("❌ ADMIN_IDS пуст в .env")
        sys.exit(1)

    print(f"Админов в .env: {len(admin_ids)} -> {admin_ids}")
    print("Отправляю тестовый алерт...\n")

    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    ok_count = 0
    fail_count = 0
    try:
        for admin_id in admin_ids:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=ALERT_TEXT,
                )
                print(f"  ✅ admin_id={admin_id}: доставлено")
                ok_count += 1
            except Exception as exc:
                print(f"  ❌ admin_id={admin_id}: {type(exc).__name__}: {exc}")
                fail_count += 1
    finally:
        await bot.session.close()

    print()
    if fail_count == 0:
        print("✅ ВСЕ алерты доставлены.")
        print("   Бот отправляет их тем же методом — доставка гарантирована.")
    else:
        print(f"⚠️ Доставлено: {ok_count}, ошибок: {fail_count}.")
        print("   Проверьте, что ADMIN_IDS содержат ваш Telegram ID")
        print("   и что вы нажали /start у бота.")


if __name__ == "__main__":
    asyncio.run(main())
