# Техническое задание

## School Schedule Web

### Полноценный веб-дублер Telegram-бота с единой БД, профилями и бизнес-логикой

> **Статус:** финальная версия ТЗ для начала разработки.
>
> **Первая версия:** локальное семейное использование через HTTPS-домен, закрытый на уровне инфраструктуры.
>
> **Уведомления:** Telegram является основным и единственным каналом уведомлений в Phase 1.
>
> **Web Push:** подготовить архитектурную возможность, реализацию оставить как TODO на будущее.

---

# 1. Цель проекта

Разработать полноценный веб-интерфейс существующего проекта `school_schedule_v2_bot`, который является вторым пользовательским интерфейсом той же системы, что и Telegram-бот.

Основная идея:

```text
                    School Schedule
                           │
                 ┌─────────┴─────────┐
                 │                   │
             Telegram               Web
                 │                   │
                 └─────────┬─────────┘
                           │
                     общие services
                           │
                         общая БД
```

Telegram и Web не должны иметь две независимые реализации бизнес-логики.

В обоих интерфейсах используются:

- одни и те же пользователи;
- одни и те же семьи;
- одни и те же `student profiles`;
- одни и те же расписания;
- одни и те же дополнительные занятия;
- одни и те же права доступа;
- одни и те же настройки;
- один источник данных.

Изменение информации через Telegram должно быть видно на сайте без отдельной синхронизации.

Изменение информации через сайт должно быть видно Telegram-боту без отдельной синхронизации.

---

# 2. Главный принцип архитектуры

Web — это не отдельное приложение с собственной предметной логикой.

Web является `frontend/interface layer` над существующим backend/domain layer проекта.

Основной принцип:

```text
Web UI
  ↓
FastAPI Web Layer
  ↓
Existing Services
  ↓
Existing Repositories
  ↓
SQLite
```

Запрещается:

- дублировать бизнес-логику Telegram-бота в web routes;
- создавать вторую систему расчёта расписания;
- создавать отдельную web БД;
- напрямую выполнять SQL из HTTP routes;
- хранить отдельные web-копии пользователей;
- хранить отдельные web-копии семей;
- хранить отдельные web-копии `student profiles`;
- создавать отдельную систему permissions.

Все бизнес-операции должны проходить через существующий service/repository layer либо через новые переиспользуемые сервисы, если существующей функциональности действительно недостаточно.

Web-specific код отвечает за:

- HTTP/HTML/API transport;
- authentication/session handling;
- request validation;
- web-specific response schemas;
- mapping domain DTO → web view/API model;
- UI state;
- SSE connection management.

---

# 3. Текущий deployment

На первом этапе система располагается на двух серверах.

## 3.1. Российский сервер

На российском сервере размещается Nginx/reverse proxy.

Он принимает HTTPS-запросы от локальных клиентов и проксирует их через NetBird на FastAPI на зарубежном сервере.

Пример:

```text
https://schedule.example.ru
        ↓
Nginx
        ↓
NetBird
        ↓
FastAPI
```

## 3.2. Зарубежный сервер

На зарубежном сервере остаётся основная система:

```text
Telegram Bot
Scheduler
Parser
FastAPI
Services
Repositories
SQLite
```

Web backend не должен переносить SQLite на российский сервер.

---

# 4. Домен и HTTPS

Домен и сертификат Let's Encrypt на российском сервере являются частью внешней инфраструктуры и не входят в основную реализацию web application.

Приложение с самого начала должно предполагать работу через HTTPS-домен:

```text
https://schedule.example.ru
```

На первом этапе домен может быть доступен только:

- из домашней сети;
- через WireGuard;
- через NetBird;
- через IP allowlist;
- через внутренний DNS.

Способ организации локального DNS, IP allowlist и получения/обновления сертификата не является частью web application.

Для приложения не должно иметь значения, публичный это сайт или закрытый.

Адрес сайта нельзя жёстко кодировать в исходном коде.

Использовать конфигурацию:

```env
WEB_PUBLIC_URL=https://schedule.example.ru
```

---

# 5. Сетевое разделение и защита backend

Российский Nginx:

```text
HTTPS :443
   ↓
NetBird
   ↓
FastAPI :8000
```

FastAPI должен быть доступен только через NetBird interface/firewall.

Российский сервер не получает доступа к файлу SQLite.

SQLite-файл никогда не монтируется на российский сервер через:

- NFS;
- SSHFS;
- SMB;
- сетевой filesystem;
- синхронизацию файла БД.

Российский сервер знает только HTTP endpoint backend.

## 5.1. Firewall

На зарубежном сервере разрешить доступ к порту FastAPI только от IP/peer российского Nginx по NetBird.

Наличие NetBird не отменяет необходимость firewall restriction.

## 5.2. Gateway secret

Дополнительно Nginx передаёт backend внутренний секретный заголовок, например:

```text
X-Web-Gateway-Key
```

Секрет:

- хранится только в environment variables;
- не хранится во frontend;
- не логируется;
- генерируется криптографически случайным образом.

FastAPI проверяет этот заголовок для обычных web/API requests.

`X-Web-Gateway-Key` подтверждает только, что запрос пришёл через доверенный gateway.

Он **не определяет пользователя**.

Нельзя реализовывать user authentication через:

```text
X-User-ID
X-Role
X-Family-ID
```

передаваемые клиентом или Nginx.

## 5.3. Forwarded headers

Так как TLS завершается на Nginx, FastAPI должен корректно обрабатывать:

```text
X-Forwarded-Proto
X-Forwarded-Host
X-Forwarded-For
```

и доверять этим заголовкам только от доверенного Nginx peer.

Uvicorn/FastAPI должен быть настроен на proxy headers с ограниченным `forwarded allow list`, а не доверять произвольному клиентскому `X-Forwarded-*`.

Это необходимо для:

- корректного определения HTTPS scheme;
- корректных redirect URL;
- корректной установки `Secure` cookies;
- корректной генерации абсолютных URL.

## 5.4. Host validation

Web application должна ограничивать допустимые `Host` headers через `TrustedHostMiddleware` или эквивалентную защиту.

Список допустимых hosts должен задаваться конфигурацией.

## 5.5. CORS

Поскольку Web UI и API работают с одного origin, отдельный CORS не требуется.

CORS не включать глобально. Если в будущем появится отдельный frontend origin или внешний client, разрешённые origins должны задаваться явным allowlist, а не через `*`.

---

# 6. Модель приложения

Проект должен рассматриваться как единый модульный backend:

```text
                   ┌────────────────┐
                   │     Telegram   │
                   │      Bot       │
                   └───────┬────────┘
                           │
                           │
                   ┌───────▼────────┐
                   │    Services    │
                   │                │
                   │ Schedule       │
                   │ Profiles       │
                   │ Students       │
                   │ ExtraClasses   │
                   │ Notifications  │
                   │ Time           │
                   └───────┬────────┘
                           │
                   ┌───────▼────────┐
                   │  Repositories  │
                   └───────┬────────┘
                           │
                     ┌─────▼─────┐
                     │   SQLite  │
                     └───────────┘
                           ▲
                           │
                   ┌───────┴────────┐
                   │     FastAPI    │
                   │    Web Layer   │
                   └───────┬────────┘
                           │
                   ┌───────▼────────┐
                   │     Nginx      │
                   └────────────────┘
```

---

# 7. Один процесс и одна SQLite

## 7.1. Общая модель

На текущем этапе Telegram Bot, APScheduler, FastAPI и все существующие services/repositories работают в **одном Python process и одном asyncio event loop**.

Все repositories используют существующее shared `aiosqlite.Connection`, созданное при старте приложения.

Это соответствует текущей архитектуре проекта: shared connection создаётся в `main.py`, передаётся repositories, а `BaseRepository` использует общий `asyncio.Lock` для сериализации транзакций данного физического соединения.

## 7.2. Запуск FastAPI

FastAPI должен запускаться внутри существующего `main()` через `uvicorn.Server(...).serve()` как asyncio task.

Концептуально:

```python
web_app = create_web_app(...)

uvicorn_config = uvicorn.Config(
    web_app,
    host=config.WEB_HOST,
    port=config.WEB_PORT,
    workers=1,
    loop="asyncio",
    reload=False,
    proxy_headers=True,
    forwarded_allow_ips=config.WEB_TRUSTED_PROXY_IPS,
)

web_server = uvicorn.Server(uvicorn_config)
web_task = asyncio.create_task(web_server.serve())
```

Не запускать Web отдельным процессом командой вроде:

```text
uvicorn web.app:app --workers 2
```

и не использовать Gunicorn с несколькими worker processes на текущем SQLite backend.

Uvicorn поддерживает `Server.serve()` для запуска из уже существующей asyncio environment. ([Uvicorn documentation](https://www.uvicorn.org/))

## 7.3. Обязательное ограничение

До перехода на PostgreSQL:

```text
workers = 1
reload = false
```

Не использовать:

```text
uvicorn --workers N
gunicorn -w N
```

для текущего backend.

Это ограничение относится к архитектуре с shared SQLite connection и in-process `asyncio.Lock`.

SQLite WAL допускает одновременные чтения и одного писателя. `asyncio.Lock` дополнительно сериализует транзакции между корутинами, использующими одно shared connection, но этот lock действует только внутри одного процесса.

## 7.4. Lifecycle

`main.py` является владельцем lifecycle всех подсистем.

При shutdown:

1. остановить приём новых web requests;
2. инициировать остановку FastAPI;
3. дождаться завершения `web_task`;
4. остановить scheduler;
5. завершить bot polling;
6. закрыть shared DB connection;
7. закрыть HTTP/TLS resources.

FastAPI не должен самостоятельно закрывать shared database connection.

---

# 8. Интеграция с существующим кодом

Web должен интегрироваться с существующей структурой проекта.

В первую очередь использовать:

```text
services/
    schedule_service.py
    profiles_service.py
    extra_classes_service.py
    students_service.py
    time_service.py
```

и существующие:

```text
core/repository/
core/models/
database/
```

Использовать существующий `ScheduleService`.

Не создавать параллельный `ScheduleServiceV2`.

Web должен использовать существующие DTO и существующие сервисные методы, когда они уже решают требуемую задачу.

Если существующего service method недостаточно, новый метод должен быть добавлен в переиспользуемый service layer, а не реализован в route.

---

# 9. Функциональный паритет с Telegram

Цель проекта — не просто сделать страницу для просмотра расписания.

Web должен стать полноценным альтернативным интерфейсом для повседневного использования.

Пользователь должен иметь возможность через сайт выполнять все основные пользовательские операции, которые доступны ему в Telegram-боте.

В начале разработки необходимо составить **feature parity matrix**:

```text
Telegram feature
    ↓
Web screen/action
    ↓
Existing service
    ↓
Permission
    ↓
Status: implemented / intentionally excluded
```

Нельзя считать Web готовым только на основании списка страниц в настоящем ТЗ.

Перед release должен существовать явный перечень пользовательских функций текущего Telegram-интерфейса и их web-аналогов.

Функциональность, связанная исключительно с внутренним техническим управлением бота, parser infrastructure или обслуживанием сервера, может быть исключена из Web, если она не предназначена для конечного пользователя.

---

# 10. Авторизация

Основной способ авторизации — Telegram identity.

Пользователь сайта должен попасть именно в существующий Telegram-профиль.

```text
Telegram user_id
        ↓
users
        ↓
family
        ↓
student_profiles
```

Нельзя создавать отдельную web identity.

Не использовать:

- логин/пароль;
- отдельный web username;
- hardcoded family ID как механизм authentication;
- `user_id` из query parameter;
- `family_id` из frontend;
- `role`, передаваемый браузером.

---

# 11. Telegram Magic Link

В Telegram-боте добавить действие:

```text
🌐 Открыть веб-версию
```

При нажатии генерируется криптографически случайный одноразовый login token.

Token должен иметь:

- минимум 32 random bytes;
- TTL = 5 минут;
- single-use;
- replay protection.

В БД хранить только:

```text
SHA-256(token)
```

Raw token в БД не хранить.

## 11.1. Формат ссылки

Использовать:

```text
https://schedule.example.ru/auth#token=RANDOM_TOKEN
```

а не:

```text
https://schedule.example.ru/auth?token=RANDOM_TOKEN
```

Frontend считывает token из URL fragment и передаёт его backend через HTTPS POST.

После успешного exchange token должен исчезнуть из URL.

## 11.2. Защита сообщения Telegram

Сообщение Telegram с login link является bearer credential и должно рассматриваться как временный секрет.

Дополнительно:

- сообщение желательно удалять ботом после истечения TTL либо вскоре после успешного использования;
- для приватного чата по возможности использовать `protect_content`;
- cleanup выполняется best-effort;
- ошибка удаления сообщения не продлевает жизнь token;
- token перестаёт работать независимо от того, удалено сообщение или нет.

Автоматическое удаление сообщения является **дополнительной защитой**, а не основным security mechanism.

Безопасность authentication обеспечивается комбинацией:

```text
short TTL
+
single-use
+
hashed token storage
+
opaque session
+
session revocation
```

## 11.3. Будущая альтернатива

При будущем public deployment допускается отдельная реализация authentication через Telegram Mini App с server-side validation `initData`.

`initDataUnsafe` не считать доверенным источником identity.

---

# 12. Формат login URL и exchange

Использовать:

```text
https://schedule.example.ru/auth#token=RANDOM_TOKEN
```

Frontend получает token из URL fragment и выполняет:

```text
POST /api/v1/auth/exchange
```

Backend:

1. проверяет token hash;
2. проверяет TTL;
3. атомарно убеждается, что token ещё не использован;
4. определяет Telegram `user_id`;
5. помечает login token как использованный;
6. создаёт web session;
7. устанавливает session cookie;
8. возвращает redirect/navigation result.

Повторное использование token должно возвращать `401`.

---

# 13. Web sessions

После успешного authentication exchange backend создаёт отдельную web session.

Cookie содержит только непрозрачный случайный session token:

```text
web_session=<random_token>
```

Cookie:

```text
HttpOnly
SameSite=Lax
Secure=true
Path=/
```

Не хранить в cookie:

```text
user_id
family_id
role
is_family_admin
permissions
student_id
```

## 13.1. Таблица `web_sessions`

Минимальные поля:

```text
id
session_hash
user_id
created_at
last_seen_at
expires_at
revoked_at
user_agent
```

Допускается добавить технические поля для управления сессией, если они не содержат лишних пользовательских данных.

`session_hash` — hash от random token, а не raw session token.

## 13.2. Lifetime

Рекомендуемые конфигурируемые значения:

```text
idle timeout: 90 days
absolute lifetime: 365 days
```

Значения не должны быть захардкожены в route code.

## 13.3. Server-side session resolution

На каждом authenticated HTTP request:

```text
web session token
        ↓
session lookup
        ↓
user_id
        ↓
ProfileService / family state
        ↓
актуальные role / family admin / permissions
```

Роль и права не должны восстанавливаться из browser cookie.

Если роль или family-admin status изменились в Telegram, существующая web session должна использовать новое состояние без повторного входа.

## 13.4. Session revocation

Поддержать:

- revoke текущей session;
- revoke конкретной session из device list;
- revoke всех sessions пользователя;
- expiration;
- cleanup старых sessions.

---

# 14. Multi-device support

Один Telegram profile может использовать Web одновременно на нескольких устройствах.

```text
Telegram user
     │
     ├── iPhone → web session A
     ├── iPad   → web session B
     ├── Mac    → web session C
     └── PC     → web session D
```

Каждое устройство получает независимую session.

Создание новой session никогда не должно автоматически инвалидировать существующие sessions.

Один `user_id` может иметь несколько активных web sessions.

## 14.1. Logout

Обычный:

```text
Выйти
```

отзывает только текущую session.

Дополнительно реализовать:

```text
Выйти на всех устройствах
```

который отзывает все активные sessions конкретного пользователя.

## 14.2. Device list

В разделе Settings предусмотреть:

```text
Активные устройства
```

Например:

```text
iPhone
Последняя активность: сегодня 21:43

[iPad]
Последняя активность: сегодня 20:17

Chrome / Windows
Последняя активность: вчера
```

с возможностью отозвать отдельную session.

`user_agent` использовать только для удобного отображения и диагностики; он не является фактором authentication.

## 14.3. Student profile

Наличие нескольких устройств не создаёт новые user/student profiles.

Расписание, дополнительные занятия, permissions и settings являются общими для пользователя и видны со всех его устройств через единую БД.

---

# 15. Authentication security

Auth endpoints должны иметь:

- rate limiting;
- single-use login token;
- token expiration;
- replay protection;
- отсутствие token в логах;
- отсутствие session token в логах;
- корректный logout.

Не логировать:

```text
login token
session token
cookie
CSRF token
Authorization header
```

Все authentication errors должны возвращать безопасное обобщённое сообщение, не раскрывающее состояние токена или существование конкретного пользователя.

---

# 16. CSRF

Все cookie-authenticated state-changing requests должны иметь CSRF protection.

Это относится ко всем:

```text
POST
PUT
PATCH
DELETE
```

включая:

- создание дополнительного занятия;
- изменение дополнительного занятия;
- удаление дополнительного занятия;
- изменение настроек;
- family administration;
- invitations;
- logout.

GET requests не должны иметь побочных эффектов.

## 16.1. Передача CSRF в HTMX

Поскольку основной frontend использует HTMX, необходимо реализовать централизованную передачу CSRF token во все HTMX requests.

Предпочтительный вариант:

```html
<body hx-headers='{"X-CSRF-Token": "<SERVER_GENERATED_TOKEN>"}'>
```

либо эквивалентный глобальный механизм через `htmx:configRequest`.

HTMX поддерживает `hx-headers` и `htmx:configRequest` для передачи/изменения request headers.

CSRF token не является session token и не должен совпадать с `web_session`.

Server должен проверять:

```text
session
+
CSRF token
+
request origin / same-origin policy
```

для state-changing requests.

## 16.2. Forms

Для обычных HTML forms разрешается использовать hidden CSRF input.

Для HTMX interactions предпочтительно использовать единый глобальный механизм, чтобы разработчик не мог случайно забыть CSRF token на отдельной mutation.

Все state-changing HTMX requests должны автоматически получать CSRF header.

## 16.3. HTMX dependency

Версии `htmx` и `htmx-ext-sse` должны быть явно зафиксированы.

Production JS dependencies предпочтительно хранить локально либо использовать CDN с точной версией и integrity hash.

---

# 17. Существующая модель семьи

Использовать существующую модель:

```text
families
users
student_profiles
```

Семья определяется backend по авторизованному пользователю.

Никакой hardcoded family ID в production code.

Для локального семейного режима допускается configuration-level allowlist:

```env
WEB_ACCESS_MODE=family_allowlist
WEB_ALLOWED_FAMILY_IDS=...
```

Allowlist является дополнительным ограничителем доступа, а не authentication mechanism.

---

# 18. Student profile model

В интерфейсе необходимо работать прежде всего со `student_profiles`.

Это важно, потому что ребёнок может существовать как student profile без собственного Telegram аккаунта.

Пример:

```text
Users:
    Мама
    Папа

Student profiles:
    Саша
    Маша
```

Родитель переключает расписание:

```text
Саша
Маша
```

но backend по-прежнему считает actor'ом родителя.

---

# 19. Actor / Target Authorization

Каждая операция должна логически разделять:

```text
actor_user_id
target_student_profile_id
```

Actor получается только из session.

Target передаётся из URL/API/form и затем проверяется backend.

После чего backend/service layer проверяет право actor работать с target.

Запрещена модель:

```text
GET /schedule?user_id=...
```

в которой любой авторизованный пользователь может подставить произвольный user ID.

Frontend не является security boundary.

---

# 20. Роли

Использовать существующую модель:

```text
parent
child
observer
teacher
```

Family admin определяется существующим механизмом семьи.

Family admin не должен превращаться в отдельную глобальную роль.

---

# 21. Единая система permissions

Telegram и Web должны использовать одинаковые правила доступа.

Например:

```text
parent → child schedule
parent → extra classes
child → own schedule
child → own extra classes, если разрешено
observer → только разрешённые действия
family admin → administrative family actions
```

Проверки прав должны выполняться backend/service layer.

Frontend только скрывает недоступные элементы UI, но это не считается security check.

Если существующего service-level permission API недостаточно, сначала расширить общий service layer, а не писать web-only ACL.

---

# 22. Главная страница — «Сегодня»

После авторизации открывается dashboard.

Основной контент:

```text
Моё расписание
```

Для пользователя с одним student profile сразу показать его расписание.

Для parent с несколькими детьми отображать выбранный student profile и быстрый переключатель.

---

# 23. Smart Schedule

Для автоматического выбора актуального дня использовать существующую бизнес-логику:

```python
ScheduleService.get_smart_day_schedule_for_student(...)
```

Не копировать smart-date algorithm в web.

Например:

```text
утро
→ сегодня

вечер после последнего урока
→ следующий актуальный учебный день
```

При ручном выборе конкретной даты smart-date не должен вмешиваться.

---

# 24. Отображение уроков

Каждый урок отображается карточкой.

Минимум:

```text
Время
Предмет
Учитель
Кабинет
Класс/группа
Статус
```

Поддержать существующие особые состояния:

```text
замена
отмена
изменение
дополнительное занятие
```

Не передавать в browser внутренние поля DTO, если они не нужны UI.

---

# 25. Дополнительные занятия

Дополнительные занятия отображаются в том же chronological timeline, что и школьные уроки.

Пример:

```text
09:00  Математика
10:00  Русский язык
16:00  Английский — дополнительное занятие
18:00  Робототехника — дополнительное занятие
```

Дополнительные занятия должны визуально отличаться от школьных уроков.

---

# 26. Навигация по дням

Поддержать:

```text
← предыдущий день
Сегодня
следующий день →
```

Переходы по датам не должны требовать полной перезагрузки страницы.

Предпочтительно использовать HTMX.

---

# 27. Экран «Неделя»

Показать расписание на неделю.

Использовать существующий:

```text
ScheduleService.get_week_schedule_summary(...)
```

для сводки.

Например:

```text
ПН   6 уроков
ВТ   7 уроков
СР   5 уроков
ЧТ   6 уроков
ПТ   6 уроков
```

Дополнительно показывать:

- количество замен;
- количество дополнительных занятий;
- наличие изменений.

По нажатию на день открывается подробное расписание.

---

# 28. Переключатель ребёнка

Для parent/observer с несколькими доступными student profiles реализовать быстрый selector:

```text
[ Саша ▼ ]
```

или аналогичный mobile-friendly компонент.

Выбор ребёнка меняет только target student profile, но не identity текущего пользователя.

---

# 29. Экран «Школа»

Web должен дать удобный интерфейс для просмотра расписания школы.

Основные сущности:

```text
Классы
Группы
Учителя
Кабинеты
```

---

# 30. Просмотр других расписаний

Поддержать:

```text
класс → расписание
учитель → расписание
кабинет → расписание
```

Минимально:

```text
сегодня
конкретный день
неделя
```

Использовать существующий `ScheduleService`.

Не создавать отдельный web algorithm для получения расписания.

---

# 31. Поиск

Экран «Школа» должен поддерживать mobile search:

```text
🔎 Математика
🔎 10А
🔎 Иванов
🔎 305
```

Результаты разделять по типу:

```text
Классы
Учителя
Кабинеты
```

---

# 32. Свободные кабинеты

В первой версии:

```text
Свободные кабинеты сейчас
```

использовать существующий:

```python
get_currently_free_rooms()
```

Дополнительно предусмотреть архитектурную возможность поиска свободного кабинета для произвольного временного интервала.

Например:

```text
26.09
14:00–15:00
```

---

# 33. Экран «Семья»

Для parent/family admin:

```text
Семья

Участники
Дети
Права
```

Поддержать:

- просмотр членов семьи;
- просмотр student profiles;
- переключение между детьми;
- управление дополнительными занятиями;
- family administration в соответствии с существующими permissions;
- invitations, если эта возможность присутствует в текущем Telegram-интерфейсе.

---

# 34. Family invitations

Использовать существующий механизм:

```text
family_invites
student_claim_invites
```

Не создавать вторую систему приглашений специально для Web.

Все операции выполнять через существующий `ProfileService`.

---

# 35. Настройки

Web должен предоставлять настройки, которые логически соответствуют настройкам Telegram-бота.

Минимально:

```text
Профиль
Уведомления
Дополнительные занятия
Сессии
Выйти
```

Настройки, относящиеся к уведомлениям Telegram, изменяются через существующий backend, которым пользуется бот.

---

# 36. Уведомления — текущая реализация

### Telegram является основным и единственным notification channel на этапе первой версии.

Уведомления:

- изменения расписания;
- изменения уроков;
- дополнительные занятия;
- напоминания;
- утренние сводки;
- другие существующие уведомления

продолжают отправляться Telegram-ботом.

Web не должен дублировать существующую логику отправки уведомлений.

---

# 37. Web Push — TODO

Web Push не реализуется в первой версии.

Однако архитектура `NotificationService` должна быть подготовлена к его добавлению в будущем.

Предусмотреть абстракцию:

```python
NotificationChannel
```

с текущей реализацией:

```python
TelegramNotificationChannel
```

и будущей:

```python
WebPushNotificationChannel
```

Бизнес-логика генерации уведомления не должна зависеть от конкретного транспорта.

Например:

```text
Schedule changed
        ↓
NotificationService
        ↓
Telegram channel
        ↓
Telegram user
```

В будущем:

```text
Schedule changed
        ↓
NotificationService
        ├── Telegram channel
        └── Web Push channel
```

---

# 38. Web Push future requirements

Web Push остаётся TODO и не входит в Phase 1.

Будущая реализация должна предусматривать:

- Service Worker для совместимого/расширенного сценария, где он требуется;
- Push API;
- PushSubscription;
- VAPID;
- хранение подписок;
- несколько устройств на одного пользователя;
- revoke subscription;
- expired/dead subscription cleanup;
- настройки notification channels;
- iOS Home Screen Web App;
- fallback на Telegram.

На Phase 1 никакой push subscription и VAPID infrastructure не создавать.

Для современных iOS/iPadOS допускается использовать Declarative Web Push, если он соответствует выбранному способу реализации. Не привязывать будущую архитектуру к единственному механизму service-worker-based push.

---

# 39. PWA

Поскольку production URL сразу предполагается HTTPS-доменом, реализовать PWA foundation уже в первой версии.

Обязательно:

```text
manifest.webmanifest
service worker
apple-touch-icon
PWA icons
display: standalone
start_url
theme_color
background_color
```

Service Worker в первой версии используется для:

```text
static assets
application shell
иконки
CSS
JS
manifest
другие безопасные неизменяемые ресурсы
```

Service Worker не является источником истины для персонального расписания.

Offline-режим для персонального расписания не является обязательной частью Phase 1.

---

# 40. iOS UX

Основная цель:

```text
Safari
+
Add to Home Screen
+
standalone app experience
```

UI должен корректно работать на:

```text
iPhone
iPad
Android
Desktop
```

Не использовать:

```html
maximum-scale=1.0
user-scalable=no
```

Использовать:

```html
viewport-fit=cover
```

и учитывать:

```css
env(safe-area-inset-top)
env(safe-area-inset-bottom)
```

для устройств с вырезами/home indicator.

Web Push не является обязательной частью установки PWA на Phase 1.

---

# 41. Mobile-first дизайн

Главный UX target:

```text
iPhone ~390–430 px
```

Но desktop должен использовать ту же систему.

Bottom navigation:

```text
Сегодня
Неделя
Школа
Семья
```

На desktop допускается преобразование в sidebar/top navigation.

Touch target:

```text
не менее ~44px
```

Интерфейс не должен требовать hover.

Не допускать horizontal overflow на типичных мобильных разрешениях.

---

# 42. Frontend stack

Предпочтительный стек:

```text
FastAPI
Jinja2
HTMX
vanilla JavaScript
CSS
```

React/Vue/Next.js не использовать без объективной необходимости.

Основной принцип:

```text
server-rendered HTML
+
HTMX для интерактивных участков
+
минимум client-side JS
```

JavaScript отвечает за:

- UI interactions;
- HTMX integration;
- SSE;
- PWA/service worker registration;
- визуальные эффекты;
- form interactions.

JavaScript не отвечает за бизнес-логику расписания.

---

# 43. Web backend structure

Предлагаемая структура:

```text
web/
├── app.py
├── dependencies.py
├── security.py
├── auth.py
├── sessions.py
├── middleware.py
├── exceptions.py
├── schemas.py
├── mappers.py
├── events.py
├── connections.py
│
├── routes/
│   ├── auth.py
│   ├── dashboard.py
│   ├── schedule.py
│   ├── school.py
│   ├── family.py
│   ├── extra_classes.py
│   └── settings.py
│
├── templates/
│   ├── base.html
│   ├── auth/
│   ├── dashboard/
│   ├── schedule/
│   ├── school/
│   ├── family/
│   ├── extra_classes/
│   └── components/
│
└── static/
    ├── css/
    ├── js/
    ├── icons/
    └── manifest.webmanifest
```

Структура может быть адаптирована к фактическому стилю существующего проекта, но слои ответственности должны сохраниться.

---

# 44. Web schemas и mapping layer

Web layer должен иметь собственные Pydantic-схемы/API models.

Например:

```text
WebLesson
WebDayScheduleResponse
WebWeekScheduleResponse
WebStudent
WebFamilyMember
WebExtraClass
WebSettings
```

Internal bot/domain DTO не должны автоматически становиться публичным JSON API contract.

Flow:

```text
domain DTO
      ↓
web mapper
      ↓
Web schema / ViewModel
      ↓
JSON / Jinja2
```

Преобразование выполняется в `web/mappers.py` либо эквивалентном web mapping layer.

Routes не должны самостоятельно собирать сложные web representations из database rows.

---

# 45. API versioning

Все JSON/API endpoints версионировать:

```text
/api/v1/...
```

Это необходимо для будущего public deployment и возможного мобильного клиента.

---

# 46. Основные endpoints

Authentication:

```text
GET  /auth
POST /api/v1/auth/exchange
POST /api/v1/auth/logout
GET  /api/v1/me
```

Schedule:

```text
GET /api/v1/schedule/today
GET /api/v1/schedule/day/{date}
GET /api/v1/schedule/week
GET /api/v1/schedule/stream
```

School:

```text
GET /api/v1/school/classes
GET /api/v1/school/groups
GET /api/v1/school/teachers
GET /api/v1/school/rooms
GET /api/v1/school/free-rooms
```

Family:

```text
GET /api/v1/family
GET /api/v1/family/members
GET /api/v1/family/students
```

Extra classes:

```text
GET    /api/v1/extra-classes
POST   /api/v1/extra-classes
PATCH  /api/v1/extra-classes/{id}
DELETE /api/v1/extra-classes/{id}
```

Settings:

```text
GET   /api/v1/settings
PATCH /api/v1/settings
```

Health:

```text
GET /health/live
GET /health/ready
```

Необходимо использовать HTML endpoints там, где HTMX делает интерфейс проще.

Для `/auth` предусмотреть корректную работу как в обычном Safari/Chrome, так и во встроенном Telegram browser. Если пользователь хочет установить сайт как Home Screen Web App на iOS, интерфейс должен явно подсказать открыть сайт в Safari, поскольку установка Home Screen выполняется средствами Safari.

---

# 47. API data exposure

Каждый endpoint отдаёт только данные, необходимые для конкретного интерфейса.

Особенно не отдавать frontend без необходимости:

- внутренние Telegram identifiers других пользователей;
- служебные поля;
- внутренние database IDs;
- административную информацию, к которой нет доступа;
- технические secrets;
- поля, используемые только Telegram-представлением.

Каждый JSON endpoint должен иметь явный `response_model`.

Например:

```python
@router.get(
    "/schedule/today",
    response_model=WebDayScheduleResponse,
)
async def get_today(...):
    ...
```

`response_model` используется как дополнительный security boundary: FastAPI фильтрует response до объявленной модели.

---

# 48. Content Security Policy и внешние ресурсы

Web application должна использовать строгую Content Security Policy.

Предпочтительная базовая policy:

```text
default-src 'self';
script-src 'self';
style-src 'self';
img-src 'self' data:;
font-src 'self';
connect-src 'self';
manifest-src 'self';
worker-src 'self';
object-src 'none';
base-uri 'self';
frame-ancestors 'none';
form-action 'self';
```

Конкретная policy может быть расширена только при реальной необходимости.

## 48.1. JavaScript dependencies

Для production предпочтительно хранить:

```text
htmx.js
htmx-ext-sse.js
application.js
```

локально:

```text
web/static/js/
```

с зафиксированными версиями.

Не использовать непинованные CDN URL без фиксации версии и integrity hash.

Локальная поставка предпочтительна из-за:

- строгого `script-src 'self'`;
- отсутствия runtime-зависимости от CDN;
- более предсказуемого PWA shell;
- контроля версий;
- уменьшения внешней supply-chain зависимости.

## 48.2. SSE и CSP

SSE endpoint должен быть разрешён через:

```text
connect-src 'self'
```

Не использовать:

```text
connect-src *
```

без объективной необходимости.

## 48.3. Inline JavaScript

Не использовать `unsafe-inline` без необходимости.

JavaScript размещать в `static/js/` либо использовать CSP nonce/hash для действительно необходимых inline scripts.

`hx-headers` HTML attribute для передачи CSRF не является inline JavaScript.

---

# 49. Cache policy

## 49.1. Общая политика

Персональные HTML/JSON responses не должны попадать в общий public/shared cache.

Для персональных данных использовать:

```text
Cache-Control: private, no-store
```

либо эквивалентную политику, исключающую выдачу содержимого одного пользователя другому.

Кэшировать разрешается:

```text
static assets
CSS
JS
icons
PWA manifest
application shell
school metadata
immutable assets
```

## 49.2. Service Worker cache

Service Worker cache не является источником истины для персонального расписания.

В Phase 1 не кэшировать персональные страницы вида:

```text
/
/schedule/day/YYYY-MM-DD
/api/v1/schedule/...
```

в универсальный Cache Storage только по URL.

Причина: персональное содержимое зависит от authenticated user/session, тогда как URL может быть одинаковым для разных пользователей.

Нельзя допустить:

```text
Пользователь A
    ↓
/schedule/day/2026-09-25
    ↓
Service Worker cache
    ↓
Пользователь B
    ↓
получает данные A
```

## 49.3. Offline schedule — будущее расширение

В будущем допускается реализация offline snapshot последнего просмотренного расписания.

Такая реализация должна быть явно user-scoped и учитывать:

- пользователя;
- выбранный student profile;
- account/session context;
- срок жизни snapshot;
- logout;
- смену пользователя;
- очистку данных.

Нельзя использовать простой глобальный Cache Storage entry для персонального расписания.

При logout локальные персональные данные приложения должны очищаться.

Допустимо использовать `Clear-Site-Data` либо явную очистку application-controlled storage. `Clear-Site-Data` поддерживает очистку cookies, cache и storage в поддерживаемых браузерах по HTTPS.

## 49.4. Server revalidation

При наличии сети персональное расписание должно запрашиваться у backend и проверяться на актуальность.

Service Worker может ускорять загрузку application shell, но не должен незаметно подменять актуальное персональное расписание устаревшим snapshot без явно определённой user-scoped offline strategy.

---

# 50. Error handling

API должен использовать стандартные HTTP статусы:

```text
400
401
403
404
409
422
429
500
503
```

Не показывать пользователю traceback.

Ошибки отображаются понятными сообщениями.

Например:

```text
Сайт временно не может получить актуальное расписание.
Последние доступные данные показаны ниже.
```

Authentication errors не должны раскрывать лишнюю информацию о token/session/user state.

---

# 51. Live UI updates

## 51.1. Цель

Если пользователь держит страницу расписания открытой, изменения расписания должны автоматически появляться в UI без ручного refresh.

Это механизм синхронизации **открытого web-интерфейса**.

Он не заменяет системные уведомления.

Phase 1 notification channel:

```text
Telegram
```

Future:

```text
Web Push
```

## 51.2. Механизм

Использовать:

```text
SSE + HTMX
```

Архитектура:

```text
Schedule changed
      ↓
application event
      ↓
in-process Event Manager
      ↓
SSE
      ↓
browser
      ↓
HTMX event
      ↓
authenticated GET
      ↓
актуальный HTML fragment
```

HTMX SSE extension поддерживает SSE connections, events и automatic reconnection.

## 51.3. Application events

После успешной фиксации изменения расписания формировать application event, например:

```text
ScheduleChanged
```

Event должен происходить **после успешного commit** соответствующего изменения.

Не использовать database polling для обнаружения изменений, если существующий service layer может сформировать событие непосредственно.

SSE connection manager подписывается на эти events.

## 51.4. SSE event не содержит персональные данные

SSE передаёт только минимальный invalidation signal:

```text
event: schedule_changed
data: {"revision": 123}
```

или эквивалентный минимальный payload.

SSE не должен передавать:

- персональное расписание;
- family data;
- student data;
- Telegram IDs;
- permissions.

После получения event browser выполняет обычный authenticated request за актуальным fragment.

Это позволяет использовать один и тот же invalidation signal независимо от того, какой student profile выбран на конкретном устройстве.

## 51.5. Reconnection

Использовать automatic reconnection, реализованное актуальной версией `htmx-ext-sse`.

Не реализовывать второй независимый reconnect loop без необходимости.

HTMX SSE extension поддерживает exponential-backoff reconnect поверх browser reconnect behavior.

После восстановления SSE:

```text
reconnect
   ↓
revalidate current screen
```

## 51.6. SSE connection и session

Каждое SSE connection принадлежит конкретной web session.

При установлении connection выполняется обычная authentication check.

Во время работы stream нельзя считать первоначальную authentication проверку достаточной для неограниченного времени существования соединения.

Использовать server-side connection manager внутри текущего single-process application.

Connection manager должен периодически проверять, что session не истекла и не была отозвана. Проверка должна происходить достаточно редко, чтобы не создавать лишнюю нагрузку на SQLite, но достаточно часто, чтобы закрывать недействительный stream без заметной задержки.

`last_seen_at` не должен обновляться самим SSE heartbeat бесконечно. Иначе открытая вкладка сможет бессрочно продлевать idle session без действий пользователя. Background SSE revalidation также не должна считаться пользовательской активностью при расчёте idle timeout, если это не предусмотрено явно.

Connection manager должен поддерживать связь:

```text
session_id
    ↓
active SSE connection(s)
```

Закрытые connections необходимо удалять из manager, чтобы не было утечек памяти.

## 51.7. Logout / revoke

При обычном logout текущая SSE connection должна завершаться.

При:

- Logout all devices;
- Session revoke;
- Family access revoke;

соответствующие SSE connections должны быть закрыты server-side best effort.

Использовать событие уровня authentication/session, например:

```text
SessionRevoked
```

Не связывать lifecycle session непосредственно с `NotificationService`.

После закрытия connection browser может попытаться reconnect.

Если session истекла естественным образом, reconnect также должен пройти обычную authentication check и быть отклонён.

Backend при следующем connection должен вернуть:

```text
401 Unauthorized
```

для недействительной session.

Даже если server-side close не сработал мгновенно, revoked session не должна получить персональные данные при следующей revalidation.

## 51.8. HTTP/2

Для production deployment на российском Nginx включить HTTP/2.

HTTP/1.1 имеет низкий per-origin limit долгоживущих connections; для SSE это особенно заметно при нескольких вкладках. HTTP/2 мультиплексирует несколько streams поверх одного connection.

HTTP/2 не является обязательным условием работы одной SSE connection, но является обязательной рекомендацией production deployment для этого приложения.

## 51.9. Nginx HTTP/2 configuration

Для актуального Nginx использовать предпочтительно:

```nginx
listen 443 ssl;
http2 on;
```

Старый вариант:

```nginx
listen 443 ssl http2;
```

допустим только в соответствии с фактической версией Nginx.

HTTP/2 требуется между:

```text
Browser
   ↓
Nginx
```

SSE может продолжать проксироваться Nginx → FastAPI обычным HTTP/1.1.

Не требуется включать experimental HTTP/2 implementation в Uvicorn только ради SSE.

## 51.10. Nginx SSE location

Для SSE endpoint Nginx должен:

- не кэшировать response;
- отключить proxy buffering;
- поддерживать long-lived connection.

Рекомендуемая схема:

```nginx
location /api/v1/schedule/stream {
    proxy_pass http://web_backend;

    proxy_http_version 1.1;
    proxy_set_header Connection "";

    proxy_buffering off;
    proxy_cache off;

    proxy_read_timeout 1h;
    proxy_send_timeout 1h;

    add_header Cache-Control "no-store" always;
}
```

Конкретные timeout значения вынести в deployment configuration.

Backend должен возвращать:

```text
Content-Type: text/event-stream
Cache-Control: no-store
X-Accel-Buffering: no
```

## 51.11. SSE heartbeat

SSE stream должен периодически отправлять heartbeat/comment event, чтобы:

- промежуточные proxy не считали connection idle;
- можно было обнаружить оборванное соединение;
- browser мог корректно инициировать reconnect.

Heartbeat не должен содержать пользовательские данные.

## 51.12. Fallback

Если SSE недоступен или постоянно разрывается:

```text
periodic polling
```

с интервалом порядка:

```text
30–60 секунд
```

Polling является fallback, а не primary mechanism.

## 51.13. Browser foreground

При возврате PWA из background в foreground выполнить revalidation текущего экрана независимо от состояния SSE.

Это защищает от:

- sleep;
- network switch;
- cellular/Wi-Fi transition;
- OS background suspension;
- длительного отсутствия activity.

## 51.14. Multi-device

Один пользователь может иметь одновременно:

```text
iPhone → SSE A
iPad   → SSE B
Mac    → SSE C
```

Каждая connection связана со своей web session.

Один user не имеет единого shared SSE connection между устройствами.

---

# 52. HTTP rate limiting

Текущий Telegram `AntiFloodMiddleware` не является HTTP rate limiter.

Он относится к Telegram update pipeline и не должен использоваться как ограничитель FastAPI/SSE requests.

## 52.1. Web rate limiting

Если для Web добавляется отдельный HTTP rate limiter, его правила должны учитывать long-lived SSE connections.

SSE endpoint:

```text
/api/v1/schedule/stream
```

не должен считаться обычным коротким request, который каждую секунду расходует полный token bucket.

Для него применять отдельную политику:

```text
connection limit
+
connection establishment rate limit
```

а не ограничивать длительность самого stream через обычный request-per-second limiter.

## 52.2. Authentication endpoints

Наиболее строгий rate limiting применять к:

```text
/api/v1/auth/exchange
```

и другим коротким auth/mutation requests.

SSE reconnect должен иметь возможность нормально восстанавливаться после временного network failure.

---

# 53. NIKA / parser outage

Сайт должен продолжать показывать последний доступный schedule cache, если parser/NIKA временно недоступен.

Отображать:

```text
Последнее обновление: 09:42
```

и ненавязчивое предупреждение:

```text
Расписание может быть неактуальным.
```

Не показывать пустой экран при временной ошибке parser.

Web использует уже существующую стратегию хранения актуального расписания.

Если schedule cache отсутствует вообще, показывать понятную ошибку вместо пустой страницы.

---

# 54. Health checks

Добавить:

```text
GET /health/live
GET /health/ready
```

`live` проверяет, что application process работает.

`ready` проверяет:

- database availability;
- initialization;
- готовность services.

Health endpoints не должны раскрывать внутренние database details или secrets.

Доступ к health endpoints может быть ограничен внутренней инфраструктурой.

При необходимости добавить отдельный parser/NIKA status.

---

# 55. Timezone

## 55.1. Источник истины

Business date/time определяется исключительно backend и существующим `TimeService`.

Browser timezone не используется для:

- определения текущего дня;
- определения текущего времени;
- smart schedule;
- времени урока;
- времени extra classes;
- notification timing.

## 55.2. Date values

Бизнес-дата передаётся как:

```text
YYYY-MM-DD
```

и рассматривается как `date-only` value.

Например:

```text
2026-09-26
```

не должен превращаться в JavaScript timestamp для определения школьного дня.

## 55.3. HTML date inputs

Для:

```html
<input type="date">
```

использовать строковое значение `YYYY-MM-DD`.

Browser-native date picker допустим.

`input[type=date]` имеет нормализованное value в формате `yyyy-mm-dd`; отображаемый формат может зависеть от locale браузера, но server contract остаётся date-only string.

## 55.4. JavaScript Date

Не использовать JavaScript `Date` для расчётов бизнес-даты/бизнес-времени.

Особенно избегать преобразований:

```text
new Date("YYYY-MM-DD")
toISOString()
getDate()
getUTCDate()
getTimezoneOffset()
```

если их назначение — определить school date/time.

Использовать:

```text
date = "YYYY-MM-DD"
time = "HH:mm"
```

и передавать их backend.

## 55.5. Server rendering

Для основной страницы расписания использовать server-side rendering.

JavaScript отвечает за:

- UI interactions;
- HTMX;
- SSE;
- визуальные эффекты;
- form interactions.

JavaScript не является источником истины для школьного времени.

## 55.6. Client timezone

В будущем допускается отображение текущего client timezone как дополнительной информации.

Это не должно менять school schedule.

Например:

```text
08:30 — по времени школы
```

даже если устройство пользователя находится в другом часовом поясе.

---

# 56. Database migrations

Новые web-specific сущности:

```text
web_login_tokens
web_sessions
```

добавляются через существующий migration mechanism проекта.

Не выполнять schema changes внутри HTTP request.

Перед production migrations выполнять существующий backup mechanism.

Migration должен быть идемпотентным на уровне используемого проекта.

---

# 57. Backup

Web использует ту же SQLite database, что и бот.

Никаких:

```text
web_database.db
```

создавать не нужно.

Существующий `BackupService` продолжает резервировать единую БД.

Web mutations автоматически попадают в backup, поскольку выполняются над той же БД.

Не использовать простое копирование `.db` файла как replacement существующему backup mechanism.

---

# 58. Audit

Web должен использовать существующую audit infrastructure, если она предусмотрена для соответствующей операции.

В audit должны попадать как минимум важные изменения:

```text
extra class create
extra class update
extra class delete
family administration changes
permission changes
profile changes
invites
notification settings
```

Не записывать в audit:

```text
session token
login token
password
CSRF secret
```

Audit должен позволять определить actor, operation и target, но не раскрывать секреты.

---

# 59. Concurrency

Особенно внимательно обработать:

- одновременное изменение extra class через Telegram и Web;
- двойную отправку формы;
- два simultaneous login exchange;
- одновременную обработку family invite;
- simultaneous session requests;
- одновременные SSE events.

Для mutations использовать существующие transaction/locking primitives проекта.

Event `ScheduleChanged` публиковать только после успешного commit.

Если два браузерных запроса одновременно изменяют одну сущность, backend не должен оставлять её в частично изменённом состоянии.

---

# 60. Idempotency

Для чувствительных POST operations предусмотреть защиту от повторного запроса.

Особенно:

```text
extra class creation
family invite creation
```

Двойной tap по кнопке на iPhone не должен создавать две одинаковые записи.

Допускается использовать:

```text
Idempotency-Key
```

или эквивалентный server-side механизм.

---

# 61. Accessibility

Ориентироваться на WCAG 2.2 AA.

Минимально:

- понятные labels;
- keyboard navigation;
- focus states;
- достаточный contrast;
- semantic buttons;
- сообщения об ошибках;
- цвет не является единственным способом передать состояние;
- zoom не блокируется.

---

# 62. Performance

Целевые показатели для домашнего использования:

```text
p95 dashboard < 500 ms
p95 day navigation < 500 ms
p95 week view < 1 s
```

при нормальной работе backend и БД.

SSE connection не должна блокировать event loop или database access.

Не использовать тяжёлую SPA-архитектуру только ради производительности интерфейса.

---

# 63. Public readiness

Сайт должен с самого начала быть архитектурно готов к будущему public launch.

Но public launch не является частью первой deployment phase.

В дальнейшем должно быть возможно перейти:

```text
локальный family-only
        ↓
public domain
        ↓
public users
```

без переписывания:

- `ScheduleService`;
- `ProfileService`;
- `ExtraClassesService`;
- domain model;
- permission model;
- notification business logic.

---

# 64. Public launch — будущий этап

При открытии сайта для всех дополнительно понадобятся:

```text
PostgreSQL
public authentication
HTTPS
rate limiting
monitoring
logging
privacy policy
public onboarding
anti-abuse controls
data isolation
session management
```

Также потребуется production-grade database migration/operations plan при переходе от SQLite.

SQLite на первом семейном deployment менять не требуется.

---

# 65. Auth abstraction

Авторизация должна быть выделена в abstraction layer.

Например:

```python
WebAuthProvider
```

Первая реализация:

```python
TelegramMagicLinkProvider
```

В будущем:

```python
TelegramMiniAppProvider
TelegramLoginProvider
```

Остальные части web-приложения не должны зависеть от конкретного механизма получения identity.

---

# 66. Notification abstraction

Notifications должны быть транспортно-независимыми.

Например:

```python
NotificationChannel
```

Текущая реализация:

```python
TelegramNotificationChannel
```

Будущая:

```python
WebPushNotificationChannel
```

Business event:

```text
ScheduleChanged
```

не должен знать, будет ли он доставлен:

```text
Telegram
Web Push
другой канал
```

---

# 67. Future Web Push

Web Push является TODO и не входит в Phase 1.

Один пользователь в будущем может иметь несколько subscriptions:

```text
Telegram user
      │
      ├── iPhone
      │     └── subscription A
      │
      ├── iPad
      │     └── subscription B
      │
      └── Mac
            └── subscription C
```

Будущая модель:

```text
web_push_subscriptions

id
user_id
endpoint
p256dh
auth
device_name
user_agent
created_at
last_seen_at
revoked_at
```

Связь должна быть:

```text
user_id → many subscriptions
```

а не `user_id → one subscription`.

Будущая реализация должна предусматривать:

- PushSubscription registration;
- VAPID;
- subscription storage;
- несколько устройств;
- revoke;
- dead subscription cleanup;
- per-channel preferences;
- fallback на Telegram;
- iOS Home Screen Web App;
- совместимость с актуальным Declarative Web Push на поддерживаемых версиях iOS/iPadOS.

В зависимости от выбранного способа доставки service worker может использоваться для обработки push; архитектура не должна предполагать его обязательность для каждого iOS сценария.

---

# 68. Testing

Обязательны automated tests.

## 68.1. Authentication

Проверить:

```text
valid token
expired token
invalid token
already used token
double exchange
session expiration
logout
revoked session
```

## 68.2. Authorization

Проверить:

```text
child → own student
child → чужой student = 403

parent → own children
parent → чужая family = 403

observer → allowed actions
observer → administrative action = 403

family admin → permitted actions
non-admin → admin actions = 403
```

## 68.3. Cross-family isolation

Для каждого семейного endpoint проверить:

```text
family A user
    ↓
family B object
    ↓
403
```

Никакой HTML/API response не должен раскрывать данные другой семьи.

## 68.4. Extra Classes

Проверить:

```text
create
edit
delete
bad time
duplicate submit
unauthorized operation
cross-family operation
```

## 68.5. Sessions

Проверить:

```text
restart application
expired cookie
revoked session
role change
family membership change
admin transfer
```

## 68.6. CSRF

Проверить:

```text
mutation without CSRF → 403
invalid CSRF → 403
valid HTMX request → success
valid standard form → success
```

## 68.7. Web schemas

Проверить, что внутренние DTO fields, не входящие в `Web*` schemas, не появляются в JSON responses.

---

# 69. End-to-end testing

Использовать Playwright или аналог.

Минимальный сценарий:

```text
открыть сайт
    ↓
login через Telegram magic link
    ↓
dashboard
    ↓
переключить ребёнка
    ↓
открыть день
    ↓
открыть неделю
    ↓
найти класс
    ↓
открыть учителя
    ↓
открыть кабинет
    ↓
просмотреть свободные кабинеты
    ↓
создать extra class
    ↓
изменить extra class
    ↓
удалить extra class
    ↓
открыть Settings
    ↓
просмотреть sessions
    ↓
выйти
```

## 69.1. Multi-device E2E

Проверить:

```text
один user
→ login на iPhone

тот же user
→ login на iPad

обе sessions одновременно работают
```

Проверить:

```text
iPhone logout
→ iPad продолжает работать

iPad logout
→ iPhone продолжает работать

logout all
→ обе sessions становятся недействительными
```

Проверить также:

```text
role/admin change в Telegram
→ существующая web session получает актуальные permissions

family membership change
→ существующая session использует новое состояние

student profile change
→ оба устройства видят одинаковый актуальный результат
```

## 69.2. Live update testing

Обязательный E2E сценарий:

```text
iPhone открывает «Сегодня»
        ↓
второй клиент/бот изменяет расписание
        ↓
backend сохраняет изменение
        ↓
ScheduleChanged
        ↓
SSE event
        ↓
HTMX/fetch
        ↓
iPhone автоматически обновляет UI
```

Также проверить:

```text
SSE disconnect
→ automatic reconnect
→ current screen revalidation

SSE unavailable
→ polling fallback

browser background/foreground
→ schedule revalidation

Nginx restart
→ SSE reconnect
→ schedule revalidation

два устройства одного user
→ оба получают обновление

два разных user/family
→ данные не смешиваются
```

## 69.3. SSE revocation tests

Проверить:

```text
logout
→ current SSE closed

logout all
→ all corresponding SSE connections closed

session revoke
→ reconnect returns 401

family access revoke
→ connection cannot receive private data
```

## 69.4. PWA security tests

Проверить:

```text
User A opens schedule
↓
logout
↓
User B login
↓
User B must not see cached schedule of User A
```

Также проверить:

```text
logout
→ personal client-side data cleared

session expiration
→ personal cached UI not exposed

cross-user navigation
→ no stale personal content

new account login
→ previous account snapshot unavailable
```

Если в будущем будет реализован offline personal schedule, эта функция должна пройти отдельный security review.

---

# 70. Definition of Done

Версия считается готовой, когда:

### Архитектура

- Web использует существующие services.
- Нет duplicate business logic.
- Нет web-specific SQLite database.
- SQLite не монтируется по сети.
- FastAPI работает в одном процессе с ботом на Phase 1.
- Multi-worker deployment не используется.
- Общая БД используется ботом и Web напрямую через существующий service/repository layer.

### Authentication

- Telegram login работает.
- Login token одноразовый.
- Login token имеет TTL.
- Token хранится только в hashed form.
- Session opaque.
- Роль/admin не находятся в cookie.
- Logout работает.
- Session revoke работает.
- Один user может иметь несколько sessions.

### Authorization

- Cross-family access невозможен.
- Child не может получить чужого student.
- Parent получает только доступных детей.
- Administrative permissions проверяются backend.
- Изменение family-admin status отражается на существующей session.

### CSRF

- Все cookie-authenticated mutations защищены CSRF.
- Все HTMX mutations автоматически получают CSRF token.
- Mutation без корректного CSRF получает `403`.

### Functionality

- Сегодня.
- Любой день.
- Неделя.
- Классы.
- Группы.
- Учителя.
- Кабинеты.
- Свободные кабинеты.
- Семья.
- Student profiles.
- Дополнительные занятия.
- Settings.
- Active sessions.
- Feature parity matrix по текущему Telegram-интерфейсу.

### Live updates

- SSE работает.
- SSE не передаёт персональные данные.
- Reconnect работает.
- Reconnect имеет backoff через актуальный `htmx-ext-sse`.
- После reconnect выполняется revalidation.
- Polling fallback работает.
- Logout/revoke корректно закрывает или инвалидирует соответствующие streams.
- Два устройства одного пользователя могут получать live updates одновременно.

### UX

- Mobile-first.
- iPhone Safari.
- iPad Safari.
- Add to Home Screen.
- PWA manifest.
- Service Worker.
- Safe areas.
- Desktop layout.
- Нет horizontal overflow.
- Zoom не заблокирован.

### Notifications

- Telegram notifications продолжают работать.
- Web не ломает существующий notification pipeline.
- Web Push остаётся TODO.
- Архитектура позволяет добавить Web Push позже.

### Security

- CSP включён.
- HTMX/SSE dependencies version-pinned.
- В production предпочтительно локальные JS dependencies.
- Session/login/CSRF secrets не попадают в logs.
- Host validation работает.
- Trusted proxy headers настроены.
- HTTP auth endpoints имеют rate limiting.

### Operations

- Backup работает.
- Health endpoints работают.
- Graceful shutdown работает.
- NIKA outage handled gracefully.
- Error pages корректны.
- Migration mechanism работает.
- Request logging не раскрывает secrets.

### Testing

- Unit/integration tests проходят.
- Authentication tests проходят.
- Authorization/cross-family tests проходят.
- CSRF tests проходят.
- Multi-device tests проходят.
- SSE tests проходят.
- PWA security tests проходят.
- E2E сценарий проходит.

---

# 71. Этапы реализации

## Phase 1 — Backend foundation

```text
FastAPI integration
shared services
shared DB
web login tokens
web sessions
Telegram magic link
authorization
CSRF
rate limiting
proxy/header security
health endpoints
application event manager
SSE connection manager
```

## Phase 2 — Основной интерфейс

```text
Сегодня
День
Неделя
```

## Phase 3 — School

```text
Классы
Группы
Учителя
Кабинеты
Поиск
Свободные кабинеты
```

## Phase 4 — Family

```text
Семья
Student profiles
переключение детей
permissions
family administration
invitations
```

## Phase 5 — Extra Classes

```text
list
create
edit
delete
conflict warnings
idempotent mutations
```

## Phase 6 — PWA

```text
manifest
icons
service worker
offline shell
iOS Home Screen UX
```

## Phase 7 — Live updates

```text
application events
SSE
HTMX integration
reconnect
foreground revalidation
polling fallback
session revoke handling
```

## Phase 8 — Stabilization

```text
security
tests
e2e
performance
backup
logging
deployment
feature parity audit
```

## Future / TODO

```text
Web Push
```

## Future Public

```text
PostgreSQL
public auth
public onboarding
monitoring
privacy
abuse protection
```

---

# 72. Главный архитектурный критерий

Финальная система должна представлять собой:

```text
                    School Schedule Backend
                              │
             ┌────────────────┴────────────────┐
             │                                 │
        Telegram UI                         Web UI
             │                                 │
             └────────────────┬────────────────┘
                              │
                         Services
                              │
                         Repository
                              │
                            SQLite
```

Telegram и Web являются двумя интерфейсами одной системы.

Telegram отвечает за привычный messaging/notification experience.

Web отвечает за удобный визуальный интерфейс, полноценный просмотр и управление данными.

SSE отвечает за синхронизацию **активно открытого Web UI**.

Web Push является запланированным дополнительным каналом доставки уведомлений и не входит в первую версию.

Один Telegram user может иметь:

```text
N web sessions
N devices
```

а в будущем:

```text
N Web Push subscriptions
```

Authentication identity, permissions, family membership и student access не дублируются в Web frontend.

Главная цель первой production-версии:

> **Пользователь должен иметь возможность практически полностью пользоваться School Schedule через сайт так же, как через Telegram-бота, сохраняя тот же профиль, ту же семью, те же права и те же данные.**
