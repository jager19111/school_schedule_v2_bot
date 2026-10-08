# Telegram-бот Школьного Расписания (v2)

Модульный Telegram-бот для автоматизированного отслеживания расписания, внеурочной деятельности и замен. Бот парсит данные непосредственно из JS-дампа системы NIKA, обеспечивая отказоустойчивость и независимость от структуры HTML.

## Особенности (v2)
* **Динамический парсинг NIKA:** Полный отказ от хардкода классов. Маппинг справочников (предметы, кабинеты, учителя, группы) происходит автоматически.
* **Семейная модель:** Объединение родителей и детей по `family_code`. Родители могут блокировать настройки уведомлений для детей.
* **Денормализованный SQLite-кэш:** Защита от дубликатов (UPSERT) с использованием строковых идентификаторов (включая маркер `ALL` для групп).
* **Умные уведомления:** Фоновый планировщик (`APScheduler`) работает строго в часовом поясе `Asia/Novosibirsk`, вычисляя динамическую дельту до начала урока. Изменения в расписании фильтруются в рамках заданного N-дневного окна.
* **Генерация постеров (v2.2):** PNG-постеры расписания через Chromium (`PlaywrightRenderer`, строго async API) с fallback на чистый `PillowRenderer` для слабых серверов. Semaphore=2, двухуровневый кэш с file_id, graceful degradation к тексту.
* **Garbage Collection:** Автоматическая очистка старых дампов `raw_nika_cache` (>7 дней) и "мягкое" отключение уведомлений для пользователей, неактивных более 60 дней.




## Telegram Mini App (`/tg/*`)

Telegram Mini App работает как дублер основного сайта: те же
templates, сервисы и расписания, отдельный только auth-bootstrap.

### Маршруты

| Маршрут | Назначение |
|---|---|
| `GET /tg/app` | Entry-экран Mini App (public). Загружает SDK, читает `initData`, отправляет на `/tg/bootstrap` |
| `POST /tg/bootstrap` | Валидация подписи `initData` (HMAC, bot token) → session с `surface="telegram"` |
| `POST /tg/browser-handoff` | Кнопка «Открыть в браузере»: выдаёт одноразовый код (TTL 120 сек) — только для telegram-сессии |
| `GET /tg/browser/consume` | Внешний браузер: consume кода → browser-сессия → 303 на чистый URL |

### Поток
Бот (WebApp-кнопка) → /tg/app → initData → /tg/bootstrap
→ session surface=telegram (WebView)
→ [скрепка] /tg/browser-handoff → openLink()
→ внешний браузер /tg/browser/consume?code=...
→ browser-сессия → PWA


### Файлы

- `web/routes/telegram_app.py` — все `/tg/*` маршруты
- `web/telegram/` — слой surface (только для Mini App)
- `services/telegram_webauth_service.py` — валидация initData
- `services/browser_handoff_service.py` — одноразовые коды перехода
- `core/repository/browser_handoff_repository.py` — SQL-слой кодов
- `web/templates/tg/`, `web/static/js/tg-app.js` — UI bootstrap
- `web/static/js/telegram-webapp.js` — адаптер (BackButton/openLink/theme)

### Инварианты

- `surface` в `web_sessions` (`telegram` / `browser`) — источник
  истины для условного рендера и guard'ов; не доверять query-параметрам.
- Handoff-код: одноразовый, в БД только SHA-256, target — allowlist
  (`ALLOWED_TARGET_PATHS`), TTL 120 сек.
- Повторное открытие Mini App переиспользует telegram-сессию;
  повторный handoff из того же браузера переиспользует browser-сессию.
- SW не регистрируется в WebView (`data-surface` на `<body>`,
  guard в `app.js`).
- `Set-Cookie` в `/tg/browser-handoff`-подобных роутах ставится на
  **возвращаемый** `RedirectResponse`, не на инжектированный `response`
  (см. `test_consume_sets_cookie_on_redirect`).
- CSRF: `/tg/bootstrap` в `EXEMPT_PATHS` (защита — подпись initData);
  `/tg/browser-handoff` требует `X-CSRF-Token`.

### Отключение

`WEB_TG_APP_ENABLED=0` — бот возвращается к legacy magic-link
(`/auth#token=...`), маршруты `/tg/*` остаются рабочими.

### Тесты
pytest -q tests/web/test_telegram_init_data.py
tests/web/test_browser_handoff.py
tests/web/test_tg_app_regression.py


Регрессия «PWA замерзает при отозванной сессии» ловится
`test_htmx_401_returns_hx_redirect`; «сессия создана, но браузер
не вошёл» — `test_consume_sets_cookie_on_redirect`.










## Требования
* Python 3.10+ (CI зафиксирован на 3.12)
* `aiogram` 3.x
* `aiosqlite`
* `apscheduler`
* `aiohttp`
* `playwright` 1.58.2 (браузер ставится отдельно, см. ниже)
* `Pillow` 12.3.0

## Установка и запуск
1. Клонируйте репозиторий.
2. Создайте виртуальное окружение: `python3 -m venv venv && source venv/bin/activate`.
3. Установите зависимости: `pip install -r requirements.txt`.
4. Скопируйте `.env.example` в `.env` и укажите `BOT_TOKEN`, `DB_PATH`, и `PROXY_URL` (при необходимости).
5. Для рендера постеров однократно установите браузер: `playwright install chromium --with-deps`. На слабых серверах без Chromium используйте `IMAGE_RENDER_ENGINE=pillow`.
6. Запустите бота: `python main.py`.

> **Фиксация версий (ТЗ v2.2):** Python 3.12 (CI), `playwright==1.58.2` —
> начиная с 1.57 Playwright поставляет Chrome for Testing вместо classic
> Chromium (кроме ARM64 Linux). Обновляйте пин осознанно: между версиями
> Playwright меняет bundled-браузер. В проекте используется только async API
> Playwright — sync-примеры из документации несовместимы с aiogram.
