# Техническое задание на разработку бота расписания v2 для школы

## 1. Назначение и общая концепция

Бот предназначен для предоставления расписания занятий конкретной школы ученикам и их родителям через мессенджер (Telegram), с перспективой поддержки учителей и других ролей.
Основная концепция версии v2 — модульная архитектура, в которой ядро работает с полным расписанием школы (данные NIKA), а бот предоставляет разные представления расписания в зависимости от роли и профиля пользователя.[^1][^2]

Версия v2 строится на следующих принципах:

- **Отказ от хардкода классов**: никакие классы (например, `"016"` для 6А) не зашиваются в коде; вся информация берётся из дампа NIKA (`CLASSES`, `CLASS_SCHEDULE`, `TEACH_SCHEDULE`).[file:27][file:79]
- **Модульная архитектура**: отдельные слои для парсинга NIKA, доменной модели школы, репозитория расписания, сервисов (ScheduleServiceV2, ProfileService, NotificationService) и слоя бота с обработчиками команд.[file:79]
- **Семейная модель и ролевой доступ**: учёт ролей ребёнка, родителя, учителя, наблюдателя и администратора, привязка пользователей к семьям по `family_code` и управление профилями.[file:79]
- **Гибкая система уведомлений**: индивидуальные настройки предурочных уведомлений и окна по изменениям расписания, с защитой от спама и дублей.[file:79]
- **Отказоустойчивость**: денормализованное расписание в SQLite (aiosqlite), краткосрочный сырой кэш NIKA, работа бота из локального кэша при недоступности сайта школы.[file:79]

Бот создаётся как рефакторинг существующего проекта: UX и основные команды сохраняются, но весь парсинг и доступ к данным переводятся на новый движок JS/NIKA и модульную архитектуру.[file:27][file:79]


## 2. Источник данных и формат расписания

### 2.1. Источник данных

- Веб‑сайт школы с расписанием: `https://lyceum.nstu.ru/rasp/schedule.html` (пример для текущей школы).[^2]
- Фактические данные расписания хранятся в JS‑файле вида `nika_data_YYYYMMDD_HHMMSS.js`, подключаемом через `<script src="nika_data_*.js">` на странице расписания.[^1][^2]

### 2.2. Формат NIKA

JS‑файл содержит глобальную переменную:

```js
var NIKA = { /* JSON-объект */ }
```

Этот объект полностью совместим с JSON и содержит как минимум:
- справочники: `CLASSES`, `TEACHERS`, `ROOMS`, `SUBJECTS`, `CLASSGROUPS`, `LESSON_TIMES`, `PERIODS`;
- основное расписание по классам: `CLASS_SCHEDULE`;
- расписание по учителям: `TEACH_SCHEDULE`;
- замены по классам: `CLASS_EXCHANGE`;
- замены по учителям: `TEACH_EXCHANGE`;
- дополнительные параметры интерфейса и настроек.[^1]

Узел `LESSON_TIMES` хранит тайминги уроков в виде массивов из двух строк:

```json
"LESSON_TIMES": {
  "1": ["8:15","9:00"],
  "2": ["9:10","9:55"],
  ...
}
```

Время начала и окончания урока должно извлекаться по индексам:

- `start_time = LESSON_TIMES[str(lesson_num)][0]`
- `end_time   = LESSON_TIMES[str(lesson_num)][1]`.[file:3]

### 2.3. Структура CLASS_SCHEDULE (упрощённо)

```json
CLASS_SCHEDULE: {
  "period_id": {
    "class_id": {
      "daylesson_key": {
        "s": ["subject_id", ...],
        "t": ["teacher_id", ...],
        "r": ["room_id", ...],
        "g": ["group_id", ...]
      }
    }
  }
}
```

- `period_id` — идентификатор учебного периода (связан с `PERIODS`).[^1]
- `class_id` — идентификатор класса (ключ из `CLASSES`).[^1]
- `daylesson_key` — строка вида `"107"`, где первая цифра — день недели (1–6/7), оставшиеся — номер урока.[^2][^1]
- `s` — массив идентификаторов предметов.
- `t` — массив идентификаторов учителей.
- `r` — массив идентификаторов кабинетов.
- `g` — массив идентификаторов групп; если отсутствует, урок относится ко всему классу.[^1]

### 2.4. TEACH_SCHEDULE (расписание учителей)

Для вкладки «Учителя» используется зеркальная структура `TEACH_SCHEDULE`:

```json
TEACH_SCHEDULE: {
  "period_id": {
    "teacher_id": {
      "daylesson_key": {
        "s": ["subject_id", ...],
        "c": ["class_id", ...],
        "g": ["group_id", ...],
        "r": ["room_id", ...]
      }
    }
  }
}
```

- `period_id` — идентификатор учебного периода (связан с `PERIODS`).
- `teacher_id` — идентификатор учителя (ключ из `TEACHERS`).
- `daylesson_key` — строка вида `"107"` (день недели + номер урока).
- `s` — массив идентификаторов предметов.
- `c` — массив идентификаторов классов.
- `g` — массив идентификаторов групп.
- `r` — массив идентификаторов кабинетов.

Парсер обязан использовать `TEACH_SCHEDULE` и `TEACH_EXCHANGE` как первичный источник расписания учителей, а не вычислять его через обход `CLASS_SCHEDULE`.[file:3]

### 2.6. Особенности данных NIKA

- В массивах `s`, `t`, `r` школьная система часто выгружает пустые строки `""` вместо `null`, например `"s":["012",""]`, `"t":["006",""]`, `"r":["023",""]`. Нормализатор обязан интерпретировать пустые строки как отсутствие значения (`None`) и никогда не использовать их для поиска в `SUBJECTS`, `TEACHERS` или `ROOMS`.[file:3]
- Узел `CLASSGROUPS` содержит динамический набор групп (например, «Группа 1», «Девочки», «Мальчики»). Значения `g[i]` всегда мапятся через словарь `CLASSGROUPS`; отсутствие массива `g` означает урок для всего класса (`group_id = None`, `group_name = "Весь класс"`).[file:3]
- Узел `CLASS_COURSES` может отсутствовать. В этом случае курс (год обучения) определяется из строки имени класса (например, «5а», «10-3») с помощью регулярного выражения, извлекающего ведущие цифры.[file:3]

## 3. Архитектура системы v2

### 3.1. Логические слои

Система разделяется на следующие слои:

1. **Data Source (NIKA/JS)** — загрузка и разбор JS‑файла расписания в объект `NIKA`.
2. **Domain Model** — нормализованная модель школы: классы, учителя, кабинеты, уроки, периоды.
3. **Repository/Cache** — слой доступа к данным расписания, кеширование и актуализация.
4. **Services** — прикладные сервисы:
   - `ScheduleService v2` — логика выборки расписания в разных разрезах (по ребёнку, классу, учителю, кабинету);
   - `ProfileService` — управление профилями пользователей (родители, дети, учителя);
   - `NotificationService` — напоминания о занятиях.
5. **Bot Layer** — обработчики команд/диалогов мессенджера, клавиатуры, состояния.

В рамках семейной модели:
- создатель семьи (parent) имеет права удалять участников семьи (детей и других взрослых) и управлять их ролями;
- роль `observer` (наблюдатель) имеет доступ только на чтение расписания (без изменений профиля и настроек).[file:79]

### 3.2. Структура пакетов (рекомендуемая)

```text
core/
  nika/           # загрузка и парсинг NIKA
  models/        # доменные модели (dataclasses / pydantic)
  repository/    # ScheduleRepository, кеш и выборки
  profiles/      # доменная модель пользователей/семей
services/
  schedule_v2.py # ScheduleService v2
  profiles.py    # ProfileService
  notifications.py # NotificationService
bot/
  handlers/      # обработчики команд Telegram
  keyboards/     # клавиатуры и меню
  main.py        # точка входа бота
```

## 4. Доменные модели и схемы БД

### 4.1. Модели расписания (Python dataclasses/pydantic)

#### Class

```python
class Class(BaseModel):
    id: str          # NIKA class_id ("013")
    name: str        # человекочитаемое имя ("5а")
    course: int      # параллель/год обучения (1..11)
```

Источник полей:
- `id`, `name` — из `CLASSES`;
- `course` — из `CLASS_COURSES`, если узел присутствует. При отсутствии `CLASS_COURSES` курс вычисляется из `name` регулярным выражением (извлечение ведущего числа до первой буквы/дефиса, например «5а» → 5, «10-3» → 10).[file:3]

#### Teacher

```python
class Teacher(BaseModel):
    id: str          # NIKA teacher_id
    full_name: str   # "Фамилия И.О."
    short_name: str  # сокращённое имя для компактного вывода
```

Источник: `TEACHERS` + сокращение по правилу (фамилия + инициалы).[^2][^1]

#### Room

```python
class Room(BaseModel):
    id: str          # NIKA room_id
    name: str        # "201", "спортзал", "1к 504" и т.п.
    location: str | None  # необязательное поле (корпус/особые пометки)
```

Источник: `ROOMS`.[^1]

#### Subject

```python
class Subject(BaseModel):
    id: str
    name: str
```

Источник: `SUBJECTS`.[^1]

#### Period

```python
class Period(BaseModel):
    id: str
    date_start: datetime.date
    date_end: datetime.date
    name: str
```

Источник: `PERIODS[period_id]` (`b`, `e`, `name`).[^1]

#### LessonInstance

Единичное занятие в конкретный день для конкретной группы/класса:

```python
class LessonInstance(BaseModel):
    id: str                    # уникальный идентификатор (period_id + class_id + date + lesson_num + group_id)
    period_id: str
    class_id: str
    date: datetime.date
    weekday: int               # 1..7
    lesson_num: int            # номер урока
    start_time: str            # "HH:MM"
    end_time: str              # "HH:MM"

    subject_id: str | None
    subject_name: str

    teacher_id: str | None
    teacher_name: str | None

    room_id: str | None
    room_name: str | None

    group_id: str | None       # идентификатор группы или None для всего класса
    group_name: str            # из CLASSGROUPS или "Весь класс"

    is_exchange: bool = False  # урок пришёл из CLASS_EXCHANGE/TEACH_EXCHANGE
    is_cancelled: bool = False # урок отменён ("F" или пустой предмет)

    original_subject_name: str | None = None
    original_teacher_name: str | None = None
    original_room_name: str | None = None

    groups_raw: list[str] | None = None
    subjects_raw: list[str] | None = None
    rooms_raw: list[str] | None = None
```

Комментарий:

```markdown
- `start_time`, `end_time` берутся из `LESSON_TIMES[lesson_num]`.[file:3][file:27]
- `subject_id`, `teacher_id`, `room_id` могут быть `None`. Пустые строки в массивах `s`, `t`, `r` при нормализации всегда заменяются на `None` и не используются для поиска в справочниках.[file:3]
- `group_id`, `group_name` — вычисляются через `CLASSGROUPS` по соответствующему элементу массива `g`. Если массив `g` отсутствует, создаётся один `LessonInstance` с `group_id = None`, `group_name = "Весь класс"`. Если `g` содержит несколько значений, слот разворачивается в несколько `LessonInstance` — по одному на группу.[file:3]
- `is_exchange` и `is_cancelled` определяются по данным `CLASS_EXCHANGE`/`TEACH_EXCHANGE` и флагу `"F"`/пустому предмету. Поля `original_*` позволяют при необходимости отображать пользователю "Было → Стало" для замен.
```

### 4.2. Схема БД (SQLite / aiosqlite)

БД уже содержит таблицы `families`, `users`, `extra_classes`, `change_history` и кеш расписания (по текущей реализации).[^1]
Ниже — рекомендуемое расширение/уточнение.

#### Таблица `users`

```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,   -- Telegram user_id
    role TEXT NOT NULL,         -- 'child', 'parent', 'teacher', 'observer'
    family_id INTEGER,          -- для детей/родителей
    class_id TEXT,              -- NIKA class_id для ребёнка/ученика
    group_id TEXT,              -- идентификатор группы ('0', '1', '2'...)
    teacher_id TEXT,            -- NIKA teacher_id для учителя
    is_admin INTEGER NOT NULL DEFAULT 0,
    last_active_at TEXT,

    child_notifications_locked INTEGER NOT NULL DEFAULT 0, -- 0/1: если 1, ребёнок не может менять свои уведомления

    pre_lesson_offset_minutes INTEGER NOT NULL DEFAULT 15, -- за сколько минут до урока слать предурочное уведомление
    changes_window_days       INTEGER NOT NULL DEFAULT 3,  -- окно уведомлений об изменениях расписания в днях

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

- `role` определяет поведение бота (какие команды доступны).
- `class_id` и `group_id` — для детей/учеников.
- `teacher_id` — для учителя, чтобы получать его расписание.

#### Таблица `families`

```sql
CREATE TABLE IF NOT EXISTS families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_code TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);
```

- `family_code` используется для привязки родителя и детей (уже реализовано).[^1]

#### Таблица `extra_classes`

Доп. занятия уже реализованы, можно сохранить текущую структуру:

```sql
CREATE TABLE IF NOT EXISTS extra_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,  -- 0..6
    time_start TEXT NOT NULL,      -- "HH:MM"
    time_end TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    reminder_minutes INTEGER DEFAULT 30,
    FOREIGN KEY (family_id) REFERENCES families(id)
);
```

#### Таблица `schedule_cache`

Кеш расписания должен быть денормализованным для эффективных выборок по классам, учителям и кабинетам:

```sql
CREATE TABLE IF NOT EXISTS schedule_cache (
    id TEXT PRIMARY KEY,         -- LessonInstance.id (period_id + class_id + date + lesson_num + group_id/"ALL")
    date TEXT NOT NULL,          -- "YYYY-MM-DD"
    period_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    lesson_num INTEGER NOT NULL,
    group_id TEXT NOT NULL,      -- всегда строка; для всего класса использовать маркер "ALL"
    subject_id TEXT,
    teacher_id TEXT,
    room_id TEXT,
    is_exchange INTEGER NOT NULL,       -- 0/1
    is_cancelled INTEGER NOT NULL,      -- 0/1
    is_notified INTEGER DEFAULT 0,      -- 0/1 (уведомление о начале урока отправлено)
    is_change_notified INTEGER DEFAULT 0, -- 0/1 (уведомление об изменении отправлено)
    created_at TEXT NOT NULL
);
```
Для обеспечения устойчивого UPSERT‑поведения в SQLite рекомендуется:

- использовать текстовый `id` как PRIMARY KEY, формируемый на уровне `LessonInstance` как конкатенация `(period_id + class_id + date + lesson_num + group_id)`;
- при формировании `id` использовать строку `"ALL"` вместо `None`/`NULL` для уроков на весь класс, и аналогично задавать `group_id = "ALL"` в таблице `schedule_cache`.

В этом случае команда `INSERT OR REPLACE` по PRIMARY KEY будет надёжно обновлять существующую строку, а не вставлять дубли, даже для уроков без явной группы.[web:69][web:71]

Рекомендуемые индексы:

```sql
CREATE INDEX idx_schedule_date_class   ON schedule_cache(date, class_id);
CREATE INDEX idx_schedule_date_teacher ON schedule_cache(date, teacher_id);
CREATE INDEX idx_schedule_date_room    ON schedule_cache(date, room_id);
```

- Каждая строка соответствует одному `LessonInstance`.
- Методы `get_lessons_for_class`, `get_lessons_for_teacher` и `get_lessons_for_room` работают через SQL‑фильтрацию по соответствующим колонкам, без десериализации больших JSON‑структур.[file:3]

Обеспечение уникальности и UPSERT‑поведения:

- Уникальность слотов расписания достигается за счёт текстового `PRIMARY KEY id`, который формируется из `(period_id + class_id + date + lesson_num + group_id/"ALL")`.
- При записи уроков в `schedule_cache` следует использовать `INSERT OR REPLACE` по этому PRIMARY KEY `id`, чтобы обновлять существующие строки без накопления дублей при периодическом обновлении расписания.[file:79][web:69][web:71]

#### Таблица `change_history`

Уже есть таблица для истории изменений; её можно использовать для логирования замен/отмен.

```sql
CREATE TABLE IF NOT EXISTS change_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    lesson_num INTEGER NOT NULL,
    change_type TEXT NOT NULL,   -- 'exchange', 'cancel', 'other'
    details TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

#### Таблица `raw_nika_cache`

```sql
CREATE TABLE IF NOT EXISTS raw_nika_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    export_date TEXT,   -- дата экспорта из NIKA (если есть в объекте)
    export_time TEXT,   -- время экспорта (если есть)
    fetched_at TEXT NOT NULL,  -- момент получения слепка (UTC или TZ из Config)
    content TEXT NOT NULL      -- полный текст nika_data_*.js
);
```

## 5. Модуль парсинга NIKA (core/nika)

### 5.1. Интерфейс `ScheduleFetcher`

```python
class ScheduleFetcher:
    BASE_URL = "https://lyceum.nstu.ru/rasp/"

    def __init__(self, proxy_url: str | None = None):
        self.proxy_url = proxy_url

    def fetch_schedule_page(self) -> str:
        """Загрузить HTML-страницу расписания."""

    def extract_nika_script_src(self, html: str) -> str:
        """Извлечь путь к JS-файлу с NIKA (nika_data_*.js)."""

    def fetch_nika_js(self, src: str) -> str:
        """Загрузить JS-файл по относительному пути src."""

    def parse_nika(self, content: str) -> dict:
        """Извлечь объект NIKA из JS-текста и преобразовать его в dict."""

    def load_nika(self) -> dict:
        """Комбинированный метод: загрузить HTML, найти JS, сохранить сырой JS и вернуть NIKA."""
```

Требования:

- Использовать заголовок `User-Agent` для минимизации блокировок.[file:27]
- Поддерживать загрузку через HTTP/HTTPS‑прокси (`proxy_url` из `Config`), если бот развёрнут в окружении с возможными ограничениями доступа (например, сервер в РФ). В других окружениях прокси опционален.
- При необходимости отключать проверку HTTPS‑сертификатов (`verify=False`), логируя предупреждение.
- При парсинге:
  - найти фрагмент `var NIKA` в тексте;
  - определить начало `{` и соответствующую закрывающую `}` с учётом вложенности;
  - извлечь тело объекта без префикса `var NIKA=` и суффикса `;`;
  - попытаться десериализовать через `json.loads`;
  - при ошибках `ValueError` логировать сырой фрагмент и, по согласованию, использовать специализированный JS→JSON‑парсер как fallback.
- Перед передачей данных в `NikaNormalizer` сохранять полный текст `nika_data_*.js` в таблицу `raw_nika_cache`.[file:3][file:27]


### 5.2. Нормализатор `NikaNormalizer`

```python
class NikaNormalizer:
    def __init__(self, nika: dict):
        self.nika = nika

    def build_metadata(self) -> SchoolMetadata:
        """Построить модели Class, Teacher, Room, Subject, Period и др."""

    def build_class_lessons(self) -> list[LessonInstance]:
        """Развернуть CLASS_SCHEDULE и CLASS_EXCHANGE в список LessonInstance по классам."""

    def build_teacher_lessons(self) -> list[LessonInstance]:
        """Развернуть TEACH_SCHEDULE и TEACH_EXCHANGE в список LessonInstance по учителям."""
```
При формировании `id` для урока на весь класс нормализатор должен использовать маркер `"ALL"` вместо `None` для части идентификатора, чтобы ключ был детерминированным и не содержал `NULL`.[file:63][web:69]

Основные шаги для классов:

- Пройти по `CLASS_SCHEDULE[period_id][class_id][daylesson_key]`.
- Декодировать день недели и номер урока из `daylesson_key`.
- Определить дату по `PERIODS[period_id]` и смещению дня.
- Проверить наличие замен в `CLASS_EXCHANGE[class_id][date_str][lesson_num]`.
  - Если замена есть, массивы `s`, `t`, `r`, `g` из замены полностью перекрывают базовые значения; при `s == "F"` или пустом `s` урок помечается как отменённый (`is_cancelled = True`).[file:3][file:27]
- Для каждого слота:
  - очистить пустые строки в `s/t/r` (заменить на `None`);
  - если `g` отсутствует — создать один `LessonInstance` с `group_id = None`, `group_name = "Весь класс"`;
  - если `g` есть — создать по одному `LessonInstance` на каждый `g[i]`, заполняя `group_id/group_name`.

Для учителей аналогичный алгоритм применяется к `TEACH_SCHEDULE[period_id][teacher_id][daylesson_key]` и `TEACH_EXCHANGE`, при этом классы берутся из массива `c`, а остальные поля — из соответствующих массивов слота.[file:3][file:2]

- `start_time`, `end_time` берутся из `LESSON_TIMES[str(lesson_num)][0]` и `[1]` соответственно, так как в дампе тайминги уроков представлены массивами из двух строк (начало и конец).[file:3]

- При обработке записи из `CLASS_EXCHANGE` необходимо учитывать, что словарь замены может быть урезанным (например, `{"s": "F"}` без `t`, `r`, `g`). Нормализатор должен использовать безопасный доступ:

  ```python
  s_value = exchange_slot.get("s")
  t_list = exchange_slot.get("t", [])
  r_list = exchange_slot.get("r", [])
  g_list = exchange_slot.get("g", [])
  ```

  и не пытаться извлекать учителя, кабинет или группы для отменённого урока, если этих данных нет. Это предотвращает падения `KeyError` при обработке отмен.[file:27][file:3]

 - Для отменённых уроков (`s == "F"` или пустой предмет) `LessonInstance` создаётся с `subject_id = None`, `subject_name` = "ОТМЕНА", а массивы `t`, `r`, `g` считаются пустыми независимо от содержимого базовой записи.[file:27]

## 6. ScheduleRepository и ScheduleService v2

### 6.1. ScheduleRepository

```python
class ScheduleRepository:
    def __init__(self, db: Database, fetcher: ScheduleFetcher):
        self.db = db
        self.fetcher = fetcher
        self.metadata: SchoolMetadata | None = None

    async def refresh_from_remote(self) -> None:
        """Загрузить NIKA с сайта, сохранить сырой JS и обновить кеш в БД."""

    def load_from_cache(self) -> None:
        """Загрузить расписание из БД, если сайт недоступен."""

    def get_lessons_for_class(self, class_id: str, date: datetime.date) -> list[LessonInstance]:
        """Получить уроки для класса по конкретной дате."""

    def get_lessons_for_teacher(self, teacher_id: str, date: datetime.date) -> list[LessonInstance]:
        """Получить уроки преподавателя по дате."""

    def get_lessons_for_room(self, room_id: str, date: datetime.date) -> list[LessonInstance]:
        """Получить занятия в кабинете по дате."""


    async def get_changes_summary(self, from_date: datetime.date, to_date: datetime.date) -> list[ChangeEntry]:
        """Вернуть краткую сводку изменений (замены, отмены) в заданном диапазоне дат по данным schedule_cache и/или change_history."""

```

Описание методов:

- `refresh_from_remote`:
  - вызывает `fetcher.load_nika()`;
  - передаёт результат в `NikaNormalizer`;
  - сохраняет полученные `LessonInstance` построчно в `schedule_cache`;
  - обновляет справочники (`metadata`).
- `load_from_cache`:
  - читает `schedule_cache` и восстанавливает `LessonInstance` при недоступности сайта.

При записи в `schedule_cache` `refresh_from_remote` должен использовать либо UPSERT (с уникальным индексом по `(date, class_id, lesson_num, group_id, teacher_id)`), либо предварительное удаление старых записей за обновляемый период, чтобы избежать дублирования одних и тех же уроков при многократных обновлениях.[file:63]
При записи уроков в `schedule_cache` `refresh_from_remote` должен использовать `INSERT OR REPLACE` по PRIMARY KEY `id`, чтобы обновлять строки без накопления дублей при периодическом обновлении расписания.[file:63]

При обработке замен из `CLASS_EXCHANGE` и `TEACH_EXCHANGE` `refresh_from_remote` (или фоновой watcher) должен выполнять UPSERT в `schedule_cache`, обновляя поля `is_exchange`/`is_cancelled` и оставляя/устанавливая `is_change_notified = 0` для новых или изменённых уроков. Мгновенная рассылка уведомлений об изменениях на этом этапе не выполняется — за неё отвечает отдельный метод сервиса уведомлений.[file:3]

Перед вставкой нового слепка в `raw_nika_cache` метод `refresh_from_remote` обязан выполнять очистку старых дампов:

```sql
DELETE FROM raw_nika_cache
WHERE fetched_at < datetime('now', '-N days');
```

где `N` задаётся в конфиге (по умолчанию 7). Это предотвращает неконтролируемый рост объёма базы при регулярном фоновом мониторинге расписания.[file:63]

Фоновая задача (например, `UserCleanupJob`) должна:

- обновлять `last_active_at` при каждой команде пользователя;
- раз в сутки находить пользователей, неактивных более N дней;
- для таких пользователей:
  - отключать уведомления (флаг в профиле);
  - при необходимости выполнять дополнительную очистку связанных данных (с учетом политики школы).
Точное значение N и политика удаления/деактивации настраиваются через конфиг.[web:90]

### 6.2. ScheduleService v2

```python
class ScheduleServiceV2:
    def __init__(self, repo: ScheduleRepository, db: Database):
        self.repo = repo
        self.db = db

    async def get_daily_schedule_for_child(self, child_user_id: int, date: datetime.date) -> dict:
        """Расписание на день для конкретного ребёнка (учёт класса и группы)."""

    async def get_week_schedule_for_child(self, child_user_id: int, week_start: datetime.date) -> dict:
        """Расписание на неделю для ребёнка."""

    async def get_daily_schedule_for_class(self, class_id: str, date: datetime.date) -> dict:
        """Расписание класса на день."""

    async def get_daily_schedule_for_teacher(self, teacher_user_id: int, date: datetime.date) -> dict:
        """Расписание учителя (по его teacher_id) на день."""

    async def get_room_occupancy(self, room_id: str, date: datetime.date) -> dict:
        """Занятость кабинета на день."""
```

Примеры логики:
- `get_daily_schedule_for_child`:
  - найти запись пользователя по `user_id`;
  - получить `class_id`, `group_id`;
  - через `repo.get_lessons_for_class` получить все уроки класса на дату;
  - отфильтровать уроки по `group_id`: брать либо `group_id` совпадает, либо `group_id` у урока `None` (весь класс);
  - добавить доп. занятия из `extra_classes`.

## 7. ProfileService и NotificationService

### 7.1. ProfileService

```python
class ProfileService:
    def __init__(self, db: Database):
        self.db = db

    async def get_user_profile(self, user_id: int) -> dict:
        """Получить профиль пользователя (роль, класс, группа, семейные связи)."""

    async def link_child_to_parent(self, parent_user_id: int, family_code: str) -> None:
        """Привязать родителя к семье по коду."""

    async def set_child_class_and_group(self, child_user_id: int, class_id: str, group_id: str | None) -> None:
        """Установить класс и группу ребёнка."""

    async def set_teacher_profile(self, teacher_user_id: int, teacher_id: str) -> None:
        """Привязать пользователя к учителю в NIKA."""
    async def remove_family_member(self, family_id: int, user_id: int) -> None:
        """Удалить участника семьи (по инициативе создателя семьи)."""

    async def set_child_notifications_lock(self, parent_user_id: int, child_user_id: int, locked: bool) -> None:
        """Разрешить или запретить ребёнку менять свои настройки уведомлений."""

remove_family_member доступен только создателю семьи или администратору.
```

### 7.2. NotificationService

```python
class NotificationService:
    def __init__(self, schedule_service: ScheduleServiceV2, db: Database, config: Config):
        self.schedule_service = schedule_service
        self.db = db
        self.config = config

    async def send_morning_reminders(self, date: datetime.date) -> None:
        """Утренние уведомления по расписанию на день для всех детей."""

    async def send_upcoming_changes(self, datetime_now: datetime.datetime) -> None:
        """Рассылка уведомлений об изменениях, попадающих в N-дневное окно."""
        
    async def send_pre_lesson_reminders(self, datetime_now: datetime.datetime) -> None:
        """Напоминания за N минут до урока (по настройке)."""
```
Если для ребёнка `child_notifications_locked = 1`, NotificationService при чтении настроек должен использовать параметры из профиля родителя (или семейные настройки) и игнорировать попытки изменения со стороны ребёнка.

Основные требования:
- Напоминания не должны отправляться по отменённым урокам (`is_cancelled = True`).
- Для детей учитывать группу (`group_id`) и доп. занятия.

При реализации `send_pre_lesson_reminders` нужно избегать строгого сравнения разницы времени:

- `apscheduler` с триггером `'interval'` может запускать задачу с небольшой задержкой (джиттер по секундам) относительно идеального момента.[web:73][web:75]
- Вместо проверки `start_time - now == N_минут` следует использовать временное окно:

  - вычислить `delta = start_time - now` в минутах;
  - отправлять уведомление, если `0 < delta <= N_минут` и `is_notified == 0` для соответствующей строки.

- После успешной отправки уведомления поле `is_notified` в `schedule_cache` должно быть выставлено в `1`, чтобы избежать повторной отправки при следующем запуске (каждые 5 минут).

Таким образом, даже при небольшом джиттере выполнения планировщика предурочные уведомления будут надёжно доставляться без дублей.[file:63][web:73]

Для уведомлений об изменениях расписания (замены, отмены) требуется отдельная логика с окном дат:

- В `NotificationService` реализуется метод `send_upcoming_changes(datetime_now: datetime.datetime)`, который запускается планировщиком по интервалу (например, каждые 45 минут).

- Метод формирует SQL‑запрос к `schedule_cache`:
  - выбирает все строки, где `is_exchange = 1 OR is_cancelled = 1` и `is_change_notified = 0`;
  - отфильтровывает только те уроки, дата которых попадает в окно между двумя датами, вычисленными на стороне Python с учётом таймзоны (например, `ZoneInfo("Asia/Novosibirsk")`):

    ```sql
    WHERE date BETWEEN ? AND ?
    ```

    где параметры — это `start_date = datetime_now.date()` и `end_date = (datetime_now + timedelta(days=N)).date()`, а `N` задаётся в конфиге или настройках профиля (например, 3 дня).[file:79][web:68]

- Для найденных уроков сервис определяет список получателей:
  - по `class_id` и `group_id` (дети, родители, при необходимости учителя);
- После отправки уведомлений сервис должен обновить соответствующие записи:

  ```sql
  UPDATE schedule_cache
  SET is_change_notified = 1
  WHERE id IN (...);
  ```

Таким образом, изменения, происходящие заранее (например, за 5–10 дней до урока), кэшируются, но уведомления по ним отправляются только при приближении урока к заданному N‑дневному окну. Пользователи не получают дубли благодаря флагу `is_change_notified`.[file:63]

Все операции с временем в `NotificationService` (`send_morning_reminders`, `send_pre_lesson_reminders`, `send_upcoming_changes`) должны использовать явно заданный часовой пояс через `ZoneInfo`:

- `now = datetime.datetime.now(ZoneInfo("Asia/Novosibirsk"))` (или другой конкретный tz, определённый в конфиге);
- `start_time` для уроков необходимо превращать из строк NIKA в `datetime` с тем же tz.

Использование `naive datetime` недопустимо, поскольку при деплое на сервер с часовым поясом UTC это приведёт к некорректным расчётам окон и сдвигу уведомлений.[web:68][web:73]

#### Архитектура предурочных уведомлений

Учитывая наличие первой и второй смены, а также возможные замены и отмены уроков, предурочные уведомления не должны основываться на статических cron‑триггерах (фиксированные часы). Время первого урока и последующих занятий может меняться.

Требования к реализации `send_pre_lesson_reminders`:

- Планировщик (например, APScheduler) должен запускать `send_pre_lesson_reminders` по схеме `interval` (каждые 5 минут), а не по фиксированным cron‑временным точкам.
- На каждом запуске метод должен:
  1. Определить текущий момент `now` в локальном часовом поясе.
  2. Сформировать SQL‑запрос к `schedule_cache` для уроков на текущую дату, у которых `is_cancelled = 0`.
  3. Для каждого найденного урока вычислить разницу между `start_time` (преобразованным в `datetime` с датой) и `now`.
  4. Если разница равна заданному интервалу напоминания (N минут, из конфигурации/настроек пользователя), сформировать список получателей:
     - для детей — искать профили по `class_id` и `group_id` (связь `users.class_id/group_id`);
     - при необходимости учитывать доп. занятия из `extra_classes`.
  5. Отправить уведомления соответствующим `user_id` через Telegram‑бота.

Такой подход гарантирует корректность предурочных уведомлений даже при изменении расписания звонков, появлении второй смены или динамических замен/отмен в NIKA.[file:3][file:63]

## 8. Структура бота и обработчики

### 8.1. Основные команды

Для ролей `child` и `parent`:
- `/start` — регистрация, выбор роли (ребёнок/родитель/учитель/наблюдатель).
- `/link_family` — ввод кода семьи для родителя, привязка детей.
- `/set_class` — выбор класса и, при необходимости, группы ребёнка.
- `/today` — расписание на сегодня для текущего выбранного ребёнка/ученика.
- `/week` — расписание на неделю.
- `/class_today` — расписание класса на сегодня (для наблюдателя/родителя).

Для роли `teacher` (на будущее):
- `/my_schedule_today` — расписание учителя на сегодня.
- `/my_schedule_week` — расписание учителя на неделю.

Для общего использования:
- `/room` — занятость конкретного кабинета.

Для роли `admin` должны быть доступны команды:
- `/admin_users` — список пользователей с их ролями и статусами;
- `/admin_families` — список семей и состава;
- `/admin_settings` — просмотр/изменение глобальных настроек (например, TIMEZONE, retention raw_nika_cache).

### 8.2. Обработчики (bot/handlers)

Рекомендуется организовать по модулям:

```text
handlers/
  registration.py    # /start, выбор роли, ввод family_code
  schedule_child.py  # /today, /week для детей
  schedule_parent.py # выбор ребёнка, просмотр расписания
  schedule_teacher.py# команды учителя
  rooms.py           # занятость кабинетов
  settings.py        # настройка класса/группы, уведомления
```

Каждый обработчик использует `ProfileService` и `ScheduleServiceV2` для получения данных.

Модуль `schedule_parent.py` должен поддерживать:
- выбор одного из детей для просмотра расписания и уведомлений;
- отображение списка детей (имя, класс, группа);
- включение/выключение уведомлений отдельно для каждого ребёнка.

Модуль `schedule_child.py` или отдельный `changes.py` должен реализовывать команду (например `/changes`), которая показывает пользователю краткую сводку изменений расписания за последние N дней, даже если уведомления об изменениях отключены.

## 9. Дополнительные функции на будущее

### 9.1. Учетка учителя

- Профиль `role = 'teacher'` с `teacher_id` из NIKA.[^1]
- Возможности:
  - просмотр своего расписания;
  - просмотр расписаний классов, где он преподаёт;
  - возможность отмечать отмены/переносы (при появлении соответствующего API или интеграции).

### 9.2. Многошколность

- Возможность поддерживать несколько школ с разными источниками расписания (разные URL и форматы), через конфигурацию `SCHOOL_ID` и таблицу `schools`.
- Каждая школа имеет свой `BASE_URL` и особый модуль парсинга; общий интерфейс `ScheduleFetcher`.

### 9.3. Интеграция с другими системами

- Экспорт расписания в формат iCal для детей/родителей.
- Веб‑панель для администратора школы (просмотр состояния бота, логов, ошибок парсинга).

## 10. Рекомендации к разработке

### 10.1. Общие принципы

- **Модульность:**
  - не связывать напрямую обработчики бота с логикой парсинга; всегда идти через сервисы.
- **Конфигурируемость:**
  - вынести URL‑ы, таймауты, интервалы напоминаний, school_id в `Config`.
- **Тестирование:**
  - написать юнит‑тесты для `NikaNormalizer` (на базе реального `nika_data_*.js`);
  - тесты для ScheduleServiceV2: корректный фильтр по группе, учёт замен.

### 10.2. Error‑handling

- При недоступности сайта:
  - логировать ошибку;
  - использовать данные из `schedule_cache`;
  - при наличии записей в `raw_nika_cache` сохранять их для анализа;
  - уведомлять администратора (отдельный чат/лог).

- При изменении структуры NIKA:
  - проверять наличие ключевых узлов (`CLASS_SCHEDULE`, `TEACH_SCHEDULE`, `SUBJECTS`, `TEACHERS`, `ROOMS`, `CLASSGROUPS`, `LESSON_TIMES`);
  - при отсутствии отдельных узлов работать в degraded‑режиме (например, без расписания по учителям или кабинетам), опираясь на существующий кеш;
  - использовать последние записи `raw_nika_cache` для адаптации нормализатора.[file:3]

- При работе на сервере в РФ или другом ограниченном окружении:
  - при необходимости включать прокси в `ScheduleFetcher` через конфиг и логировать использование прокси.

логика предурочных уведомлений опирается на актуальные данные из schedule_cache, и любые изменения расписания учитываются автоматически при следующем запуске интервал‑планировщика.

Политика хранения слепков NIKA:

- `raw_nika_cache` предназначена не для долгосрочного хранения, а исключительно для кратковременного дебага при изменении структуры NIKA.
- Система должна автоматически удалять устаревшие записи, чтобы база не разрасталась. По умолчанию рекомендуется хранить слепки не более 1 суток; значение периода хранения настраивается через конфиг (при необходимости можно увеличить, но не обязательно более нескольких дней).[file:79]; при желании можно уменьшить до 1 дня).[file:3]

Часовой пояс системы:

- Конфиг должен содержать параметр `TIMEZONE` (например, `"Asia/Novosibirsk"`), который используется:
  - при создании всех объектов `datetime` в сервисах;
  - при настройке триггеров APScheduler.
- Любая логика уведомлений должна опираться на tz-aware `datetime` с этим `TIMEZONE`. Использование `naive datetime` (без tz) считается ошибкой реализации.[web:73][web:75]

### 10.3. Памятка разработчику

- Не хардкодить класс, группу, учителя в коде — всё должно идти из БД/конфига.
- Не привязывать логику бота к конкретным ключам NIKA внутри обработчиков — только через доменные модели.
- При добавлении новых функций сначала расширять доменную модель и сервисы, а уже потом — обработчики.
- Всегда учитывать, что один родитель может иметь нескольких детей в разных классах.

Параметры уведомлений (интервал предурочных напоминаний в минутах и окно по изменениям в днях) должны задаваться через конфиг и/или настройки профиля пользователя:

- `pre_lesson_offset_minutes` — сколько минут до начала урока слать предурочное уведомление;
- `changes_window_days` — сколько дней вперёд учитывать замены/отмены (по умолчанию, например, 3).

Эти параметры используются в `send_pre_lesson_reminders` и `send_upcoming_changes` вместо жёстко зашитых значений.[file:63]

Параметры `pre_lesson_offset_minutes` и `changes_window_days` должны:

- храниться в таблице `users` как поля с значениями по умолчанию (15 минут и 3 дня);
- использоваться `NotificationService` в методах `send_pre_lesson_reminders` и `send_upcoming_changes` вместо жёстко зашитых констант.[file:63]

## 11. Этапы реализации

1. **Подготовка и рефакторинг NIKA‑парсинга**
   - Вынести текущую логику поиска `nika_data` и `json.loads` из `parser.py` в `core/nika/ScheduleFetcher`.[^3]
   - Реализовать `NikaNormalizer` и построение доменных моделей.

2. **Создание ScheduleRepository**
   - Реализовать in‑memory кеш и методы выборки по классу/учителю/кабинету.
   - Добавить запись кеша в БД (`schedule_cache`).

3. **Внедрение ScheduleService v2**
   - Реализовать методы `get_daily_schedule_for_child`, `get_week_schedule_for_child`, `get_daily_schedule_for_class`.
   - Подключить сервис в существующий код бота параллельно старому ScheduleService.

4. **Рефакторинг бота на v2‑сервисы**
   - Переписать основные команды (`/today`, `/week`) на использование ScheduleServiceV2.
   - Удалить зависимость от старого `parser.py`.

5. **Расширение профилей и семейной логики**
   - Обновить таблицу `users` и `families` при необходимости.
   - Добавить команды выбора ребёнка, класса, группы.

6. **Добавление уведомлений на основе v2**
   - Адаптировать NotificationService к новой модели уроков.
   - Протестировать утренние и предурочные напоминания.

7. **Поддержка учительской учётки (этап 2)**
   - Расширить ProfileService и ScheduleServiceV2 для учителей.
   - Добавить соответствующие команды бота.

8. **Оптимизация и мониторинг**
   - Добавить логирование количества уроков, классов, учителей.
   - Настроить мониторинг ошибок парсинга и оповещения.

Этот план позволяет постепенно перейти от текущей моноклассной реализации к универсальному, модульному боту расписания для школы, при этом сохранив совместимость по API с существующей логикой сохранения и использования расписания.[^3][^1]

---

## References

1. [repomix-output.txt](repomix-output.txt)

2. [schedule.txt](schedule.txt)

3. [parser.py](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/85441044/0da6bae6-e912-441c-9165-e111893cb78c/parser.py) - #!/etc/mihomo/python3/venv/bin/python3
# -*- coding: utf-8 -*-

import requests
import json
import u...

