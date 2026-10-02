# UI Icon Inventory

This directory contains a curated subset
of Phosphor Icons.

Source:
https://github.com/phosphor-icons/homepage
https://phosphoricons.com

License:
MIT

Version:
2.1.0

## Bottom navigation

- calendar-duotone → Сегодня
- calendar-dots-duotone → Неделя
- building-apartment-duotone → Школа
- palette-duotone → Допы
- users-three-duotone → Семья

## Header

- gear-duotone → Настройки

## Day navigation

- caret-circle-left-duotone → Предыдущий день
- caret-circle-right-duotone → Следующий день
- x-circle-duotone → Закрыть
- caret-down-duotone → Раскрыть
- caret-up-duotone → Свернуть

## Schedule

- clock-counter-clockwise-duotone→ История изменений
- arrows-clockwise-duotone → Замена
- repeat-duotone - ротация/смена позициии урока
- record-duotone → Сейчас
- door-duotone → Кабинет
- door-open-duotone → свободный Кабинет
- chalkboard-teacher-duotone - учитель
## Actions

- plus-circle-duotone → Добавить
- pencil-duotone → Редактировать
- trash-duotone → Удалить
- magnifying-glass-duotone → Поиск

## Family

- users-three-duotone → Семья
- user-circle-duotone → Пользователь
- baby-duotone - ребенок
- user-circle-plus-duotone → добавить пользователя
- user-circle-dashed-duotone → редактировать пользователя
- user-circle-gear-duotone → настройки пользователя
- student-duotone → Ученик
- key-duotone → Права
- link-duotone → Связать
- eye-duotone → Просмотр
- hat-glasses → наблюдатель
## Notifications

- bell-duotone → Уведомления
- bell-ringing-duotone → Уведомления включены
- bell-slash-duotone → Уведомления выключены

## Theme

- sun-dim-duotone - темная/светлая тема

## Others
- star-duotone - избранное
- shield-check-duotone - безопасность
- clock-duotone - время
- question-duotone - справка
- sign-out-duotone - выйти/выключить
- paperclip-duotone - ссылка



ТЗ ДЛЯ GEMINI — PHOSPHOR ICON SYSTEM + ВИЗУАЛЬНАЯ ИНТЕГРАЦИЯ
Ты продолжаешь работу над существующим проектом веб-интерфейса для Telegram-бота школьного расписания.
Это не новый проект. Не переизобретай архитектуру. Не теряй контекст предыдущей работы.
Твоя задача сейчас — интегрировать новый локальный набор Phosphor Icons Duotone в существующий web frontend, заменив старые UI-иконки/emoji там, где это предусмотрено inventory.
0. КОНТЕКСТ ПРОЕКТА — ОБЯЗАТЕЛЬНО СОХРАНИ ПЕРЕД НАЧАЛОМ РАБОТЫ
Проект — web companion / второй frontend поверх уже существующего Telegram-бота.
Основные технологии:
FastAPI
Jinja2
HTMX
vanilla JavaScript
CSS
PWA
SQLite
общий существующий service/repository/business-logic слой
Python asyncio
Telegram bot + FastAPI работают в одном процессе
Web frontend не имеет собственной бизнес-логики расписания и не должен дублировать Telegram-логику.
Архитектурные правила
Нельзя:
добавлять вторую БД;
создавать дублирующие user/student/family сущности;
писать SQL в web routes;
переносить domain/business logic в routes;
создавать новую параллельную систему расписаний;
дублировать существующие сервисы;
менять backend/API только ради иконок;
вводить React;
вводить Vue;
вводить npm только ради icon library;
подключать CDN для иконок;
использовать внешний runtime icon library.
Web должен оставаться:
HTML/Jinja + HTMX + vanilla JS + CSS + локальные SVG.
1. ВИЗУАЛЬНЫЙ КОНТЕКСТ
Функциональность основных экранов уже реализована.
В проекте уже существуют:
Today / расписание дня;
Week;
School;
Extra classes;
Family;
Settings;
tracked classes / отслеживаемые сущности;
teacher/room/class views;
day navigation;
changes;
extra classes;
PWA shell;
SSE/live updates.
Сейчас не нужно добавлять новые функции.
Главная цель этой задачи:
сделать единообразную, современную и цельную систему UI-иконок на основе Phosphor Duotone.
Особенно важно сохранить уже достигнутую геометрию и UX расписания.
Не переделывай layout без необходимости.
Не превращай эту задачу в полный redesign.
2. НОВАЯ ICON SYSTEM
Теперь проект использует:
Phosphor Icons
Версия:
2.1.0
Источник:
https://github.com/phosphor-icons/homepage
https://phosphoricons.com
Лицензия:
MIT
Используется локальный curated subset SVG-иконок.
Основной стиль:
Duotone
3. КРИТИЧЕСКОЕ ПРАВИЛО ПО ФОРМАТУ
Мы не используем:
@phosphor-icons/react
npm
React components
icon font
CDN
external runtime library
<img src="icon.svg">
React-примеры из официальной документации Phosphor не относятся к архитектуре этого проекта.
Не устанавливай npm-пакеты.
Не добавляй package.json только ради иконок.
Не делай runtime dependency на Phosphor.
4. ИСТОЧНИК ИКОНОК
Используй локальные Raw SVG assets, которые уже подготовлены для проекта.
Ожидаемая концепция:
web/
└── static/
    └── icons/
        └── phosphor/

Перед изменением файлов:
Найди фактическое расположение уже добавленного каталога иконок.
Не создавай второй параллельный каталог.
Не копируй иконки заново, если нужные SVG уже существуют.
Используй существующие файлы из curated subset.
Не скачивай случайные дополнительные иконки из интернета.
Если конкретной иконки из inventory нет среди локальных assets — не подменяй её самовольно другой иконкой. Зафиксируй проблему в отчёте.
5. ПОЛНЫЙ INVENTORY
Это текущий утверждённый список.
Bottom navigation
calendar-duotone          → Сегодня
calendar-dots-duotone     → Неделя
building-apartment-duotone → Школа
palette-duotone           → Допы
users-three-duotone       → Семья
Header
gear-duotone → Настройки
Day navigation
caret-circle-left-duotone  → Предыдущий день
caret-circle-right-duotone → Следующий день
x-circle-duotone           → Закрыть
caret-down-duotone         → Раскрыть
caret-up-duotone           → Свернуть
Schedule
clock-counter-clockwise-duotone → История изменений
arrows-clockwise-duotone        → Замена
repeat-duotone                  → Ротация / смена позиции урока
record-duotone                  → Сейчас
door-duotone                    → Кабинет
door-open-duotone               → Свободный кабинет
chalkboard-teacher-duotone      → Учитель
Actions
plus-circle-duotone        → Добавить
pencil-duotone             → Редактировать
trash-duotone              → Удалить
magnifying-glass-duotone   → Поиск
Family
users-three-duotone             → Семья
user-circle-duotone             → Пользователь
baby-duotone                    → Ребёнок
user-circle-plus-duotone        → Добавить пользователя
user-circle-dashed-duotone     → Редактировать пользователя
user-circle-gear-duotone       → Настройки пользователя
student-duotone                 → Ученик
key-duotone                     → Права
link-duotone                    → Связать
eye-duotone                     → Просмотр
hat-glasses                     → Наблюдатель
Notifications
bell-duotone          → Уведомления
bell-ringing-duotone  → Уведомления включены
bell-slash-duotone    → Уведомления выключены
Theme
sun-dim-duotone → Тёмная / светлая тема
Others
star-duotone            → Избранное
shield-check-duotone    → Безопасность
clock-duotone           → Время
question-duotone        → Справка
sign-out-duotone        → Выйти
paperclip-duotone       → Ссылка
6. ГЛАВНОЕ ТЕХНИЧЕСКОЕ ТРЕБОВАНИЕ
Иконки должны рендериться inline SVG, а не как <img>.
Нам необходимо управлять цветом через CSS.
Phosphor SVG использует currentColor, поэтому должна работать схема:
.icon {
    color: var(--icon-color);
}
или:
.icon-primary {
    color: var(--color-primary);
}
Не прописывай конкретные UI-цвета внутрь SVG.
Не перекрашивай SVG вручную под каждый экран.
Не создавай десятки копий одной иконки ради цвета.
7. DUOTONE
Используем нативный внешний вид Phosphor Duotone.
Не нужно сейчас делать систему с двумя независимыми CSS-цветами.
Модель:
currentColor
+
встроенная визуальная opacity/вторичный слой Phosphor Duotone
Цвет задаётся через CSS.
Например:
.icon-primary {
    color: var(--color-primary);
}

.icon-changed {
    color: var(--color-changed);
}

.icon-extra {
    color: var(--color-extra);
}

.icon-danger {
    color: var(--color-danger);
}

.icon-muted {
    color: var(--color-text-muted);
}
8. СОЗДАЙ ЕДИНЫЙ СПОСОБ РЕНДЕРИНГА
Найди существующий механизм Jinja/template helpers/macros.
Если готового icon helper нет — создай один централизованный Jinja macro/helper для SVG.
Цель использования должна быть примерно такой:
{{ icon("calendar-dots-duotone") }}
или аналогично, но выбери форму, которая естественно ложится на уже существующую структуру проекта.
Не дублируй SVG markup в десятках шаблонов.
Не вставляй большие <svg>...</svg> блоки вручную в каждый template.
9. API ICON HELPER
Icon helper должен позволять как минимум:
выбрать icon;
задать CSS class;
задать размер;
сохранить возможность использовать currentColor;
корректно работать с accessibility.
Например концептуально:
{{ icon(
    "calendar-duotone",
    class="nav-icon",
    size=24
) }}
Но сначала изучи существующую архитектуру проекта и не вводи API, который конфликтует с имеющимися Jinja conventions.
10. ACCESSIBILITY
Это важно.
Если иконка находится внутри:
<button>
    ...
</button>
или:
<a href="...">
    ...
</a>
и сама иконка декоративная, она должна быть:
aria-hidden="true"
Accessible name должен находиться у самого control:
<button aria-label="Настройки">
а не только у SVG.
Не добавляй aria-label ко всем декоративным SVG без необходимости.
11. ЗАМЕНА СТАРЫХ ИКОНОК
Найди существующее использование:
emoji;
Unicode arrows;
старых SVG;
старой icon system;
текстовых визуальных символов,
но заменяй только UI-иконки, а не обычный текст.
Например:
⚙️
🔍
➕
✏️
🗑️
🔔
◀
▶
могут быть кандидатами на замену.
Но не надо механически искать каждый emoji в проекте и заменять его.
Особое внимание:
bottom navigation;
header;
day navigation;
schedule actions;
school actions;
family actions;
notifications;
settings.
12. НЕ ЛОМАТЬ UX РАСПИСАНИЯ
Экран расписания — наиболее важный экран проекта.
Не менять:
размеры lesson cards без необходимости;
existing time column;
day navigation behavior;
swipe behavior;
HTMX navigation;
SSE;
current lesson logic;
changes logic;
extra-class logic;
teacher aggregation;
room logic.
Задача icon migration не должна затронуть business logic.
13. ОСОБЕННО ВАЖНО: DAY SWIPE
В проекте уже существует сложная интерактивная навигация дня:
стрелки Previous / Next;
свайп всей рабочей области;
drag-like page transition;
neighbor day preview;
commit примерно после 45vw;
существующий HTMX canonical update.
Эта система ранее уже исправлялась из-за гонок между canonical day content и preloaded neighbor HTML.
НЕ возвращай preload реального соседнего HTML.
Не переделывай DayPager.
Не создавай новую navigation state machine.
Не меняй swipe implementation в рамках этой задачи.
Иконки day navigation должны просто интегрироваться в существующие controls.
14. ЦВЕТОВАЯ СЕМАНТИКА
Сохраняй существующую design-token систему.
Основные семантики:
Primary
Changed → orange
Extra → purple
Danger → red
Muted / metadata → gray
Иконка не должна сама по себе определять семантику.
Семантику задаёт surrounding component/class.
Например:
<span class="icon icon-changed" aria-hidden="true">
а не:
orange SVG file
15. НЕ ПЕРЕДЕЛЫВАЙ ВСЮ CSS-СИСТЕМУ
Сейчас задача:
icon system integration, а не новый дизайн-системный refactor.
Можно добавить:
.icon
.icon--sm
.icon--md
.icon--lg
или более подходящие классы, если это естественно для текущего CSS.
Но не начинай:
массовый rename CSS;
массовый rename templates;
перестройку layout;
перенос всех цветов в новую архитектуру;
переписывание всех компонентов.
Работа должна быть минимально инвазивной.
16. РАЗМЕРЫ ИКОНОК
Сделай единообразную систему размеров.
Ориентировочно:
small UI      ~16px
normal UI     ~20px
navigation    ~22–24px
prominent     ~24–28px
Но сначала посмотри фактическую геометрию существующего интерфейса.
Не делай иконки большими только потому, что Duotone красивые.
Особенно важно сохранить:
высоту bottom navigation;
высоту header;
плотность schedule cells.
17. BOTTOM NAVIGATION
Bottom navigation должна получить полноценную Phosphor-систему.
Не менять:
routing;
active tab logic;
HTMX;
URLs;
layout.
Меняется только визуальное представление иконок.
Active state должен использовать существующую semantic color system.
18. HEADER
Settings icon:
gear-duotone
Интегрировать в существующую кнопку.
Не создавать новую кнопку только ради иконки.
Не менять поведение settings.
19. FAMILY / SCHOOL / ACTIONS
Особенно внимательно посмотри на текущие CRUD controls.
Использовать:
plus-circle
pencil
trash
magnifying-glass
user-circle-plus
user-circle-dashed
user-circle-gear
Но:
не ставить иконку возле каждого слова просто ради красоты.
Иконка должна иметь UI-смысл.
Не создавать визуальный шум.
20. ИКОНКИ РАСПИСАНИЯ
Использовать соответствующие иконки там, где они уже имеют соответствующую смысловую функцию:
История → clock-counter-clockwise
Замена → arrows-clockwise
Ротация → repeat
Сейчас → record
Кабинет → door
Свободный кабинет → door-open
Учитель → chalkboard-teacher
Особенно проверь teacher view.
chalkboard-teacher-duotone должен восприниматься как часть semantic teacher UI, а не случайная decorative icon.
21. ЧТО ЗАПРЕЩЕНО ДЕЛАТЬ
Во время этой задачи запрещено:
добавлять React;
добавлять npm;
добавлять Phosphor runtime package;
подключать CDN;
менять backend business logic;
менять БД;
менять API contracts;
писать SQL;
изменять auth;
изменять permissions;
менять schedule services;
переделывать swipe;
возвращать реальный preload соседнего дня;
делать большой CSS refactor;
заменять функциональные тексты emoji-иконками без необходимости;
создавать собственный новый icon library слой поверх Phosphor без причины.
22. ОБЯЗАТЕЛЬНО СНАЧАЛА ИЗУЧИ REPO
Не начинай сразу редактировать файлы.
Сначала:
найди текущие templates;
найди static assets;
найди существующие icon helpers/macros, если они есть;
найди все текущие emoji/UI symbols;
найди bottom nav;
найди header;
найди day navigation;
найди actions;
найди family/school/settings templates;
пойми текущую CSS-архитектуру.
После этого кратко покажи:
Что найдено
Где находятся текущие иконки
Какой helper уже существует
Какие файлы будут изменены
Как именно будет интегрирован Phosphor
Только после этого приступай к правкам.
23. РАБОТАЙ ИНКРЕМЕНТАЛЬНО
Не переписывай 30 файлов одним махом.
Работай примерно так:
1. icon infrastructure
2. bottom navigation
3. header/day navigation
4. schedule actions
5. school
6. family
7. settings/notifications
8. visual cleanup
9. tests / lint / checks
После каждого крупного этапа проверяй, что проект не сломан.
24. НЕ ИЗОБРЕТАЙ НОВЫЕ PATHS / FILENAMES
Используй реальные существующие пути проекта.
Не пиши:
web/templates/components/icons.html
просто потому, что это красиво выглядит в ТЗ.
Сначала проверь структуру repo.
То же касается:
CSS;
JS;
static;
templates;
macros.
25. ВАЖНО: НЕ ТРОГАЙ docs/UI/
В рабочей ветке ранее существовала отдельная директория:
docs/UI/
Она может содержать мои локальные UI-материалы.
Не удаляй её.
Не изменяй её без прямого указания.
Не добавляй её содержимое в функциональный commit.
26. ПРОВЕРКА РЕЗУЛЬТАТА
После реализации проверь:
Functional
Сегодня работает
Неделя работает
Школа работает
Допы работают
Семья работает
Настройки работают
Day navigation работает
Swipe работает как раньше
HTMX работает
Visual
Проверить минимум:
mobile width
iPhone-like viewport
desktop
light theme
dark theme
active nav
inactive nav
disabled icon
changed state
extra state
danger action
muted metadata
Особенно проверить, что Duotone иконки не выглядят слишком тяжёлыми.
27. VISUAL QA
После внедрения сделай визуальный проход по следующим экранам:
Today
Week
School
Extra classes
Family
Settings
Notifications
Teacher
Room
Changes
Проверяй:
alignment;
baseline;
размеры;
optical balance;
active state;
color;
spacing;
отсутствие визуального шума;
отсутствие разношерстных emoji;
отсутствие старых icon styles.
28. ВАЖНЫЕ ПРИНЦИПЫ ДЛЯ ВСЕЙ РАБОТЫ
Запомни эти правила и не теряй их в следующих сообщениях:
Это существующий production-oriented проект, а не playground.
Мы не ищем повод переписать архитектуру.
Сначала читаем существующий код, потом меняем минимально необходимое.
Не дублируем business logic.
Не меняем рабочую функциональность ради эстетики.
HTML/Jinja + HTMX + vanilla JS + CSS остаются основной архитектурой.
Phosphor используется как локальный набор SVG assets, а не как React/npm dependency.
SVG рендерятся inline.
Цвет контролируется через CSS/currentColor.
Основной визуальный вес — Duotone.
Не возвращаем emoji туда, где уже есть утверждённая иконка.
Не меняем swipe/day navigation.
Не трогаем backend.
Не трогаем БД.
Не добавляем новые зависимости без необходимости.
29. ФОРМАТ РАБОТЫ С КОДОМ
Когда предлагаешь изменение:
сначала указывай точный файл.
Например:
FILE:
web/templates/base.html
Затем укажи:
LOCATION:
...
Если изменение небольшое:
OLD:
...

NEW:
...
Если файл проще заменить полностью:
FULL FILE:
...
Не используй:
...
same as before
...
rest unchanged
...
Не оставляй placeholder вместо рабочего кода.
30. НЕ ДЕЛАЙ COMMIT
Не создавай commit самостоятельно.
В конце предоставь:
Изменённые файлы
Что сделано
Что осталось
Какие проверки выполнены
Есть ли проблемы
31. КОНТРОЛЬНАЯ ТОЧКА ПЕРЕД ЗАВЕРШЕНИЕМ
Перед тем как сказать «готово», проверь:
[ ] Используются только локальные Phosphor SVG
[ ] Нет React
[ ] Нет npm dependency
[ ] Нет CDN
[ ] SVG inline
[ ] currentColor работает
[ ] Accessibility сохранён
[ ] Bottom nav переведён
[ ] Header переведён
[ ] Day navigation переведён
[ ] Schedule actions переведены
[ ] Family actions переведены
[ ] School actions переведены
[ ] Settings/notifications переведены
[ ] Старые emoji UI icons не остались там, где есть утверждённый Phosphor icon
[ ] Swipe не изменён
[ ] HTMX не изменён
[ ] Backend не изменён
[ ] Business logic не изменён
[ ] docs/UI не затронут
[ ] Нет лишних файлов/зависимостей
ФИНАЛЬНОЕ ТРЕБОВАНИЕ
Не теряй контекст проекта между шагами.
Перед каждым новым изменением сверяйся с уже принятыми архитектурными решениями.
Если видишь возможность сделать «красивее», но для этого надо менять функциональность, архитектуру или существующий UX — не делай это самостоятельно.
Если обнаружишь конфликт между текущим кодом и этим ТЗ:
сначала покажи конфликт;
укажи конкретные файлы;
предложи минимальное решение;
не принимай архитектурное решение за пользователя.
Сейчас твоя задача — аккуратно внедрить утверждённую Phosphor Duotone icon system в уже работающий интерфейс, сохранив весь существующий функциональный и UX-контракт проекта.
Начни с аудита repo и текущей icon infrastructure, затем покажи найденную структуру и план изменений.




Icon system: Phosphor Icons, curated local SVG subset, version 2.1.0.
Source format: Raw SVG assets.
Storage: web/static/icons/.
Rendering: inline SVG through a Jinja macro, not <img>, not icon font, not CDN, not runtime icon package.
Default weight: Duotone.
Coloring: SVG uses currentColor; semantic icon colors are controlled exclusively by CSS/design tokens.
Duotone: use Phosphor's native duotone appearance; do not introduce a second independent CSS color unless explicitly required by a future design decision.
Accessibility: decorative icons aria-hidden="true"; actionable controls get accessible label on the button/link, not on the decorative SVG itself.


Usage

Simply import the icons you need, and add them anywhere in your render method. Phosphor supports tree-shaking, so your bundle only includes code for the icons you use.

import { HorseIcon, HeartIcon, CubeIcon } from "@phosphor-icons/react";

const App = () => {
  return (
    <main>
      <HorseIcon />
      <HeartIcon color="#AE2983" weight="fill" size={32} />
      <CubeIcon color="teal" weight="duotone" />
    </main>
  );
};
Import Performance Optimization

When importing icons during development directly from the main module @phosphor-icons/react, some bundlers may eagerly transpile all 9,000+ modules exported by the package. This behavior can drastically increase compilation time. To avoid transpiling all modules, import individual icons from their specific file paths instead:

import { BellSimpleIcon } from "@phosphor-icons/react/dist/csr/BellSimple";
Next.js Specific Optimizations

If you're using Next.js 13+, consider using optimizePackageImports in your next.config.js to have Next.js only load the modules that you are actually using. With this approach, you can use @phosphor-icons/react directly without causing Next.js to compile all its modules:

module.exports = {
  experimental: {
    optimizePackageImports: ["@phosphor-icons/react"],
  },
}
React Server Components and SSR

When using Phosphor Icons in an SSR environment, within a React Server Component, or in any environment that does not permit the use of the Context API (Next.js Server Component, for example), import icons from the /dist/ssr submodule:

import { FishIcon } from "@phosphor-icons/react/ssr";

const MyServerComponent = () => {
  return <FishIcon weight="duotone" />;
};
Note

These variants do not use React Context, and thus cannot inherit styles from an ancestor IconContext.
Props

Icon components accept all props that you can pass to a normal SVG element, including inline style objects, onClick handlers, and more. The main way of styling them will usually be with the following props:

color?: string – Icon stroke/fill color. Can be any CSS color string, including hex, rgb, rgba, hsl, hsla, named colors, or the special currentColor variable.
size?: number | string – Icon height & width. As with standard React elements, this can be a number, or a string with units in px, %, em, rem, pt, cm, mm, in.
weight?: "thin" | "light" | "regular" | "bold" | "fill" | "duotone" – Icon weight/style. Can also be used, for example, to "toggle" an icon's state: a rating component could use Stars with weight="regular" to denote an empty star, and weight="fill" to denote a filled star.
mirrored?: boolean – Flip the icon horizontally. Can be useful in RTL languages where normal icon orientation is not appropriate.
alt?: string – Add accessible alt text to an icon.
Context

Phosphor takes advantage of React Context to make applying a default style to all icons simple. Create an IconContext.Provider at the root of the app (or anywhere above the icons in the tree) and pass in a configuration object with props to be applied by default to all icons:

import { IconContext, HorseIcon, HeartIcon, CubeIcon } from "@phosphor-icons/react";

const App = () => {
  return (
    <IconContext.Provider
      value={{
        color: "limegreen",
        size: 32,
        weight: "bold",
        mirrored: false,
      }}
    >
      <div>
        <HorseIcon /> {/* I'm lime-green, 32px, and bold! */}
        <HeartIcon /> {/* Me too! */}
        <CubeIcon /> {/* Me three :) */}
      </div>
    </IconContext.Provider>
  );
};
You may create multiple Contexts for styling icons differently in separate regions of an application; icons use the nearest Context above them to determine their style.

Note

The context will also pass any provided SVG props down to icon instances, which can be useful E.G. in adding accessible aria-labels, classNames, etc.
Note

React Context is not available in some environments. See React Server Components and SSR for details.
Composability


Components can accept arbitrary SVG elements as children, so long as they are valid children of the <svg> element. This can be used to modify an icon with background layers or shapes, filters, animations, and more. The children will be placed below the normal icon contents.

The following will cause the Cube icon to rotate and pulse:

const RotatingCube = () => {
  return (
    <CubeIcon color="darkorchid" weight="duotone">
      <animate
        attributeName="opacity"
        values="0;1;0"
        dur="4s"
        repeatCount="indefinite"
      ></animate>
      <animateTransform
        attributeName="transform"
        attributeType="XML"
        type="rotate"
        dur="5s"
        from="0 0 0"
        to="360 0 0"
        repeatCount="indefinite"
      ></animateTransform>
    </CubeIcon>
  );
};
Note

The coordinate space of slotted elements is relative to the contents of the icon viewBox, which is 256x256 square. Only valid SVG elements will be rendered.
Imports

You may wish to import all icons at once for use in your project, though depending on your bundler this could prevent tree-shaking and make your app's bundle larger.

import * as Icon from "@phosphor-icons/react";

<Icon.SmileyIcon />
<Icon.FolderIcon weight="thin" />
<Icon.BatteryHalfIcon size="24px" />
For information on using Phosphor Icons in Server Components, see See React Server Components and SSR.

Custom Icons

It is possible to extend Phosphor with your custom icons, taking advantage of the styling and context abstractions used in our library. To create a custom icon, first design your icons on a 256x256 pixel grid, and export them as SVG. For best results, flatten the icon so that you only export assets with path elements. Strip any fill or stroke attributes, as these will be inherited from the wrapper.

Next, create a new React forwardRef component, importing the IconBase component, as well as the Icon and IconWeight types from this library. Define a Map<IconWeight, ReactElement> that maps each icon weight to the contents of each SVG asset, effectively removing the wrapping <svg> element from each. Name your component, and render an <IconBase />, passing all props and the ref, as well as the weights you defined earlier, as JSX props:

import { forwardRef, ReactElement } from "react";
import { Icon, IconBase, IconWeight } from "@phosphor-icons/react";

const weights = new Map<IconWeight, ReactElement>([
  ["thin", <path d="..." />],
  ["light", <path d="..." />],
  ["regular", <path d="..." />],
  ["bold", <path d="..." />],
  ["fill", <path d="..." />],
  [
    "duotone",
    <>
      <path d="..." opacity="0.2" />
      <path d="..." />
    </>,
  ],
]);

const CustomIcon: Icon = forwardRef((props, ref) => (
  <IconBase ref={ref} {...props} weights={weights} />
));

CustomIcon.displayName = "CustomIcon";

export default CustomIcon;