# SVG ICON SYSTEM v1
## Полный переход проекта на единую SVG-иконографику

Ты работаешь как senior frontend engineer + UI designer.

Задача:
полностью привести иконографику web/PWA приложения школьного расписания
к единой профессиональной SVG design system.

Функциональность приложения НЕ меняем.

Это исключительно UI polish.

==================================================
1. ГЛАВНАЯ ЦЕЛЬ
==================================================

Сейчас приложение использует много emoji:

📅
🗓️
🏫
🎯
👥
⚙️
✏️
🗑️
🔑
📎
🔔
👁️
➕

Они должны быть заменены на единый SVG icon system.

Цель:

не просто "заменить emoji на SVG",
а создать централизованную iconography system,
которую затем будут использовать ВСЕ страницы проекта.

После внедрения:
- Today;
- Week;
- School;
- Extra;
- Family;
- Settings;
- Schedule;
- Week;
- Family;
- Watched classes;
- Extra classes;
- forms;
- actions;
- navigation;
- statuses

должны использовать одну визуальную систему.

==================================================
2. ICON LIBRARY
==================================================

Использовать:

Lucide Icons.

Не использовать одновременно:
- Lucide + Heroicons;
- Font Awesome;
- Material Icons;
- Bootstrap Icons;
- emoji как основную UI iconography.

Lucide использовать как единственный основной icon source.

Официальная документация:
https://lucide.dev/

Lucide предоставляет SVG icons,
поддерживает настройку color / size / stroke width
и рассчитан на единый визуальный стиль.

==================================================
3. INSTALLATION
==================================================

СНАЧАЛА проверь фактическую frontend-инфраструктуру проекта.

Проверь:
- package.json;
- package-lock.json / npm lockfile;
- pnpm-lock.yaml;
- yarn.lock;
- существующие npm scripts;
- существует ли Vite / Rollup / esbuild / другой bundler;
- как сейчас собирается web/static.

НЕ добавляй новый frontend bundler
только ради иконок.

--------------------------------------------------
Сценарий A
--------------------------------------------------

Если в проекте УЖЕ есть npm build/bundling pipeline:

используй официальный пакет:

npm install lucide

и импортируй только необходимые icons,
чтобы сохранить tree-shaking.

Не подключать полный Lucide runtime.

--------------------------------------------------
Сценарий B
--------------------------------------------------

Если frontend bundler отсутствует:

НЕ добавляй Vite/Webpack/Rollup только ради icon system.

Используй:

npm install --save-dev lucide-static

как локальный источник SVG assets.

Из пакета взять ТОЛЬКО фактически используемые SVG.

Production НЕ должен загружать весь icon set.

Скопировать выбранные icons в:

web/static/icons/lucide/

или в фактический существующий static assets directory,
если проект использует другую структуру.

После копирования package нужен только
для development/source assets,
а браузер не должен загружать npm package напрямую.

--------------------------------------------------
Важно
--------------------------------------------------

Не использовать CDN.

Не использовать:

https://unpkg.com/...
https://cdn.jsdelivr.net/...
и другие runtime CDN.

Все icons должны быть self-hosted.

Это соответствует текущей CSP/PWA архитектуре проекта.

==================================================
4. СПОСОБ ИНТЕГРАЦИИ
==================================================

Не вставлять SVG вручную хаотично в 20+ templates.

Создать единый reusable icon mechanism.

Предпочтительный вариант для Jinja:

shared icon component / macro.

ПЕРЕД реализацией проверь существующую структуру web/templates
и существующие UI macros/components.

Если уже существует подходящий shared component —
использовать его.

Если его нет, создать:

web/templates/components/ui/icon.html

или аналогичный фактической структуре проекта.

Цель:

в template писать что-то вроде:

{% from "components/ui/icon.html" import icon %}

{{ icon("settings") }}

или эквивалентную idiomatic конструкцию,
подходящую для текущего проекта.

Не создавать отдельный JS runtime icon renderer,
если он не нужен.

Предпочтительно:
server-rendered inline SVG.

==================================================
5. SVG FORMAT
==================================================

Каждая icon должна быть стандартным SVG.

Базовые свойства:

viewBox="0 0 24 24"

Размер управляется CSS,
а не жёстко зашит в SVG.

Предпочтительно:

width="1em"
height="1em"

или CSS-controlled dimensions.

Цвет:

stroke="currentColor"

Не использовать внутри icons
жёстко заданные цвета вроде:

stroke="#123456"

если только icon специально не является multi-color illustration.

Основная система:
outline icons.

Базовый:

fill="none"

stroke-linecap="round"
stroke-linejoin="round"

Начальный stroke-width:
2

Но перед реализацией визуально проверить,
нужен ли 2 или 2.25 для текущей typography/UI density.

Не использовать разные stroke widths
без семантической причины.

==================================================
6. ICON SIZE SYSTEM
==================================================

Зафиксировать базовые размеры.

### Inline small
16px

Для:
- metadata;
- небольших status markers.

### Standard
20px

Для:
- buttons;
- secondary actions;
- inline controls.

### Navigation
24px

Для:
- bottom navigation;
- settings;
- search;
- main controls.

### Large
28–32px

Для:
- empty states;
- prominent contextual actions,
если реально необходимо.

### Giant
не использовать без конкретной UX причины.

Не делать иконки 40–56px
в обычных UI cards только ради decoration.

==================================================
7. ICON COLOR SYSTEM
==================================================

Icons не должны иметь собственную произвольную цветовую систему.

Icon получает color от родительского UI control.

Основные semantic colors:

PRIMARY
→ active navigation / selected / primary action

TEXT SECONDARY
→ inactive icons

TEXT MUTED
→ tertiary information

CHANGED / ORANGE
→ schedule change

EXTRA / PURPLE
→ extra classes

DANGER / RED
→ destructive action

SUCCESS
→ successful/active state, если такой state уже существует

Важно:
цвет не является единственным способом передачи состояния.

==================================================
8. ИКОНОГРАФИКА BOTTOM NAVIGATION
==================================================

Заменить текущие emoji:

📅 Сегодня
🗓️ Неделя
🏫 Школа
🎯 Допы
👥 Семья

на единые Lucide icons.

Предпочтительно использовать семантически подходящие icons,
например после проверки актуального Lucide catalog:

Сегодня:
calendar-days / calendar

Неделя:
calendar-range / calendars

Школа:
school

Допы:
выбрать наиболее семантически подходящую
иконку для extra classes,
например graduation-cap / book-open-check,
но НЕ принимать пример автоматически —
сначала сравнить визуально несколько Lucide icons.

Семья:
users-round / users

Settings:
settings

Правила:
- одинаковый размер;
- одинаковое визуальное положение;
- active icon отличается состоянием, а не другой формой;
- active = primary;
- inactive = secondary;
- label остаётся текстовым.

Bottom navigation не должен зависеть от SVG
для понимания названия section.

==================================================
9. HEADER ICONS
==================================================

Заменить:

⚙️

на:

settings

Header settings icon:
- 24px;
- neutral color;
- proper touch target;
- aria-label="Настройки".

Не увеличивать сам SVG ради размера tap target.

Touch target и icon size — разные вещи.

==================================================
10. DAY NAVIGATION
==================================================

Заменить:

←
→

на:

arrow-left
arrow-right

Для date navigation:

- 24–28px;
- visually strong;
- consistent stroke;
- same icon family.

Не заменять на:
chevron-left/right,
если текущие большие arrows лучше читаются.

Нужно визуально сравнить:
arrow-left/right
vs
chevron-left/right

и выбрать один вариант для всей day navigation system.

==================================================
11. SCHEDULE ACTIONS
==================================================

Проверить и заменить все icon-like controls:

- expand/collapse;
- change details;
- close;
- room/status indicators;
- current lesson indicators;
- changes/history;
- next/previous;
- Today;
- any lesson action.

Suggested semantic mappings:

Close:
x

Expand:
chevron-down

Collapse:
chevron-up

History / changes:
history
или подходящая Lucide icon

Current:
circle-dot
или другой подходящий minimal marker

Refresh/change:
refresh-cw
или replace
если визуально лучше соответствует значению "замена".

ВАЖНО:
не вставлять icons без проверки semantics.

==================================================
12. EXTRA CLASSES
==================================================

Заменить emoji/actions:

✏️
🗑️
🔔
➕

на:

Edit:
pencil

Delete:
trash-2

Reminder:
bell

Add:
plus

FAB:
plus

FAB icon:
24–28px.

FAB icon white / current contrasting foreground,
цвет задаётся кнопкой, а не SVG.

Delete:
danger color.

Edit:
neutral/primary depending on existing button variant.

Не использовать text emoji.

==================================================
13. FAMILY
==================================================

Заменить:

👥
🔑
📎
🗑️
👶
👁️

на подходящие Lucide icons:

Family:
users-round

Permissions:
key-round

Telegram linking:
paperclip / link
или другой semantic icon,
если link визуально понятнее.

Delete:
trash-2

Child:
user-round / baby
после визуальной проверки.

Observer:
eye

Parent/adult:
user-round

ВАЖНО:
Не пытаться буквально копировать emoji meaning.
Главный критерий:
понятность действия в UI.

==================================================
14. WATCHED CLASSES / NOTIFICATIONS
==================================================

Заменить:

🔔
🟢
⚫
и другие decorative indicators,
если они являются UI icons.

Suggested:

Notifications:
bell

Enabled:
bell / bell-ring
или icon + text

Active:
circle-check
или circle-dot

Paused:
circle-pause

Changes:
history / refresh-cw / replace

Delete:
trash-2

Здесь особенно важно не создавать
слишком много разных визуальных status icons.

==================================================
15. SCHOOL
==================================================

Для School hub:

Search:
search

Classes:
school
или library
если подходит семантически.

Teachers:
graduation-cap / user-round
после визуальной проверки.

Rooms:
door-open
или building-2
после визуальной проверки.

Free rooms:
circle-check
или door-open + status indicator.

Не использовать green circle emoji:

🟢

как единственный indicator.

==================================================
16. SETTINGS
==================================================

Settings screens должны перейти
на тот же icon language.

Использовать:

settings
chevron-right
shield
monitor-smartphone
log-out
bell
key-round
eye
etc.

Но НЕ вводить icon на каждую строку,
если существующий settings component
визуально лучше работает без него.

Иконки — функциональные,
не decorative noise.

==================================================
17. BUTTON ICONS
==================================================

Создать единые правила:

### Icon + text

Иконка:
16–20px

Text:
primary.

Gap:
6–8px.

### Icon-only button

SVG:
20–24px.

Button:
minimum 44x44px touch target.

Обязательно:
aria-label.

### Destructive icon button

Например:

trash-2

Не использовать только красную иконку
без accessible name.

==================================================
18. ICON + TEXT ALIGNMENT
==================================================

Проверить vertical alignment.

Icons должны:

- сидеть по visual center строки;
- не "прыгать" относительно текста;
- не менять baseline;
- не создавать неожиданных extra line-height.

Рекомендуемый layout:

display: inline-flex
align-items: center

а для button:

display: inline-flex
align-items: center
justify-content: center

==================================================
19. ACCESSIBILITY
==================================================

Критически важно.

### Decorative icon

Если icon только визуально дублирует text:

aria-hidden="true"

Например:

[иконка] Настройки

Если "Настройки" уже присутствует,
SVG не должен читать дополнительное имя.

### Icon-only control

Обязательно:

aria-label.

Например:

<button aria-label="Открыть настройки">
    SVG
</button>

Для:
- previous;
- next;
- close;
- edit;
- delete;
- add;
- settings.

### Не использовать title
как единственный accessibility mechanism.

==================================================
20. NO EMOJI LEFTOVER
==================================================

После migration выполнить поиск по проекту.

Проверить emoji в:

- templates;
- static HTML fragments;
- JS-generated UI;
- error messages;
- buttons;
- navigation;
- forms.

Но НЕ удалять emoji из:
- пользовательского текста;
- lesson subject names;
- Telegram-generated content;
- данных, поступающих из backend,
если emoji являются частью реальных пользовательских данных.

Заменять только UI icons.

==================================================
21. EMOJI EXCEPTIONS
==================================================

Можно оставить emoji только там,
где они являются частью продукта/data,
а не UI icon.

Например:
название кружка может содержать emoji,
если пользователь его сам ввёл.

Но:

"🎯 Допы"

как UI navigation icon
должно перейти в SVG.

==================================================
22. CENTRAL ICON API
==================================================

Нужен единый способ вызова icons.

Примеры допустимой концепции:

icon("settings")
icon("arrow-left")
icon("trash-2")

API должен поддерживать минимум:

name
size/class
aria-hidden
aria-label

Пример концептуально:

{{ icon(
    "settings",
    class="icon icon--header",
    label="Настройки"
) }}

Но адаптируй API
к фактической Jinja architecture проекта.

Не создавать сложный abstraction
ради нескольких строк.

==================================================
23. ICON CSS
==================================================

Создать или использовать существующий
central icon CSS.

Например:

.icon {
    width: 1em;
    height: 1em;
    flex: 0 0 auto;
    display: inline-block;
}

.icon--sm { ... }
.icon--md { ... }
.icon--lg { ... }

Не задавать width/height
в каждом template вручную.

Не использовать inline style
для каждого icon.

==================================================
24. SVG OPTIMIZATION
==================================================

Каждая icon должна быть:

- минимальной;
- без editor metadata;
- без unnecessary XML comments;
- без inline styles;
- без unnecessary IDs;
- без embedded raster;
- без gradients;
- без filters,
если icon standard Lucide.

Не менять path data вручную без необходимости.

Не использовать Illustrator-exported oversized SVG.

==================================================
25. DESIGN RULE
==================================================

Иконки не должны визуально конкурировать
с основной typography.

В этом приложении:

Typography > content
Icons > navigation/action
Color > semantic state

Icon не должен становиться
главным визуальным элементом,
если он не является primary action.

==================================================
26. BOTTOM NAV — ОСОБЫЕ ПРАВИЛА
==================================================

Bottom navigation icon:
20–24px

Label:
14–16px

Active:
primary color

Inactive:
secondary color

Active icon может быть filled/stronger,
если Lucide-style equivalent существует,
но не смешивать filled icon family
с outline без необходимости.

Не использовать разные визуальные веса
для пяти navigation items.

Все five icons должны ощущаться
как один set.

==================================================
27. SCHEDULE ROOM BADGES
==================================================

Не вставлять SVG icon рядом с каждым room,
если это не помогает UX.

Кабинет уже представлен badge.

Например:

[ 230 ]

не должен становиться:

[ 🚪 230 ]

без необходимости.

SVG icons использовать только там,
где icon добавляет semantic value.

==================================================
28. LESSON STATUS ICONS
==================================================

Для:

normal
current
changed
added
cancelled
extra

не создавать шесть больших icons
внутри каждой карточки.

Статус по-прежнему кодируется:

- цветом;
- border/accent;
- typography;
- текстом,
а icon используется только если он реально улучшает recognition.

Особенно:
changed/cancelled должны оставаться читаемыми
без reliance on icon/color.

==================================================
29. DO NOT OVER-ICONIZE
==================================================

Очень важно.

Не превращать UI в:

[icon] Subject
[icon] Teacher
[icon] Room
[icon] Group
[icon] Time

Расписание должно оставаться text-first.

SVG icons нужны в:
- navigation;
- actions;
- system controls;
- meaningful status indicators.

Не использовать icon перед каждым полем
только ради декоративности.

==================================================
30. VISUAL STYLE
==================================================

Общий стиль:

- clean;
- modern;
- mobile-first;
- restrained;
- consistent;
- friendly;
- not corporate-heavy.

Иконки должны подходить
к уже существующему:

- dark typography;
- blue primary;
- orange changes;
- purple extra;
- light surfaces;
- rounded cards.

Не делать icons слишком thin.

Не делать icons filled cartoon-like.

Не использовать emoji-style SVG.

==================================================
31. ПЕРЕД РЕАЛИЗАЦИЕЙ
==================================================

Сначала проанализируй текущий проект.

Дай список:

CURRENT UI ICONS:
...

TARGET LUCIDE ICONS:
...

AFFECTED FILES:
...

Новые файлы:
...

Изменяемые:
...

Не меняй функциональность.

==================================================
32. ICON INVENTORY
==================================================

Создай итоговый inventory.

Минимально покрыть:

### Navigation
- today
- week
- school
- extra
- family
- settings
- previous
- next
- chevron-right
- chevron-down
- chevron-up
- close

### Actions
- add
- edit
- delete
- search
- save
- cancel
- confirm
- logout
- link
- copy
- back

### Family
- family
- child
- parent
- observer
- permissions
- telegram-link

### Schedule
- changed
- history
- current
- cancelled
- added
- extra
- room
- teacher
- group
- calendar

### Notifications
- bell
- bell-ring
- pause
- play/enable

### School
- school
- teacher
- class
- room
- free room

### Settings
- settings
- security
- devices
- tracking
- account
- logout

Не обязательно использовать все inventory icons,
если фактический UI их не использует.

==================================================
33. ICON NAMING
==================================================

Нейминг внутри проекта должен быть стабильным.

Например:

schedule
calendar-days

week
calendar-range

school
school

settings
settings

previous
arrow-left

next
arrow-right

add
plus

delete
trash-2

edit
pencil

close
x

search
search

Не создавать свои имена:
icon1
icon_blue
icon2_new
schedule-arrow-final

==================================================
34. NO DUPLICATES
==================================================

Одна семантическая задача = одна icon.

Не создавать:
previous-arrow
back-arrow
left-arrow-small
arrow-prev
prev-day-icon

если это одна и та же семантика.

Использовать:
arrow-left

И варьировать только:
- size;
- color;
- surrounding control.

==================================================
35. ICON SOURCE
==================================================

Для каждого выбранного Lucide icon
зафиксировать его официальное имя.

Не копировать произвольные SVG из Google Images,
Figma community,
неизвестных sites или icon packs.

Если нужной icon нет в Lucide:
сначала проверить близкую семантическую icon.

Не рисовать custom SVG
до тех пор, пока не доказано,
что Lucide не покрывает задачу.

==================================================
36. LICENSE / ATTRIBUTION
==================================================

Учитывать лицензию Lucide.

Lucide распространяется под ISC license.

Если в проекте есть third-party licenses / NOTICE:
добавить соответствующую attribution/license entry
в существующий механизм проекта,
не создавая отдельный механизм только ради icon set.

==================================================
37. PERFORMANCE
==================================================

Не подключать всю Lucide collection.

Использовать только icons,
которые реально нужны UI.

Не делать network request на каждую icon.

Иконки должны быть local/self-hosted.

Не использовать runtime CDN.

==================================================
38. CSP / PWA
==================================================

Не нарушать текущую CSP.

Не добавлять:
unsafe-inline script
unsafe-eval
external icon CDN.

SVG должны быть совместимы
с текущим self-hosted PWA.

Service Worker не требуется менять
только ради icon migration,
если icons уже находятся в существующем static assets path.

Если PWA static caching автоматически покрывает
новую icons directory —
использовать существующий механизм.

Не создавать новый caching system.

==================================================
39. RESPONSIVE
==================================================

SVG должны корректно работать:

- iPhone Safari;
- iOS installed PWA;
- Android Chrome;
- Android installed PWA;
- desktop.

Не завязывать размеры на device-specific hacks.

==================================================
40. REDUCED MOTION
==================================================

Icons сами по себе не должны иметь обязательную animation.

Если для какого-либо icon существовала animation:
по умолчанию НЕ добавлять её.

Не добавлять rotating/spinning/pulsing icons,
если это не уже существующий system state.

==================================================
41. VISUAL QA
==================================================

После migration проверить все screenshots/scenarios:

Today
Week
School
Extra
Family
Settings
Watched classes
Schedule changes
Teacher
Room
School search
Extra forms

Особенно:

Bottom navigation
Header
Day arrows
Today button
FAB
Edit/Delete
Family actions
Settings chevrons.

==================================================
42. ПРОВЕРКА НА КОНСИСТЕНТНОСТЬ
==================================================

Проверить:

- одинаковый stroke;
- одинаковые optical sizes;
- одинаковое vertical alignment;
- одинаковый icon/text gap;
- одинаковый active color;
- одинаковый inactive color;
- одинаковый touch target;
- одинаковое поведение icon-only buttons.

==================================================
43. НЕ ТРОГАТЬ
==================================================

Не изменять:

- backend;
- services;
- repository;
- database;
- auth;
- session;
- security;
- schedule business logic;
- navigation semantics;
- URLs;
- HTMX behavior;
- swipe;
- DayPager;
- PWA service worker logic;
- notification pipeline.

Иконографика — isolated visual refactor.

==================================================
44. РЕЗУЛЬТАТ
==================================================

После реализации приложение должно визуально перейти:

FROM:

emoji-based UI

TO:

single Lucide-based SVG icon system

Пример:

FROM:

📅 Сегодня

TO:

[calendar icon] Сегодня

FROM:

⚙️

TO:

[settings icon]

FROM:

←

TO:

[arrow-left SVG]

FROM:

✏️ / 🗑️

TO:

[pencil SVG] / [trash-2 SVG]

==================================================
45. ФОРМАТ ОТЧЁТА GEMINI
==================================================

После анализа выдай:

### 1. Current icon audit
полный список найденных UI emoji/icons.

### 2. Icon mapping
таблица:

| Current | Lucide | Usage |
|---------|--------|-------|

### 3. Files to change
полный список.

### 4. Installation
точная команда,
исходя из фактической frontend infrastructure.

### 5. Implementation
готовый код.

Для каждого файла:

FILE:
path

WHAT CHANGES:
...

EXACT LOCATION:
...

OLD:
полный реальный фрагмент

NEW:
полный replacement

Если новый файл:
дать полный файл целиком.

Никаких:
...
rest unchanged
placeholder
pseudo-code
invented path

### 6. Final icon inventory

### 7. Manual visual QA checklist

### 8. Search leftovers
что осталось найти после migration.

==================================================
46. ОСОБЕННО ВАЖНО
==================================================

НЕ делай icon migration только в Bottom Navigation.

Нужно пройти ПО ВСЕМУ ПРОЕКТУ.

Особенно проверить:
- templates;
- fragments;
- forms;
- buttons;
- cards;
- settings;
- family;
- school;
- extra classes;
- schedule changes;
- navigation;
- error states;
- empty states.

Но НЕ менять реальные пользовательские emoji-данные.

==================================================
47. КРИТЕРИЙ ГОТОВНОСТИ
==================================================

Готово только когда:

✓ основной UI больше не использует emoji как icon system;
✓ все основные UI icons идут из Lucide;
✓ нет второй icon library;
✓ нет CDN;
✓ icons self-hosted;
✓ icon rendering централизован;
✓ размеры стандартизированы;
✓ stroke стандартизирован;
✓ colors наследуются через currentColor;
✓ icon-only controls имеют aria-label;
✓ decorative icons aria-hidden;
✓ touch targets не уменьшены;
✓ bottom navigation единообразна;
✓ header единообразен;
✓ Schedule / Week / School / Extra / Family / Settings
   используют одну iconography;
✓ функциональность не изменилась;
✓ URL/HTMX/backend не затронуты;
✓ визуально UI стал спокойнее и единообразнее.

==================================================
48. ГЛАВНЫЙ DESIGN PRINCIPLE
==================================================

Иконки должны сделать интерфейс:
чище,
спокойнее,
консистентнее,
современнее.

НЕ:
более пёстрым,
более декоративным,
более "технологичным".

Основная визуальная иерархия приложения остаётся:

CONTENT
>
TYPOGRAPHY
>
STATUS
>
ICON