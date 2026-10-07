# ТЗ: UI/UX и HTML-архитектура PWA «Расписание»

## 1. Назначение документа

Этот документ фиксирует единый контракт для разработки нового UI/UX и HTML-архитектуры веб/PWA-версии приложения школьного расписания.

Основной визуальный референс — эталонная карточка расписания из Telegram-бота. Задача веб-версии не в буквальном копировании Telegram-интерфейса, а в переносе его сильной информационной архитектуры в современный mobile-first web UI.

Документ является implementation-ready контрактом для UI/UX-дизайнера, frontend-разработчика, coding agent, разработчика web schemas/mappers и QA.

---

# 2. Основные UX-принципы

## 2.1. Главный принцип

Для ученика карточка должна мгновенно отвечать:

> Что у меня? Когда?

Для преподавателя:

> У кого? Где? Когда?

### Student mode

1. Время.
2. Номер урока.
3. Предмет.
4. Преподаватель.
5. Группа.
6. Кабинет.

### Teacher mode

1. Время.
2. Номер урока.
3. Класс.
4. Группа.
5. Кабинет.
6. Предмет.

Ключевые элементы имеют больший визуальный вес. Вторичная справочная информация визуально спокойнее.

---

# 3. Архитектурные ограничения

Существующая бизнес-логика проекта не переносится в web layer.

Цепочка данных:

```text
Repository
    ↓
Service
    ↓
Domain / internal DTO
    ↓
Web mapper
    ↓
Web schema / view model
    ↓
Jinja template
    ↓
HTML / CSS
```

## Запрещено

- SQL в шаблонах.
- SQL в web routes.
- Repository calls из Jinja.
- Бизнес-логика расписания в Jinja.
- Парсинг NIKA в web layer.
- Определение принадлежности ребёнка к подгруппе внутри HTML.
- Определение изменений внутри HTML.
- Вычисление того, нужно ли объединять одинаковые предметы, внутри шаблона.
- Дублирование domain logic специально для web.

Шаблон получает уже подготовленные данные и занимается только presentation.

---

# 4. Структура проекта

```text
web/
├── app.py
├── deps.py
├── security.py
├── schemas.py
├── mappers.py
│
├── routes/
│   ├── auth.py
│   ├── health.py
│   ├── schedule.py
│   ├── school.py
│   ├── extras.py
│   └── family.py
│
├── templates/
│   ├── base.html
│   │
│   ├── pages/
│   │   ├── dashboard.html
│   │   ├── schedule_day.html
│   │   ├── schedule_week.html
│   │   ├── changes.html
│   │   ├── school.html
│   │   ├── school_search.html
│   │   ├── school_list.html
│   │   ├── school_day.html
│   │   ├── school_week.html
│   │   ├── free_rooms.html
│   │   ├── extras.html
│   │   ├── extra_create.html
│   │   └── family/
│   │       ├── index.html
│   │       ├── members.html
│   │       ├── student.html
│   │       └── settings.html
│   │
│   ├── fragments/
│   │   ├── schedule_day.html
│   │   ├── schedule_week.html
│   │   ├── changes.html
│   │   ├── school_search.html
│   │   ├── school_list.html
│   │   ├── school_day.html
│   │   ├── school_week.html
│   │   └── free_rooms.html
│   │
│   ├── components/
│   │   ├── schedule/
│   │   │   ├── lesson_card.html
│   │   │   ├── lesson_subgroup.html
│   │   │   ├── teacher_lesson_content.html
│   │   │   ├── room_lesson_content.html
│   │   │   ├── room_badge.html
│   │   │   ├── window_card.html
│   │   │   └── day_header.html
│   │   ├── navigation/
│   │   │   ├── bottom_nav.html
│   │   │   ├── day_navigation.html
│   │   │   └── week_navigation.html
│   │   ├── students/
│   │   │   ├── selector.html
│   │   │   └── chip.html
│   │   ├── school/
│   │   │   ├── hub.html
│   │   │   ├── search_form.html
│   │   │   └── school_item.html
│   │   ├── changes/
│   │   │   ├── change_badge.html
│   │   │   └── history_sheet.html
│   │   └── ui/
│   │       ├── empty_state.html
│   │       ├── error_state.html
│   │       ├── loading.html
│   │       └── offline.html
│   │
│   └── errors/
│       ├── 401.html
│       ├── 403.html
│       ├── 404.html
│       └── 500.html
│
└── static/
    ├── css/
    │   ├── app.css
    │   ├── components/
    │   │   ├── schedule.css
    │   │   ├── navigation.css
    │   │   ├── school.css
    │   │   └── forms.css
    │   └── utilities.css
    └── js/
        ├── app.js
        ├── schedule.js
        └── auth.js
```

---

# 5. Роли HTML-файлов

## 5.1. `base.html`

`base.html` — application shell. Содержит общую оболочку приложения, CSS, JS, HTMX, основной `<main>`, bottom navigation и глобальный CSRF для HTMX.

Не содержит бизнес-логику расписания.

```html
<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>{% block title %}Расписание{% endblock %}</title>
    <link rel="stylesheet" href="/static/css/app.css">
</head>
<body hx-headers='{"X-CSRF-Token": "{{ csrf_token }}"}'>
    <header class="app-header">
        {% block header %}{% endblock %}
    </header>

    <main id="main" class="app-main">
        {% block content %}{% endblock %}
    </main>

    {% include "components/navigation/bottom_nav.html" %}

    <script src="/static/js/htmx.min.js"></script>
    <script src="/static/js/htmx-sse.min.js"></script>
    <script src="/static/js/app.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
```

## 5.2. `pages/`

Полноценные страницы, наследующие `base.html`.

Пример:

```text
GET /schedule/day/2026-09-28
        ↓
pages/schedule_day.html
```

## 5.3. `fragments/`

HTMX-фрагменты. Они не содержат `<html>`, `<head>`, `<body>` и не наследуют `base.html`.

## 5.4. `components/`

Переиспользуемые UI-компоненты. Центральный компонент — `components/schedule/lesson_card.html`.

---

# 6. Центральный компонент `LessonCard`

## 6.1. Основной принцип

Не создавать отдельные карточки для student, teacher, class, room, extra, changed или cancelled.

Единый компонент:

```text
components/schedule/lesson_card.html
```

Поддерживает режимы:

```text
student
class
teacher
room
```

Типы:

```text
regular
extra
window
```

Состояния:

```text
normal
changed
added
cancelled
current
```

---

# 7. Общая геометрия LessonCard

Карточка состоит из трёх зон:

```text
┌────────────┬─────────────────────────────┬────────┐
│ TIME       │ MAIN CONTENT                │ ROOM   │
│            │                             │        │
│ 14:00      │ Предмет                     │ [305]  │
│ 14:40      │ Преподаватель · Группа      │        │
│ УРОК 4     │                             │        │
└────────────┴─────────────────────────────┴────────┘
```

## Time zone

Фиксированная ширина примерно `68–78 px`.

Содержит:

```text
14:00
14:40
УРОК 4
```

Правила:

- start time — самый заметный элемент зоны;
- end time — меньше и светлее;
- номер урока — отдельной строкой;
- номер урока — bold;
- ширина time-zone одинаковая во всех карточках;
- длинный предмет не должен сдвигать time-zone.

## Content zone

Основная область контента, зависящая от `view_mode`.

## Room zone

Фиксированная область справа. Кабинет всегда отдельным badge.

```text
┌──────┐
│ 305  │
└──────┘
```

Кабинет никогда не выводится как обычный текст.

Обычный кабинет:

- светлый фон;
- тёмный bold text.

Изменённый кабинет:

- оранжевая рамка;
- оранжевый текст.

---

# 8. Web schema contract

## 8.1. `LessonViewMode`

```python
class LessonViewMode(str, Enum):
    STUDENT = "student"
    CLASS = "class"
    TEACHER = "teacher"
    ROOM = "room"
```

## 8.2. `LessonKind`

```python
class LessonKind(str, Enum):
    REGULAR = "regular"
    EXTRA = "extra"
    WINDOW = "window"
```

## 8.3. `LessonStatus`

```python
class LessonStatus(str, Enum):
    NORMAL = "normal"
    CHANGED = "changed"
    ADDED = "added"
    CANCELLED = "cancelled"
```

---

# 9. `WebChangedValue`

Используется для локального подсвечивания изменённого поля.

```python
class WebChangedValue(BaseModel):
    value: str | None
    changed: bool = False
```

Пример:

```json
{"value": "214", "changed": true}
```

`changed=True` означает, что значение изменилось относительно исходного расписания.

Старое значение не требуется в `WebLesson` для обычного рендера; оно используется в истории через `WebChange`.

---

# 10. `WebRoomBadge`

```python
class WebRoomBadge(BaseModel):
    value: str
    changed: bool = False
```

`value` может быть числом или произвольной строкой, например:

```text
305
201
324а
205(Н)
спортзал
актовый зал
```

---

# 11. `WebLessonEntry`

Одна логическая часть временной ячейки:

```python
class WebLessonEntry(BaseModel):
    subject: WebChangedValue | None = None
    teacher: WebChangedValue | None = None
    group: WebChangedValue | None = None
    class_name: WebChangedValue | None = None
    room: WebRoomBadge | None = None
```

Пример:

```text
Группа 1
Английский
Победа А.А.
230
```

---

# 12. Полный `WebLesson`

Рекомендуемый контракт:

```python
class WebLesson(BaseModel):
    key: str
    number: int | None
    start_time: str
    end_time: str
    view_mode: LessonViewMode
    kind: LessonKind
    status: LessonStatus
    is_current: bool = False
    entries: list[WebLessonEntry] = []
    shared_subject: bool = False
    history_url: str | None = None
    aria_label: str
```

## Значения полей

### `key`

Стабильный UI identifier. Пример: `lesson-2026-09-29-2`.

Используется для DOM, accessibility, тестов, history и будущих live-update механизмов.

### `number`

Номер урока. Если отсутствует — `null`.

### `start_time`, `end_time`

Только строки (`14:00`, `14:40`). Не использовать JS Date для школьного времени.

### `kind`

`regular`, `extra`, `window`.

### `status`

`normal`, `changed`, `added`, `cancelled`.

`kind` и `status` — разные semantic dimensions. Например, `kind=extra` и `status=changed` могут существовать одновременно.

### `is_current`

Текущий урок. Не должен менять геометрию карточки.

### `entries`

Одна или несколько частей урока.

### `shared_subject`

`true` означает, что несколько подгрупп изучают один предмет и предмет должен быть выведен один раз.

### `history_url`

URL истории изменений либо `null`.

### `aria_label`

Готовое доступное описание карточки.

---

# 13. Mapper contract

Рекомендуемые функции:

```python
def lesson_to_web(
    lesson: DayLessonDTO,
    *,
    view_mode: LessonViewMode,
    student_profile_id: int | None = None,
) -> WebLesson:
    ...
```

и:

```python
def lessons_to_web(
    lessons: Iterable[DayLessonDTO],
    *,
    view_mode: LessonViewMode,
    student_profile_id: int | None = None,
) -> list[WebLesson]:
    ...
```

Mapper отвечает за:

- нормализацию;
- выбор relevant subgroup;
- определение одинакового предмета;
- определение changed fields;
- presentation режима;
- объединение нескольких классов преподавателя;
- формирование history URL;
- подготовку accessibility текста.

Template не решает эти задачи.

---

# 14. Student / Class mode

## Обычный урок

```text
14:00
14:40
УРОК 4

Биология
Потапова М.В. · Группа 2

                         [305]
```

Предмет:

- крупный;
- semibold/bold;
- основной цвет;
- одна строка.

Преподаватель:

- маленький;
- серый;
- italic;
- secondary.

Группа:

- маленький;
- серый;
- через разделитель `·`.

---

# 15. Один предмет + несколько подгрупп

Если несколько подгрупп изучают один предмет, предмет не дублируется.

Например:

```text
Английский язык

Победа А.А. · Группа 1       [230]
Погорцева Г.К. · Группа 2    [324]
```

Правильное представление:

```text
┌─────────────────────────────────────────────┐
│ 2 │ 14:55                                  │
│   │ 15:35                                  │
│   │ УРОК 2                                 │
│   │                                         │
│   │ Английский язык                         │
│   │ Победа А.А. · Группа 1          [230]  │
│   │ Погорцева Г.К. · Группа 2        [324]  │
└─────────────────────────────────────────────┘
```

Предмет показывается один раз. Под ним — строки подгрупп.

---

# 16. Разные предметы по подгруппам

Если одновременно проходят разные предметы:

```text
┌─────────────────────────────────────────────┐
│ 2 │ 14:55                                  │
│   │ 15:35                                  │
│   │ УРОК 2                                 │
│   │                                         │
│   │ Ин. язык                         [324а]│
│   │ Корчмит О.О. · Группа 1                │
│   │ ─────────────────────────────────────  │
│   │ Программирование                 [301] │
│   │ Гурина А.А. · Группа 2                 │
└─────────────────────────────────────────────┘
```

Правила:

- номер урока и время один раз;
- это одна lesson card;
- 2–3 subgroup blocks допустимы;
- разделитель тонкий;
- не использовать отдельные полноценные вложенные карточки;
- каждый блок должен легко сканироваться.

---

# 17. Student target mode

Если родитель или ребёнок выбрал конкретного ребёнка, показывается только его подгруппа без показа наименования Группа

Пример:

```text
Ребёнок:
Лиза · 6а · Группа 2
```

Исходные данные:

```text
Группа 1 → Английский → Корчмит → 324а
Группа 2 → Программирование → Гурина → 301
```

Presentation model ребёнка:

```text
Программирование
Гурина А.А. 
[301]
```

Группа 1 не должна приходить в presentation model.
Наименование группа не должно выводиться в карточку

---

# 18. Teacher mode

Для преподавателя карточка сохраняет ту же геометрию, но имеет другую информационную иерархию.

```text
┌───────────────────────────────────────────────┐
│ 4 │ 16:40                                    │
│   │ 17:20                                    │
│   │ УРОК 4                                   │
│   │                                          │
│   │ 6а · группа 2                      [201] │
│   │ Математика                               │
└───────────────────────────────────────────────┘
```

Приоритет:

```text
Класс / группа
↓
Кабинет
↓
Предмет
```

---

# 19. Несколько классов одновременно

Если преподаватель одновременно ведёт:

```text
6а · группа 1
6б · группа 2
7а · группа 1
```

нельзя создавать три карточки.

Одна карточка:

```text
6а · группа 1, 6б · группа 2, 7а · группа 1     [201]

Математика
```

Класс — основной текст. Группа — серый, но примерно того же размера, что и класс. Предмет — secondary.

---

# 20. Teacher windows

Окно преподавателя — компактная карточка:

```text
┌──────────────────────────────────────────┐
│ 3 │ 15:50–16:30                         │
│   │ Свободное время                      │
└──────────────────────────────────────────┘
```

Требования:

- значительно ниже обычной карточки;
- muted background;
- нет большого room badge;
- нет тяжёлого primary content;
- предназначено для быстрого анализа свободного времени.

CSS: `lesson-card--window`.

---

# 21. Изменения расписания

Для изменённой карточки:

```text
lesson-card--changed
```

Сохраняется исходная геометрия.

Обычная карточка — синяя левая граница.

Изменённая — оранжевая левая граница.

Вся карточка не перекрашивается в orange.

---

# 22. Локальное выделение изменённого поля

## Изменён предмет

Orange только новая/изменённая часть:

```text
Биология → История
```

## Изменён преподаватель

Orange только изменённое значение:

```text
Петрова Е.В.
```

## Изменён кабинет

```text
[214]
```

Orange border + orange text.

---

# 23. История изменений

Если `lesson.history_url != null`, карточка интерактивна.

По tap открывается bottom sheet или HTMX fragment:

```text
ИЗМЕНЕНИЯ

Урок 4
16:40–17:20

ПРЕДМЕТ
Было: Биология
Стало: История

УЧИТЕЛЬ
Было: Иванов И.И.
Стало: Петрова Е.В.

КАБИНЕТ
Было: 305
Стало: 214
```

`Было` — subdued.

`Стало` — orange.

При множественных изменениях — хронологическая история.

---

# 24. `WebChange`

```python
class WebChange(BaseModel):
    field: Literal[
        "subject",
        "teacher",
        "group",
        "class",
        "room",
    ]

    old_value: str | None
    new_value: str | None

    changed_at: str | None = None
```

`WebLesson` нужен для текущего состояния.

`WebChange` нужен для истории.

---

# 25. Дополнительные занятия

Дополнительные занятия входят в общий timeline.

Semantic color:

```text
purple
```

Обычный урок:

```text
blue
```

Изменение:

```text
orange
```

Дополнительное:

```text
purple
```

Для extra:

- purple left border;
- light purple tint;
- badge `доп.`;
- обычный room badge.

---

# 26. Добавленный урок

```text
lesson-card--added
```

Semantic color: `green`.

---

# 27. Отменённый урок

```text
lesson-card--cancelled
```

Semantic color: `red`.

Предмет может быть зачёркнут. Кабинет убирается из вывода

Урок остаётся во временной сетке и не удаляется из timeline.

---

# 28. Текущий урок

```text
lesson-card--current
```

Использовать:

- небольшой badge `Сейчас`;
- subtle highlight;
- умеренный усиленный border.

Не увеличивать карточку.

---

# 29. Длинные названия предметов

Пример:

```text
Основы естественно-научных исследований
```

Предмет по возможности должен оставаться в одну строку.

Ориентир adaptive typography:

```text
normal:      20–22 px
medium:      18–20 px
long:        16–18 px
very long:   14–16 px
```

Нельзя просто скрывать конец строки через `overflow: hidden`, если это приводит к потере информации.

Если текст визуально уменьшен, полное название должно оставаться доступным через accessibility и/или detail view.

---

# 30. Базовый HTML `LessonCard`

```html
<article
    class="
        lesson-card
        lesson-card--{{ lesson.kind }}
        lesson-card--{{ lesson.status }}
        {% if lesson.is_current %}
            lesson-card--current
        {% endif %}
    "
    data-lesson-key="{{ lesson.key }}"
>

    <div class="lesson-card__time">
        <time class="lesson-card__start">{{ lesson.start_time }}</time>
        <time class="lesson-card__end">{{ lesson.end_time }}</time>

        {% if lesson.number is not none %}
            <span class="lesson-card__number">
                УРОК {{ lesson.number }}
            </span>
        {% endif %}
    </div>

    <div class="lesson-card__body">

        {% if lesson.view_mode in ["student", "class"] %}

            {% if lesson.shared_subject %}
                <div class="lesson-card__subject">
                    {{ lesson.entries[0].subject.value }}
                </div>

                <div class="lesson-card__entries">
                    {% for entry in lesson.entries %}
                        {% include "components/schedule/lesson_subgroup.html" %}
                    {% endfor %}
                </div>

            {% else %}
                <div class="lesson-card__entries">
                    {% for entry in lesson.entries %}
                        {% include "components/schedule/lesson_subgroup.html" %}
                    {% endfor %}
                </div>
            {% endif %}

        {% elif lesson.view_mode == "teacher" %}
            {% include "components/schedule/teacher_lesson_content.html" %}

        {% elif lesson.view_mode == "room" %}
            {% include "components/schedule/room_lesson_content.html" %}
        {% endif %}

    </div>

    {% if lesson.entries and lesson.entries[0].room %}
        <div class="lesson-card__room">
            {% include "components/schedule/room_badge.html" %}
        </div>
    {% endif %}

</article>
```

> Примечание для реализации: logic выбора room и других nested values должна быть подготовлена mapper/view-model. Если потребуется сложная условная логика, вынести её из `lesson_card.html` в отдельный presentation component, а не наращивать условия в шаблоне.

---

# 31. `lesson_subgroup.html`

```html
<div class="lesson-entry">
    <div class="lesson-entry__content">

        {% if entry.subject %}
            <div class="lesson-entry__subject">
                {{ entry.subject.value }}
            </div>
        {% endif %}

        <div class="lesson-entry__meta">

            {% if entry.teacher %}
                <span class="lesson-entry__teacher">
                    {{ entry.teacher.value }}
                </span>
            {% endif %}

            {% if entry.group %}
                <span class="lesson-entry__separator">·</span>
                <span class="lesson-entry__group">
                    {{ entry.group.value }}
                </span>
            {% endif %}

        </div>
    </div>

    {% if entry.room %}
        <span class="room-badge">{{ entry.room.value }}</span>
    {% endif %}
</div>
```

---

# 32. `room_badge.html`

```html
<span
    class="
        room-badge
        {% if room.changed %}
            room-badge--changed
        {% endif %}
    "
>
    {{ room.value }}
</span>
```

Кабинет — отдельный reusable component.

---

# 33. Основной CSS layout

Карточка реализуется через CSS Grid, а не HTML `<table>`.

```css
.lesson-card {
    display: grid;

    grid-template-columns:
        var(--lesson-time-width)
        minmax(0, 1fr)
        var(--lesson-room-width);
}
```

Это сохраняет табличную структуру старого сайта и одновременно поддерживает:

- подгруппы;
- responsive;
- разные состояния;
- extra;
- changes;
- teacher mode;
- room mode.

---

# 34. Day fragment

`fragments/schedule_day.html`:

```html
<section class="schedule-day">

    {% include "components/schedule/day_header.html" %}

    <div class="schedule-list">

        {% for lesson in lessons %}

            {% if lesson.kind == "window" %}
                {% include "components/schedule/window_card.html" %}
            {% else %}
                {% include "components/schedule/lesson_card.html" %}
            {% endif %}

        {% endfor %}

    </div>

</section>
```

---

# 35. Навигация по дням

Компонент:

```text
components/navigation/day_navigation.html
```

Пример:

```text
┌─────────┬────────────┬─────────┐
│ ← Пред. │ Сегодня    │ След. → │
└─────────┴────────────┴─────────┘
```

Требования:

- swipe left/right;
- кнопки;
- HTMX;
- `hx-push-url`;
- F5 открывает тот же день;
- touch targets минимум 44 px.

---

# 36. Навигация по неделям

Пример:

```text
← Пред. нед.   Текущая   След. нед. →
```

Дни:

```text
ПН 28.09     6 уроков · 3 доп.
ВТ 29.09     6 уроков · 1 изменение
СР 30.09     5 уроков · 1 доп.
ЧТ 01.10     6 уроков · 2 доп.
ПТ 02.10     7 уроков · 1 изменение
```

Tap по дню → day view.

Не использовать большие календарные tiles.

---

# 37. Dashboard

`pages/dashboard.html` собирает:

```text
Header
   ↓
StudentSelector
   ↓
DayNavigation
   ↓
DayHeader
   ↓
LessonList
   ↓
BottomNavigation
```

Главный экран содержит:

- текущего ребёнка;
- быстрый переключатель детей;
- дату;
- summary;
- список уроков;
- bottom nav.

---

# 38. School

Главный hub:

```text
🏫 Школа

[ Класс, учитель, кабинет... ] [Найти]

┌──────────────┐ ┌──────────────┐
│ 🎓           │ │ 👨‍🏫          │
│ Классы       │ │ Учителя      │
└──────────────┘ └──────────────┘

┌──────────────┐ ┌──────────────┐
│ 🚪           │ │ 🟢           │
│ Кабинеты     │ │ Свободные    │
└──────────────┘ └──────────────┘
```

Результаты поиска группируются по типам:

```text
Классы
Учителя
Кабинеты
```

---

# 39. School schedule

Используется тот же `LessonCard`.

## Class

```text
view_mode=class
```

Primary — предмет. Secondary — учитель/группа. Room — badge.

## Teacher

```text
view_mode=teacher
```

Primary — класс/группа. Secondary — предмет. Room — badge.

## Room

```text
view_mode=room
```

Primary — предмет. Secondary — класс/группа/преподаватель. Room — badge.

---

# 40. Дополнительные занятия

`pages/extra_create.html`.

Поля:

```text
Предмет *
Дата *
Начало *
Окончание *
Место *
Учитель
```

Ниже — preview.

Preview обязан использовать **тот же `LessonCard`**, что и реальное расписание.

---

# 41. Bottom Navigation

Компонент:

```text
components/navigation/bottom_nav.html
```

Разделы:

```text
📅 Сегодня
🗓 Неделя
🏫 Школа
🎯 Доп. занятия
👥 Семья
```

Текущий раздел получает active blue state.

Bottom nav:

- fixed/sticky;
- учитывает `safe-area`;
- не перекрывает timeline.

---

# 42. Responsive

Основные viewport:

```text
375 × 812
390 × 844
393 × 852
430 × 932
```

Ключевой acceptance criterion:

> На `390 × 844` должно помещаться минимум 8 обычных уроков.

Для этого:

- ограничить высоту header;
- убрать лишние vertical paddings;
- не делать giant cards;
- room badge компактный;
- metadata компактная;
- windows ещё компактнее.

Время, предмет и кабинет должны оставаться читаемыми.

---

# 43. Геометрия

Ориентиры:

```text
Time zone:
68–78 px

Room zone:
52–88 px

Обычная карточка:
64–76 px

Composite card:
96–128 px

Window:
40–48 px
```

Composite card с несколькими подгруппами закономерно выше обычной.

---

# 44. Типографика

## Student mode

```text
start time     20–22 px / bold
end time       14–16 px
lesson number  14–15 px / bold
subject        18–22 px / 600–700
teacher        13–14 px / italic / gray
group          13–14 px / gray
room           16–19 px / bold
```

## Teacher mode

```text
class          18–20 px / 600
group          16–18 px / gray
room           16–19 px / bold
subject        13–15 px / italic / gray
```

Это стартовые значения, которые должны быть проверены на реальных viewport.

---

# 45. Цветовая система

Semantic tokens:

```css
--schedule-normal
--schedule-extra
--schedule-changed
--schedule-added
--schedule-cancelled
--schedule-current

--room-bg
--room-text
--room-changed
```

Семантика:

```text
BLUE    → обычный
PURPLE  → дополнительное занятие
ORANGE  → изменение
GREEN   → добавленный урок
RED     → отменённый урок
```

Цвет не должен быть единственным способом передачи состояния. Использовать также border, badge, icon, strike-through и text treatment.

---

# 46. CSS-классы

```text
.lesson-card
.lesson-card__time
.lesson-card__start
.lesson-card__end
.lesson-card__number
.lesson-card__body
.lesson-card__subject
.lesson-card__meta
.lesson-card__entries
.lesson-card__room

.lesson-entry
.lesson-entry__content
.lesson-entry__subject
.lesson-entry__meta
.lesson-entry__teacher
.lesson-entry__group
.lesson-entry__separator

.room-badge

.lesson-card--regular
.lesson-card--extra
.lesson-card--changed
.lesson-card--added
.lesson-card--cancelled
.lesson-card--window
.lesson-card--current

.lesson-card__field--changed
.room-badge--changed
```

---

# 47. HTMX

Полная страница:

```text
pages/schedule_day.html
```

HTMX fragment:

```text
fragments/schedule_day.html
```

Навигация:

```html
hx-get="/schedule/day/2026-09-29"
hx-target="#main"
hx-push-url="true"
```

или точечный target:

```html
hx-target="#day-content"
```

История:

```html
hx-get="{{ lesson.history_url }}"
hx-target="#history-sheet"
```

GET не меняет серверное состояние.

---

# 48. JavaScript

Не использовать inline JavaScript.

Запрещено:

```html
onclick="..."
```

Использовать:

```text
/static/js/app.js
/static/js/schedule.js
```

Для client behavior использовать `data-*` attributes:

```html
data-autofit="subject"
data-lesson-key="..."
data-history-url="..."
```

---

# 49. Accessibility

Обязательно:

- keyboard navigation;
- `focus-visible`;
- semantic elements;
- доступные `aria-label`;
- корректные buttons/links;
- `<time>` для времени;
- видимое focus state;
- touch targets ≥44 px.

Цвет не является единственным индикатором изменения.

---

# 50. Fixture data для разработки

До подключения production backend создать набор fixtures.

## Fixture A — обычный урок

```text
Биология
Потапова М.В.
Группа 2
305
```

## Fixture B — один предмет / две группы

```text
Английский

Победа А.А. · Группа 1 · 230
Погорцева Г.К. · Группа 2 · 324
```

## Fixture C — разные предметы

```text
Ин. язык · Гр.1 · 324а
Программирование · Гр.2 · 301
```

## Fixture D — teacher

```text
6а · Гр.1
6б · Гр.2
7а · Гр.1

Математика

201
```

## Fixture E — changed room

```text
[214] orange
```

## Fixture F — changed teacher

Orange только новый/изменившийся teacher.

## Fixture G — changed subject

Orange только новый/изменившийся subject.

## Fixture H — cancelled

Red + strike-through.

## Fixture I — added

Green.

## Fixture J — extra

Purple.

## Fixture K — current

Subtle current state.

## Fixture L — window

Compact teacher window.

## Fixture M — long subject

```text
Основы естественно-научных исследований
```

---

# 51. Dev showcase page

До интеграции с реальным расписанием создать временную страницу:

```text
/dev/schedule-components
```

Она должна показывать одновременно:

- обычную карточку;
- extra;
- changed;
- added;
- cancelled;
- current;
- window;
- одну подгруппу;
- один предмет + 2 группы;
- разные предметы + 2 группы;
- 3 подгруппы;
- teacher mode;
- room mode;
- long subject.

Это основная страница визуальной приёмки `LessonCard`.

---

# 52. Acceptance criteria

## Состояния

```text
[ ] regular
[ ] extra
[ ] changed
[ ] added
[ ] cancelled
[ ] current
[ ] window
```

## Подгруппы

```text
[ ] одна группа
[ ] один предмет + 2 группы
[ ] один предмет + 3 группы
[ ] разные предметы + 2 группы
[ ] разные предметы + 3 группы
```

## Режимы

```text
[ ] student
[ ] class
[ ] teacher
[ ] room
```

## Student

```text
[ ] ребёнок видит только relevant subgroup
[ ] subject — основная информация
[ ] teacher/group — secondary
[ ] room — самостоятельный badge
```

## Teacher

```text
[ ] class/group — primary
[ ] room — visible
[ ] subject — secondary
[ ] 2–3 класса одной строкой
[ ] окно compact
```

## Changes

```text
[ ] changed subject
[ ] changed teacher
[ ] changed room
[ ] orange card accent
[ ] local orange field highlight
[ ] history sheet
```

## Responsive

```text
[ ] 375×812
[ ] 390×844
[ ] 393×852
[ ] 430×932
[ ] ≥8 обычных уроков на 390×844
```

## Interaction

```text
[ ] touch target ≥44 px
[ ] keyboard navigation
[ ] focus-visible
[ ] HTMX
[ ] hx-push-url
[ ] F5 сохраняет текущий URL/экран
[ ] CSP не нарушается
[ ] нет inline JS
```

---

# 53. Порядок реализации

Не переделывать сразу все страницы.

## Stage 1 — Web contracts

Зафиксировать:

```text
WebChangedValue
WebRoomBadge
WebLessonEntry
WebLesson
WebChange
LessonViewMode
LessonKind
LessonStatus
```

Добавить schema tests.

## Stage 2 — Fixture page

Создать:

```text
/dev/schedule-components
```

и визуально проверить все состояния.

## Stage 3 — LessonCard

Сначала добиться эталона на:

```text
390 × 844
```

Затем проверить:

```text
375
393
430
```

## Stage 4 — CSS

После утверждения геометрии перенести стили в:

```text
web/static/css/components/schedule.css
```

## Stage 5 — Real mapper

Подключить:

```text
ScheduleService
    ↓
Web mapper
    ↓
WebLesson
    ↓
LessonCard
```

## Stage 6 — Student schedule

Подключить к `/schedule/day`.

## Stage 7 — Teacher

Подключить `view_mode=teacher`.

## Stage 8 — School

Подключить `class`, `teacher`, `room`.

## Stage 9 — Week

Подключить weekly summaries и переходы в day view.

## Stage 10 — Changes / Extras

После стабилизации base component:

```text
history
extra
added
cancelled
```

---

# 54. Full page vs fragment — итог

```text
pages/
    ↓
полная страница
    ↓
base.html
    ↓
components + fragments

fragments/
    ↓
HTMX partial update
    ↓
components

components/
    ↓
reusable UI
    ↓
LessonCard
```

---

# 55. Финальная архитектура LessonCard

```text
                       WebLesson
                           │
                           ▼
                    ┌─────────────┐
                    │ LessonCard  │
                    └──────┬──────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
         Student         Teacher          Room
            │              │              │
        Subgroups      Class / Group   Class / Teacher
            │
       ┌────┴────┐
       │         │
 same subject   different subjects
       │         │
 subject once  subject per subgroup
```

Общая геометрия:

```text
┌────────┬────────────────────────────┬────────┐
│ TIME   │ PRIMARY                    │ ROOM   │
│        │                            │        │
│ 14:00  │ Биология                   │  305   │
│ 14:40  │ Потапова · Группа          │        │
│ УРОК 4 │                            │        │
└────────┴────────────────────────────┴────────┘
```

### Student

```text
PRIMARY = Предмет
SECONDARY = Преподаватель · Группа
ROOM = Кабинет
```

### Teacher

```text
PRIMARY = Класс · Группа
SECONDARY = Предмет
ROOM = Кабинет
```

### Room

```text
PRIMARY = Предмет
SECONDARY = Класс · Группа · Преподаватель
ROOM = Кабинет
```

---

# 56. Ключевое правило разработки

Не начинать с полной переделки `schedule/day`, `school`, `teacher` и `week`.

Сначала реализовать и визуально утвердить:

```text
LessonCard
+
LessonSubgroup
+
RoomBadge
+
Teacher content
+
WindowCard
```

на fixture data.

После утверждения компонентов подключить их к существующим backend service/mappers.

Так весь интерфейс будет строиться вокруг одного стабильного визуального контракта, а разные экраны не разойдутся по стилю.




---

# ТЗ 2. TODO на будущее — настоящий DayPager

А это я бы действительно сохранил отдельным `TODO.md`, потому что это уже **другая архитектурная ступень**, а не очередной фикс. Ваш текущий анализ именно так и классифицирует этот вариант. :contentReference[oaicite:0]{index=0}

```md
# TODO — Full DayPager / Native Gallery-like Day Navigation

## Цель

Если в будущем потребуется максимально нативное
gallery-like перелистывание расписания,
реализовать отдельный `DayPager`.

Главное отличие:

соседний день становится не временным preview,
а полноценной частью pager state.

## Целевая модель

```text
                    DayPager
                       │
          ┌────────────┼────────────┐
          │            │            │
      previous      current       next
       fragment      fragment     fragment
          │            │            │
          └──── interactive drag ───┘


Pager одновременно знает:
current URL;
previous URL;
next URL;
current fragment;
previous fragment;
next fragment;
request status;
active navigation token;
selected target/profile identity;
cache version.
Interaction
drag left
→ current + next move together
→ real next day already available/preloading
→ release < threshold
→ snap-back

release >= threshold
→ next becomes current
Аналогично для previous.
Navigation ownership
DayPager становится owner day navigation.
Один controller обслуживает:
swipe;
previous arrow;
next arrow;
Today;
browser history.
Не должно существовать параллельных navigation implementations.
Canonical state
В отличие от текущего temporary-preview подхода:
previous
current
next
являются полноценными pager states.
Visual state и application day state
должны быть согласованы.
Не допускается:
visible = Wednesday
canonical = Tuesday
Network
Нужен отдельный request lifecycle:
idle
loading-current
ready
loading-neighbour
dragging
settling
committing
error
Поддержать:
abort stale requests;
request tokens;
stale response rejection;
concurrent preload control;
retry/error state.
Prefetch
После установки current day:
preload previous
preload next
Cache только:
previous
current
next
Старые дни удаляются.
History
History management централизован
в DayPager.
Swipe и arrows используют один механизм.
Browser:
Back
Forward
должен синхронизировать pager state.
Live updates
ScheduleChanged должен инвалидировать
или revalidate соответствующий pager fragment.
Нельзя показывать устаревший соседний день
как canonical после изменения расписания.
Target identity
Pager cache должен быть привязан как минимум к:
current authenticated user/session;
selected student/profile;
class/teacher/room target;
date.
Нельзя использовать HTML одного target
для другого target.
PWA
Оптимизировать прежде всего:
iPhone Safari;
installed iOS PWA;
Android Chrome;
installed Android PWA.
UX
Сохранить:
direct manipulation;
drag 1:1 за пальцем;
~45% viewport commit threshold;
snap-back;
clean horizontal transition;
fixed application header;
fixed bottom navigation.
Не добавлять без необходимости:
3D page curl;
heavy physics;
parallax;
blur;
zoom;
сложный carousel framework.

```

## Рекомендуемый TODO-план DayPager

# Этап P1 — подготовить fragment contract
[ ] Зафиксировать единый DayFragment contract для personal и school screens.
[ ] Разделить outer pager slot и внутренний day fragment.
[ ] Убрать зависимость pager от duplicate id="day-content".
[ ] Добавить data attributes:
    - data-day-url;
    - data-previous-url;
    - data-next-url;
    - data-week-url;
    - data-pager-identity.
[ ] Не переносить календарную арифметику в JavaScript.
[ ] Сохранить обычные href links как progressive enhancement fallback.

# Этап P2 — pager без drag
[ ] Создать web/static/js/day-pager.js.
[ ] Поднять three-slot DOM: previous/current/next.
[ ] Загрузить current fragment.
[ ] После current load preload previous и next.
[ ] Реализовать bounded memory: только три DOM slots.
[ ] Добавить AbortController и navigation token.
[ ] Реализовать transition кнопками previous/next без HTMX outerHTML swap.
[ ] Обновлять history только после completed navigation.

Это самый важный этап: сначала доказать корректность state machine без gesture animation.

# Этап P3 — native drag

[ ] Pointer Events.
[ ] Horizontal direction lock.
[ ] CSS transform translate3d().
[ ] Drag following finger.
[ ] Threshold commit.
[ ] Velocity commit.
[ ] Snap-back animation.
[ ] pointercancel / lost pointer capture.
[ ] block interaction с inactive pages.
[ ] prefers-reduced-motion.

# Этап P4 — integration

[ ] popstate rebuild.
[ ] SSE invalidates neighbours.
[ ] Profile/child switch destroys pager state.
[ ] School mode:
    - class;
    - teacher;
    - room;
    - origin=free-rooms.
[ ] Day → Week contextual button.
[ ] Week → Day contextual button.
[ ] PWA offline failure state для missing neighbour.
[ ] Browser/PWA smoke tests.

# Критерии готовности

[ ] При drag соседний день реально следует за пальцем.
[ ] Нет white screen, skeleton flash или late DOM replacement после release.
[ ] Release ниже threshold возвращает exact current screen.
[ ] Быстрый swipe не запускает duplicate navigation.
[ ] 10 быстрых свайпов не создают race condition.
[ ] В DOM максимум три day slots.
[ ] Нет duplicate IDs.
[ ] Previous/next days недоступны через Tab и screen reader.
[ ] Back/Forward открывают правильную дату.
[ ] Switch child/class/teacher/room отменяет старые request.
[ ] SSE change не показывает stale preloaded neighbor как актуальный.
[ ] Room origin=free-rooms не теряется.
[ ] Offline missing neighbour показывает понятный fallback, а не blank screen.

# Мой совет по приоритету
Это хорошая после-8D задача, но я бы не начинал её до того, как вы:

1. Зафиксируете текущий app-shell/PWA state отдельным commit.
2. Добавите хотя бы базовые automated smoke tests для day/week URLs.
3. Стабилизируете PWA update workflow.

[ ] Не полагаться на service worker в pager-коде.
[ ] Не использовать window.open / target="_blank" в pager.
[ ] touch-action: pan-y на pager surface —
    чтобы не конфликтовать с Telegram горизонтальными жестами.
[ ] Не начинать drag в зоне ~20px от левого/правого края экрана —
    iOS edge-swipe back должен остаться системным.
[ ] Проверить popstate в Telegram WebView отдельно:
    BackButton Telegram и history.back() должны сходиться к одной истории.
[ ] prefers-reduced-motion проверить в обоих окружениях.
[ ] Тестировать drag на реальном iPhone внутри Telegram.



# TODO Miniapp + переход в браузер
Рекомендуемый roadmap
Этап T1 — surface model

[ ] Добавить WebSurface / surface_mode в server-side session context.
[ ] Ввести browser и telegram mode.
[ ] Передавать surface в _ctx().
[ ] Не доверять query parameter как auth/security signal.
[ ] Добавить data-surface в <html> или <body>.
Этап T2 — Mini App bootstrap

[ ] Добавить /tg/app.
[ ] Добавить Telegram Web Apps SDK.
[ ] Добавить POST /auth/telegram/bootstrap.
[ ] Валидировать initData на server.
[ ] Создавать Telegram WebView session.
[ ] После success открывать existing home schedule route.
[ ] Добавить graceful fallback вне Telegram.
Этап T3 — общий shell

[ ] Не дублировать schedule/school templates.
[ ] Оставить один base.html.
[ ] Вынести browser/PWA и Telegram-specific UI в include fragments.
[ ] Условно подключать pwa-runtime и telegram-webapp runtime.
[ ] Добавить theme/safe-area adaptation.
[ ] Подключить Telegram BackButton к browser history.
Этап T4 — external browser handoff

[ ] Создать browser_handoff_codes.
[ ] Создать BrowserHandoffService.
[ ] POST /auth/browser-handoff.
[ ] GET /auth/browser/consume.
[ ] Одноразовый code: 60–120 секунд.
[ ] Хранить только hash code.
[ ] Atomically consume.
[ ] Set-Cookie только во внешнем browser.
[ ] 303 redirect на чистый URL.
[ ] Cache-Control: no-store.
[ ] Referrer-Policy: no-referrer.
Этап T5 — bot UX migration

[ ] Заменить token link на Web App button.
[ ] Основная кнопка: «🌐 Открыть расписание».
[ ] В Mini App показать «Открыть в браузере».
[ ] Оставить legacy magic link как support fallback.
[ ] Добавить rate limit на fallback token generation.
[ ] Убрать длинную инструкцию из обычного happy path.
Итог
Да, используйте текущий web UI как основу Mini App.

Правильная продуктовая формула:

text
Одна бизнес-логика.
Один набор server-rendered pages.
Один app-shell.
Два доверенных auth bootstrap flow.
Два shell capability режима.
То есть:

text
Telegram Mini App
= удобный быстрый вход из Telegram.

Browser/PWA
= полноценное standalone-приложение.
А переход между ними должен передавать не текущий видимый token, а короткоживущий одноразовый browser handoff code. Это даст вам удобство Telegram, не потеряв PWA и не породив второй, расходящийся интерфейс.


План реализации по этапам
Этап MA-1 — Data layer (0.5 дня)

text
[ ] migration: browser_handoff_codes
    (code_hash UNIQUE, telegram_user_id, target_path,
     issued_at, expires_at, used_at)
[ ] core/repository/browser_handoff_repository.py
[ ] atomic consume в одном SQL UPDATE ... WHERE used_at IS NULL
[ ] cleanup expired записей (в существующий cleanup_service)
Этап MA-2 — Service layer (1 день)

text
[ ] services/telegram_webauth_service.py
    - validate initData (HMAC-SHA256 по алгоритму Telegram, проверка hash)
    - проверка auth_date freshness (например, ±24h)
    - telegram_user_id → ваш внутренний user (через существующую
      связь user_id в web_auth/user repository)
    - создание WebSessionContext с surface_mode="telegram"
[ ] services/browser_handoff_service.py
    - issue_handoff(telegram_user_id, target_path)
    - consume_handoff(raw_code) → telegram_user_id, target_path
    - allowlist target_path: {"/", "/school", "/school/free-rooms", ...}
    - TTL 60–120 сек, single-use
    - в логи только fingerprint, не raw code
Этап MA-3 — Surface model (0.5 дня)

text
[ ] web/telegram/surface.py: WebSurface dataclass
    (mode, can_install_pwa, can_open_external_browser,
     can_register_service_worker, is_embedded)
[ ] web/telegram/context.py: surface из session
[ ] прокинуть surface в _ctx() всех routes
    (в вашем случае — через web_sessions_service или deps)
[ ] в base.html:
    - {% if surface.can_register_service_worker %} → app.js / SW
    - {% if surface.mode == "telegram" %} → telegram-webapp.js
Этап MA-4 — Mini App routes + templates (1 день)

text
[ ] web/routes/telegram_app.py:
    GET  /tg/app            — entry, редирект на / после bootstrap
    POST /tg/bootstrap      — принимает initData, валидирует, создаёт session
    POST /tg/browser-handoff — выдаёт external_url с одноразовым code
    GET  /tg/browser/consume — consume → browser cookie → 303 на чистый URL
[ ] web/templates/tg/app.html — экран «Открыть в браузере» + CTA
[ ] Cache-Control: no-store, Referrer-Policy: no-referrer на consume
[ ] после bootstrap НЕ создавать PWA service worker
Этап MA-5 — Telegram JS adapter (0.5 дня)

text
[ ] web/static/js/telegram-webapp.js
    - ready(), expand(), theme params
    - BackButton ↔ history.back()
    - openLink() только по user click
[ ] bump_pwa_version.py прогон
Этап MA-6 — Bot integration (0.5 дня)

text
[ ] bot/handlers/web_link.py:
    - кнопка WebApp: https://test.domen.xyz/tg/app
      (тип keyboard button web_app, а не url)
    - убрать длинную инструкцию из happy path
    - оставить legacy token link как /webfallback
[ ] главное меню (⚙️ Настройки → 🌐 Веб-версия):
    заменить на Web App кнопку
[ ] в уведомлениях об изменениях (notifications/dispatcher):
    добавить inline кнопку "Открыть" → /tg/app
      — это ваш главный сценарий "быстрый просмотр из уведомления"
Этап MA-7 — Тесты и приёмка (1 день)

text
[ ] test_telegram_init_data: валидная/невалидная подпись, старый auth_date
[ ] test_browser_handoff: повторное использование code → 404/410
[ ] test_tg_routes: bootstrap без initData, consume expired
[ ] ручная проверка: iPhone ТГ → Mini App → «Открыть в браузере» → PWA install
[ ] проверить, что legacy token flow не сломан
Итого реалистично 4–5 рабочих дней.





## TODO PWA Push Notifications — не приоритет до стабилизации Mini App и PWA adoption.

Telegram остаётся основным и обязательным каналом уведомлений
об изменениях расписания.

PWA Web Push — будущая opt-in функция для пользователей,
установивших приложение на Home Screen.

Не заменять Telegram PWA Push-уведомлениями.
Не включать PWA Push по умолчанию.
Не показывать permission prompt автоматически.
Не отправлять одинаковые уведомления в Telegram и PWA без
явной user preference.

[ ] Сейчас: Telegram-only notification delivery.
[ ] Подготовить NotificationChannel enum.
[ ] Подготовить user notification preferences.
[ ] Реализовать Mini App + browser handoff.
[ ] Довести PWA installation flow.
[ ] Измерить долю установивших PWA пользователей.
[ ] Только затем: opt-in Web Push MVP.
[ ] Добавить web_push_subscriptions.
[ ] Добавить VAPID.
[ ] Добавить push + notificationclick в worker.
[ ] Добавить unsubscribe и invalid subscription cleanup.
[ ] Добавить Telegram/PWA deduplication policy.

PWA Push: оценка 5–7 рабочих дней (production),
из них ~1.5 дня — реальная iOS-отладка.

Приоритет: после Mini App/browser handoff
и стабилизации PWA install flow.







Phase Web Sessions — управление доступом и устройствами

Цель
Пользователь понимает:
- есть ли у него active web sessions;
- на каких устройствах он авторизован;
- как выйти с current device;
- как отозвать lost/old device;
- как немедленно закрыть web access в случае угрозы.

Принцип
Не добавлять в users поля вроде:
web_connected = true
web_enabled = true
web_last_login = ...

Это будет duplicate state и почти гарантированно станет stale.

Источником истины должна оставаться existing таблица:
web_sessions

Активной считается session, для которой:

text
revoked_at IS NULL
AND idle_expires_at > now
AND absolute_expires_at > now
Поэтому правильно говорить пользователю не:

text
«Веб-версия сейчас подключена».
а:

text
«Активные веб-сеансы: 2».
или:

text
«Нет активных веб-сеансов».
Слово «подключена» может создать ложное впечатление, что browser прямо сейчас online. Session может быть valid, но browser давно закрыт.

Этап 1: Logout current device
Цель
Добавить в web UI простой и всегда доступный выход:

text
Выйти с этого устройства
Existing backend уже готов:

text
POST /api/v1/auth/logout
Он:

text
отзывает current session;
удаляет cookie;
публикует SessionRevoked;
закрывает SSE best effort;
app.js очищает Cache Storage.
То есть backend/service/repository менять не нужно.

UI location
Не добавлять logout в bottom navigation. Там должны оставаться primary sections:

text
Сегодня;
Неделя;
Школа;
Допы;
Семья.
Logout — account/security action, не навигационный раздел.

Лучшее место:

text
Header menu → Настройки / Аккаунт → Выйти с этого устройства.
Пока account screen не сделан, допустим temporary вариант:

text
Семья → нижний security section → Выйти с этого устройства.
Но окончательное расположение лучше сделать в отдельном account/settings area.

Acceptance criteria
text
Пользователь нажимает «Выйти с этого устройства».
→ получает confirm dialog.
→ POST /api/v1/auth/logout.
→ current cookie удаляется.
→ current SSE stream закрывается.
→ PWA cache очищается.
→ browser попадает на /auth.
→ protected URLs больше не открываются.
→ другие устройства остаются авторизованными.
Этап 2: Active devices screen
Цель
Сделать web screen:

text
Настройки → Устройства
Existing API уже есть:

text
GET /api/v1/sessions
POST /api/v1/sessions/{session_id}/revoke
POST /api/v1/auth/logout-all
И existing service/repository already support:

text
list_devices();
revoke_session_by_id();
revoke_all_sessions();
UI composition
Пример:

text
Устройства

Текущее устройство
Safari · iPhone
Активно: сегодня, 20:14
[Текущее устройство]

Другие устройства

Chrome · macOS
Активно: вчера, 18:42
[Завершить сеанс]

Safari · iPad
Активно: 28.09, 09:11
[Завершить сеанс]

[Выйти на всех устройствах]
Не нужно показывать пользователю:

text
session_hash;
raw token;
IP address;
internal session_id;
user_id;
family_id;
CSRF token.
session_id можно использовать только внутри hx-post route URL.

Required UI states
text
Нет active sessions
→ «Активных веб-сеансов нет».

Только current session
→ показать current device;
→ не обязательно отображать action revoke current отдельно,
  потому что есть «Выйти с этого устройства».

Several sessions
→ показать current и other devices.

Unknown user agent
→ «Неизвестное устройство».

Revoke failure
→ спокойная error message;
→ не показывать internal details.
Confirmation rules
Для одного чужого device:

text
Завершить сеанс на этом устройстве?
Для logout-all:

text
Выйти на всех устройствах?

Будет завершён доступ к веб-версии
на всех устройствах, включая текущее.
После logout-all user должен получить:

text
/auth
и зайти снова через Telegram magic link.

Этап 3: Bot indicator
Цель
Добавить в Telegram-bot спокойную индикацию состояния web sessions.

Не нужно выводить её на main screen и не нужно spamming notifications.

Лучшее место:

text
Настройки → Веб-версия
или в existing settings page рядом с button:

text
🌐 Веб-версия
Активных сеансов: 2
Тексты

Session count	Текст
0	🌐 Веб-версия: нет активных сеансов
1	🌐 Веб-версия: 1 активный сеанс
2+	🌐 Веб-версия: N активных сеансов
Не писать:

text
«Веб-версия подключена».
Потому что session valid не означает, что browser сейчас открыт.

Правильная архитектура
Не давать bot handler прямой доступ к raw SQL / WebAuthRepository.

Добавить service-level method:

python
async def get_active_session_count(
    self,
    *,
    user_id: int,
) -> int:
В WebSessionsService:

python
async def get_active_session_count(
    self,
    *,
    user_id: int,
) -> int:
    rows = await self.repo.get_active_sessions_for_user(
        user_id=user_id,
        now_utc=self._now_str(),
    )
    return len(rows)
Позже, если понадобится performance optimization, можно добавить dedicated SQL:

sql
SELECT COUNT(*)
FROM web_sessions
WHERE user_id = ?
  AND revoked_at IS NULL
  AND idle_expires_at > ?
  AND absolute_expires_at > ?
Но сейчас reuse current repository method достаточно: sessions per user обычно единицы.

Что не делать на первом шаге
Не добавлять в Telegram-bot:

text
полные user-agent strings;
список устройств;
session IDs;
IP;
last_seen точное время;
кнопку logout current browser session;
automatic alerts «кто-то открыл веб».
Это усложнит UX и может создавать лишнюю тревожность.

Первый bot UX должен быть только informative:

text
Веб-версия: 2 активных сеанса.
Этап 4: Emergency revoke из Telegram
Это полезная future security feature, но делать её после web devices screen.

Сценарий:

text
Пользователь потерял телефон или ноутбук.
→ открывает Telegram-bot.
→ Настройки → Веб-версия.
→ «Завершить все веб-сеансы».
→ confirmation.
→ все web sessions revoked.
Почему не сразу
Для bot-triggered revoke нужно корректно решить integration с SSE event bus.

Current web route делает:

python
await sessions.revoke_all_sessions(
    user_id=context.user_id,
)

await bus.publish(
    SessionRevoked(
        user_id=context.user_id,
    )
)
Bot handler тоже может вызвать:

python
web_sessions_service.revoke_all_sessions(
    user_id=message.from_user.id,
)
Но затем нужно ещё best-effort закрыть active SSE streams пользователя, иначе existing browser tabs смогут жить до следующей session revalidation/reconnect.

План:

text
1. Bot вызывает WebSessionsService.revoke_all_sessions().
2. Bot публикует SessionRevoked(user_id).
3. SSEConnectionManager закрывает web streams user-а.
4. Browser reconnect получает 401.
5. User попадает на /auth.
Это потребует controlled access bot layer к existing ApplicationEventBus или отдельный neutral WebSessionRevocationService, а не import FastAPI state в bot handler.

Это правильная future refactor boundary.

Этап 5: Security observability
После устройств и logout actions добавьте маленький monitoring layer.

Admin-only events
text
Много invalid magic-link exchange за короткое время.
Много CSRF failures.
Много session revoke attempts.
Необычно много active sessions у одного user.
Cleanup job exception.
Cleanup удалил неожиданно большой объём rows.
Не нужно логировать:

text
raw magic tokens;
raw session cookies;
CSRF tokens;
full session hashes;
full user-agent, если он содержит лишние данные.
Для logs достаточно:

text
user_id;
session_id;
operation;
result;
timestamp;
truncated / normalized user-agent при необходимости.
Приоритеты TODO
text
P0 — уже есть:
✓ Magic-link TTL 5 минут.
✓ One-time consume.
✓ Session idle TTL 90 дней.
✓ Session absolute TTL 365 дней.
✓ Device revoke backend.
✓ Logout current backend.
✓ Logout all backend.
✓ Scheduled cleanup в 04:10.
✓ Cleanup revoked rows через 7 дней.

P1 — следующий UX:
□ Web logout current device.
□ Friendly /auth redirect after logout.
□ Account / settings entry point.

P2 — session security UI:
□ Active devices web screen.
□ Revoke one other device.
□ Logout all devices.
□ Confirmation dialogs.
□ Web integration tests.

P3 — bot visibility:
□ Active web-session count in Telegram settings.
□ Neutral wording «N активных веб-сеансов».
□ No raw device details in bot.

P4 — emergency access control:
□ «Завершить все веб-сеансы» из Telegram.
□ Controlled SessionRevoked event publication.
□ SSE immediate close after bot-side revoke.

P5 — operations:
□ Cleanup result structured logging.
□ Cleanup failure admin alert.
□ Invalid magic-link / CSRF anomaly counters.
□ Optional session lifetime policy review: 90/365 vs 30/180.