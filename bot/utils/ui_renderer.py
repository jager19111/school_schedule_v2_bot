# bot/utils/ui_renderer.py — ЧАСТЬ 1 из 2
#
# ЭТАП 6 (рендер). Изменения:
#
# 1. Даты в местном времени: format_dt() + set_date_formatter().
#    main.py один раз вызывает UIRenderer.set_date_formatter(
#    time_service.format_base) — и все рендеры показывают
#    "10.09.2026 19:10" вместо "2026-09-10 12:10:46+00:00".
#    Затронуто: 5 инвайт-рендеров + render_nika_source_health.
#
# 2. Аудит человекочитаемых данных: 4 рендера получали сырые
#    NIKA class_id ("016") вместо имён — добавлены параметры
#    class_name/group_name (см. ЧАСТЬ 2 и патч хендлеров).
#
# 3. render_morning_summary: экранирование child_name/class_id/
#    полей уроков (имя с "<" ломало HTML и доставку сводки).
#
# 4. Удалён мёртвый код: if False:-блок со старой утренней сводкой
#    и render_family_code_prompt (был помечен "удалить").
#
# 5. Исправлен копипаст-докstring render_notifications_menu.
#
# СКЛЕЙКА: содержимое ЧАСТИ 2 дописать в конец этого файла.

from html import escape
from datetime import datetime, timedelta, timezone, date
from typing import Callable, Optional

from services.help_service import HelpPageDTO
from core.models.dto import (ClassListDTO, FamilyCreatedDTO, AdminStatsDTO, DayScheduleDTO, ExtraClassListDTO,
                             WeekSummaryDTO, FullWeekScheduleDTO, UserProfileDTO, FamilyMemberDTO,
                             MorningSummaryDTO, ChangeReminderDTO, LessonReminderDTO, ProfileResetImpactDTO, FamilyInviteDTO, 
                            ScheduleWatchTargetDTO, StudentProfileDTO, ParentStudentNotificationSettingsDTO,
                            AdultStudentExtraClassesPermissionDTO, StudentTelegramSettingsDTO, NikaSourceHealthDTO,  
                            StudentProfileViewModel, WatchTargetViewModel, ExtraClassViewModel, FamilyMemberViewModel, StudentTelegramSettingsViewModel,
                            ParentStudentNotificationSettingsViewModel
)

# Этап 6: форматтер дат. Устанавливается один раз в main.py:
#   UIRenderer.set_date_formatter(time_service.format_base)
# Без установки format_dt() деградирует до str(value) — бот не падает.
_DATE_FORMATTER: Optional[Callable] = None


class UIRenderer:

    @staticmethod
    def set_date_formatter(formatter: Callable) -> None:
        """
        Подключает TimeService.format_base как форматтер дат.

        Вызывается один раз в main() после создания TimeService.
        """
        global _DATE_FORMATTER
        _DATE_FORMATTER = formatter

    @staticmethod
    def format_dt(value) -> str:
        """
        aware-UTC datetime / ISO-строка -> 'DD.MM.YYYY HH:MM'
        в таймзоне школы. None -> '—'.

        Понимает и datetime, и строку (аннотации DTO местами
        устарели: после Strict Time Governance *_at-поля приходят
        из репозитория как aware-UTC datetime).
        """
        if value is None:
            return "—"
        if _DATE_FORMATTER is not None:
            formatted = _DATE_FORMATTER(value)
            if formatted is not None:
                return str(formatted)
        return str(value)

    @staticmethod
    def escape_html(value: object | None, fallback: str = "—") -> str:
        """
        Экранирует динамические значения перед подстановкой в Telegram HTML.

        Статические строки с HTML-разметкой не передаются в этот метод.
        """
        if value is None:
            return fallback
        value_str = str(value).strip()
        if not value_str:
            return fallback
        return escape(value_str)

#-------РЕНДЕРЫ РЕГИСТРАЦИИ-------------
    @staticmethod
    def _render_registration_help_hint() -> str:
        """
        Единая короткая подсказка после успешной регистрации.

        Не перегружает onboarding длинной справкой, но указывает,
        где пользователь сможет узнать подробности.
        """
        return (
            "ℹ️ <b>Подробнее:</b> ⚙️ Настройки → ℹ️ Справка\n"
            "или команда /help."
        )

    @staticmethod
    def _render_registration_capabilities(
        *,
        role: str,
        is_family_admin: bool = False,
    ) -> str:
        """
        Возвращает краткий список возможностей по роли.

        Подробности находятся в интерактивной справке,
        поэтому здесь только onboarding-ориентированные пункты.
        """
        if role == "child":
            return (
                "Теперь доступны:\n"
                "• расписание на день и неделю;\n"
                "• дополнительные занятия и напоминания;\n"
                "• уведомления о заменах и отменах."
            )
        if role == "parent":
            if is_family_admin:
                return (
                    "Теперь доступны:\n"
                    "• управление профилями детей;\n"
                    "• приглашения родителей и наблюдателей;\n"
                    "• расписание и дополнительные занятия детей;\n"
                    "• настройка прав взрослых."
                )
            return (
                "Теперь доступны:\n"
                "• расписание доступных детей;\n"
                "• дополнительные занятия, если есть право управления;\n"
                "• уведомления по детям;\n"
                "• личные отслеживаемые классы."
            )
        if role == "observer":
            return (
                "Теперь доступны:\n"
                "• просмотр расписания доступных детей;\n"
                "• личные уведомления;\n"
                "• личные отслеживаемые классы."
            )
        if role == "teacher":
            return (
                "Теперь доступны:\n"
                "• личное расписание на день и неделю;\n"
                "• поиск расписания классов и учителей;\n"
                "• личные настройки уведомлений."
            )
        return (
            "Теперь можно пользоваться основными возможностями "
            "бота расписания."
        )

    @staticmethod
    def render_registration_success(
        *,
        name: str | None,
        role: str,
        title: str,
        intro: str | None = None,
        is_family_admin: bool = False,
        additional_block: str | None = None,
        next_step: str | None = None,
    ) -> str:
        """
        Общий renderer успешного завершения регистрации.

        Все role-specific success pages должны использовать его,
        чтобы сохранялся одинаковый стиль onboarding.
        """
        safe_name = UIRenderer.escape_html(
            name,
            fallback="",
        )
        safe_title = UIRenderer.escape_html(
            title,
            fallback="Регистрация завершена",
        )
        lines = [
            f"✅ <b>{safe_title}</b>",
            "",
        ]
        if safe_name:
            lines.append(
                f"👋 Привет, <b>{safe_name}</b>!"
            )
            lines.append("")
        if intro:
            lines.append(intro)
            lines.append("")
        if additional_block:
            lines.append(additional_block)
            lines.append("")
        lines.append(
            UIRenderer._render_registration_capabilities(
                role=role,
                is_family_admin=is_family_admin,
            )
        )
        lines.append("")
        lines.append(
            UIRenderer._render_registration_help_hint()
        )
        if next_step:
            lines.append("")
            lines.append(next_step)
        return "\n".join(lines)
 
    @staticmethod
    def render_already_registered(name: str | None) -> str:
        # ЭКРАНИРОВАНИЕ
        safe_name = UIRenderer.escape_html(name, "")
        greeting = f", {safe_name}" if safe_name else ""
        return (
            f"👋 С возвращением{greeting}!\n\n"
            f"Вы уже зарегистрированы. Воспользуйтесь меню ниже:"
        )

    @staticmethod
    def render_final_success(
        name: str | None,
    ) -> str:
        """
        Успешная регистрация самостоятельного child profile
        либо child после вступления в семью.
        """
        return UIRenderer.render_registration_success(
            name=name,
            role="child",
            title="Регистрация завершена",
            next_step=(
                "⬇️ Начните с кнопки "
                "«📅 Моё расписание»."
            ),
        )

    @staticmethod
    def render_success_join(
        *,
        name: str | None,
        role: str,
    ) -> str:
        role_title = {
            "parent": "Вы присоединились к семье",
            "observer": "Вы присоединились к семье",
            "child": "Вы присоединились к семье",
        }.get(
            role,
            "Регистрация завершена",
        )
        return UIRenderer.render_registration_success(
            name=name,
            role=role,
            title=role_title,
            next_step=(
                "⬇️ Начните с кнопки "
                "«📅 Моё расписание»."
            ),
        )

    @staticmethod
    def render_family_created(
        dto: FamilyCreatedDTO,
        name: str | None,
    ) -> str:
        """
        Успешное создание семьи её первым parent/admin.
        """
        safe_code = UIRenderer.escape_html(
            dto.family_code,
            fallback="—",
        )
        additional_block = (
            f"🔑 <b>Код семьи:</b> <code>{safe_code}</code>\n\n"
            "Передайте код только тем, кому доверяете.\n\n"
            "🛡 <b>Рекомендуем:</b> приглашайте новых участников "
            "персональными ссылками через раздел «Семья». "
            "Такая ссылка безопаснее, действует ограниченное время "
            "и заранее определяет роль участника."
        )
        return UIRenderer.render_registration_success(
            name=name,
            role="parent",
            title="Семья создана",
            is_family_admin=True,
            additional_block=additional_block,
            next_step=(
                "⬇️ Откройте «⚙️ Настройки» → «👨‍👩‍👧 Семья», "
                "чтобы добавить ребёнка или создать приглашение."
            ),
        )

#-------РЕНДЕР СПРАВКИ -------------
    @staticmethod
    def render_help_page(
        dto: HelpPageDTO,
    ) -> str:
        """
        Короткая справка для Telegram.

        Полная версия доступна по public_help_url,
        если ссылка задана в config.
        """
        section = dto.section
        if section == "child":
            return (
                "🧒 <b>Справка для ученика</b>\n\n"
                "📅 <b>Моё расписание</b>\n"
                "Показывает уроки на выбранный день, краткую неделю "
                "или подробное расписание на неделю. "
                "В расписании учитываются группа, замены и отмены.\n\n"
                "🎨 <b>Доп. занятия</b>\n"
                "Добавляйте кружки, секции, репетиторов и другие "
                "внеурочные занятия. Они показываются вместе "
                "со школьным расписанием и могут напоминать о себе.\n\n"
                "⚙️ <b>Настройки</b>\n"
                "Здесь можно изменить класс и группу, настроить "
                "уведомления и время утренней сводки.\n\n"
                "🔔 <b>Уведомления</b>\n"
                "Бот может присылать утреннее расписание, напоминания "
                "перед уроками и дополнительными занятиями, а также "
                "сообщения об отменах и заменах.\n\n"
            )
        if section == "parent":
            return (
                "👨‍👩‍👧 <b>Справка для родителя</b>\n\n"
                "📅 <b>Расписание детей</b>\n"
                "В разделе «Моё расписание» выберите нужного ребёнка "
                "и откройте расписание на день или неделю. "
                "Если детей несколько, между ними можно переключаться.\n\n"
                "🎓 <b>Мои отслеживаемые классы</b>\n"
                "Добавляйте классы и группы, за расписанием которых "
                "хотите следить. Для них можно вручную открыть "
                "расписание и получать уведомления об изменениях.\n\n"
                "👨‍👩‍👧 <b>Семья</b>\n"
                "Создавайте виртуальный профиль ребёнка, если у него "
                "пока нет Telegram или телефона. "
                "Приглашайте родителей и наблюдателей, а также "
                "создавайте персональные приглашения для привязки Telegram "
                "к уже созданному профилю ребёнка.\n\n"
                "🎨 <b>Дополнительные занятия</b>\n"
                "Добавляйте и редактируйте кружки ребёнка, "
                "если у вас есть соответствующее право.\n\n"
                "👥 <b>Права взрослых</b>\n"
                "Администратор семьи имеет полный доступ к профилю "
                "детей. Он может выдавать другим родителям "
                "и наблюдателям право редактировать дополнительные "
                "занятия конкретного ребёнка.\n\n"
                "🔔 <b>Уведомления по детям</b>\n"
                "Для каждого ребёнка можно отдельно включить "
                "или выключить утренние сводки, напоминания перед "
                "уроками, уведомления об изменениях расписания "
                "и напоминания о дополнительных занятиях.\n\n"
                "⚙️ <b>Собственные уведомления</b>\n"
                "Ваши личные настройки уведомлений действуют "
                "для всех доступных вам детей. Если личный тип "
                "уведомлений выключен, сообщения этого типа "
                "не будут приходить ни по одному ребёнку."
            )
        if section == "observer":
            return (
                "👁 <b>Справка для наблюдателя</b>\n\n"
                "Вы можете просматривать расписание детей, "
                "которые доступны вам в семье.\n\n"
                "📅 Открывайте расписание на день или неделю.\n"
                "🔔 Настраивайте собственные уведомления.\n"
                "🎓 Добавляйте личные отслеживаемые классы.\n\n"
                "По умолчанию наблюдатель не может изменять "
                "дополнительные занятия ребёнка. Это право может "
                "выдать администратор семьи."
            )
        if section == "teacher":
            return (
                "👩‍🏫 <b>Справка для учителя</b>\n\n"
                "📅 <b>Моё расписание</b>\n"
                "Показывает ваше расписание на выбранный день "
                "или неделю.\n\n"
                "🔍 <b>Поиск по школе</b>\n"
                "Позволяет посмотреть расписание классов и учителей.\n\n"
                "⚙️ <b>Настройки</b>\n"
                "Здесь можно изменить привязанный профиль учителя "
                "и настроить личные уведомления."
            )
        if section == "family":
            return (
                "👨‍👩‍👧 <b>Семья и приглашения</b>\n\n"
                "Создает семью первый подключившийся родитель, он автоматически становится администратором семьи\n"
                "Администратор семьи может:\n"
                "• добавлять учеников без Telegram;\n"
                "• создавать персональное приглашение для ребёнка;\n"
                "• приглашать родителей и наблюдателей по персональной ссылке или передав код семьи (небезопасно);\n"
                "• отслеживать и отменять выданные приглашения.\n"
                "• назначать права на дополнительные занятия.\n\n"
                "📱 <b>Привязать Telegram</b>\n"
                "Используйте, если виртуальный профиль ребёнка уже создан "
                "в семье и нужно привязать к нему Telegram Вашего ребенка.\n\n"
                "📨 <b>Пригласить участника</b>\n"
                "Используйте, если новый участник должен "
                "вступить в семью как ребенок, родитель или наблюдатель."
            )
        if section == "notifications":
            return (
                "🔔 <b>Уведомления</b>\n\n"
                "Бот может присылать:\n"
                "• утреннюю сводку расписания в заданное время;\n"
                "• напоминания перед уроками;\n"
                "• напоминания о дополнительных занятиях;\n"
                "• уведомления об отменах и заменах.\n\n"
                "Время утренней сводки и другие настройки "
                "находятся в разделе «Настройки»."
            )
        if section == "extras":
            return (
                "🎨 <b>Дополнительные занятия</b>\n\n"
                "Дополнительные занятия — это кружки, секции, "
                "репетиторы и другие внеурочные события.\n\n"
                "Для каждого занятия можно указать:\n"
                "• день недели;\n"
                "• время начала и окончания;\n"
                "• название;\n"
                "• место;\n"
                "• время напоминания.\n\n"
                "Занятия принадлежат профилю ученика, а не "
                "конкретному Telegram-аккаунту. Поэтому они "
                "сохраняются при привязке Telegram к семейной группе."
            )
        if section == "privacy":
            return (
                "🔐 <b>Данные и приватность</b>\n\n"
                "Бот хранит только данные, нужные для работы:\n"
                "• Telegram user ID;\n"
                "• выбранную роль;\n"
                "• класс/группу или роль учителя;\n"
                "• семейные связи и настройки доступа;\n"
                "• дополнительные занятия;\n"
                "• настройки уведомлений.\n\n"
                "Расписание школы загружается из официального "
                "источника и хранится в локальном кеше для "
                "работы при временной недоступности сайта школы.\n\n"
                "Для удаления или сброса профиля используйте "
                "раздел «Настройки»."
            )
        if section == "support":
            return (
                "💬 <b>Поддержка и обратная связь</b>\n\n"
                "Если вы нашли ошибку, хотите предложить улучшение "
                "или нуждаетесь в помощи с регистрацией или Вам нужен рабочий доступ к Telegram — напишите автору.\n\n"
                "❤️ Если бот оказался полезным, его можно поддержать "
                "добровольной благодарностью. Это необязательно, "
                "но помогает развивать проект."
            )
        role_hint = {
            "child": "🧒 Вы используете бот расписания как ученик.",
            "parent": "👨‍👩‍👧 Вы используете бот расписания как родитель.",
            "observer": "👁 Вы используете бот расписания как наблюдатель.",
            "teacher": "👩‍🏫 Вы используете бот расписания как учитель.",
        }.get(
            dto.role,
            "👋 Начните с команды /start, чтобы выбрать роль.",
        )
        return (
            "ℹ️ <b>Справка по боту расписания</b>\n\n"
            f"{role_hint}\n\n"
            "Bot помогает смотреть школьное расписание, "
            "учитывать замены, управлять дополнительными занятиями "
            "и получать напоминания.\n\n"
            "Выберите интересующий раздел ниже."
        )

    @staticmethod
    def render_nika_source_health(
        dto: NikaSourceHealthDTO,
    ) -> str:
        """
        Рендерит admin-only диагностику NIKA source/cache.

        Этап 6: таймстемпы проверки/изменения/ошибки — через
        format_dt() в местном времени (раньше сырой UTC со смещением).
        """
        status_headers = {
            "healthy": (
                "🟢 <b>NIKA source: работает</b>",
                "Последняя проверка прошла успешно.",
            ),
            "source_error_cache_available": (
                "🟡 <b>NIKA source: недоступен</b>",
                "Bot использует последнее сохранённое расписание.",
            ),
            "source_error_cache_empty": (
                "🔴 <b>NIKA source: недоступен</b>",
                "Локальное расписание ещё не загружено.",
            ),
            "source_healthy_cache_empty": (
                "🟠 <b>NIKA source: cache пуст</b>",
                "Источник доступен, но расписание пока не сохранено.",
            ),
            "cache_empty": (
                "🔴 <b>NIKA source: нет данных</b>",
                "Источник ещё не был успешно загружен.",
            ),
            "cache_without_source_state": (
                "🟠 <b>NIKA source: неполный state</b>",
                "Cache существует, но metadata источника отсутствует.",
            ),
        }
        header, description = status_headers.get(
            dto.status,
            (
                "⚪ <b>NIKA source: неизвестный статус</b>",
                "Не удалось определить состояние источника.",
            ),
        )
        lines = [
            header,
            "",
            description,
            "",
            "<b>Источник</b>",
            f"JS: <code>{UIRenderer.escape_html(dto.js_filename)}</code>"
            if dto.js_filename
            else "JS: —",
            (
                f"Экспорт: <code>{UIRenderer.escape_html(dto.export_date)}</code> "
                f"<code>{UIRenderer.escape_html(dto.export_time)}</code>"
                if dto.export_date or dto.export_time
                else "Экспорт: —"
            ),
            (
                "Последняя проверка: "
                f"<code>{UIRenderer.escape_html(UIRenderer.format_dt(dto.last_checked_at))}</code>"
                if dto.last_checked_at
                else "Последняя проверка: —"
            ),
            (
                "Последнее изменение: "
                f"<code>{UIRenderer.escape_html(UIRenderer.format_dt(dto.last_changed_at))}</code>"
                if dto.last_changed_at
                else "Последнее изменение: —"
            ),
            "",
            "<b>Локальный cache</b>",
            f"Уроков: <b>{dto.lesson_count}</b>",
            (
                "Coverage: "
                f"<code>{UIRenderer.escape_html(dto.coverage_start_date)}</code> "
                "— "
                f"<code>{UIRenderer.escape_html(dto.coverage_end_date)}</code>"
                if dto.coverage_start_date
                and dto.coverage_end_date
                else "Coverage: —"
            ),
        ]
        if dto.coverage_end_date:
            if dto.coverage_has_future:
                coverage_status = "🟢 Coverage включает будущие дни"
            elif dto.coverage_is_current:
                coverage_status = (
                    "🟡 Coverage заканчивается сегодня"
                )
            else:
                coverage_status = (
                    "🔴 Coverage cache уже устарел"
                )
            lines.append(coverage_status)
        if dto.last_error:
            lines.extend([
                "",
                "<b>Последняя ошибка</b>",
                f"<code>{UIRenderer.escape_html(dto.last_error)}</code>",
                (
                    "Время ошибки: "
                    f"<code>{UIRenderer.escape_html(UIRenderer.format_dt(dto.last_error_at))}</code>"
                    if dto.last_error_at
                    else "Время ошибки: —"
                ),
            ])
        return "\n".join(lines)

    @staticmethod
    def render_role_selection() -> str:
        return "Добро пожаловать! Выберите вашу роль:"

    @staticmethod
    def render_name_prompt() -> str:
        return "Как к вам обращаться? Введите ваше имя (например, Иван или Лиза):"

    @staticmethod
    def render_unregistered_error() -> str:
        return ("⚠️ Регистрация ещё не завершена.\n"
                 "Пожалуйста, сначала пройдите регистрацию (/start) и выберите роль, чтобы продолжить.")

    @staticmethod
    def render_access_denied() -> str:
        return "Эта команда доступна только для вашей текущей роли."

    @staticmethod
    def render_settings_menu() -> str:
        return "⚙️ Меню настроек:"

    @staticmethod
    def render_parent_family_action() -> str:
        return "Вы хотите создать новую семью или присоединиться к уже существующей?"

    @staticmethod
    def render_child_family_action() -> str:
        return (
            "Вы можете присоединиться к семье (чтобы родители помогали "
            "с настройками) или продолжить самостоятельно:\n\n"
            "🛡 <i>Для более безопасного присоединения к семье попроси родителей отправить персональную ссылку-приглашение.</i>"
        )

    # ЭТАП 6: удалён render_family_code_prompt (мёртвый код,
    # был помечен "старый код для примера. удалить").
    # render_family_code_join_intro ниже полностью заменяет его.

    @staticmethod
    def render_family_code_join_intro(
        *,
        intended_role: str,
    ) -> str:
        """
        Вступление в семью через вручную введённый family code.
        """
        return (
            UIRenderer.render_family_join_intro(
                intended_role=intended_role,
                via_code=True,
            )
            + "\n\n"
            + "🔑 <b>Введите код семьи.</b>\n"
            + "Код можно запросить у администратора семьи."
        )

    @staticmethod
    def render_family_invite_join_intro(
        *,
        intended_role: str,
        has_standalone_child_profile: bool = False,
    ) -> str:
        """
        Текст для role-specific join_<token> invite.

        В отличие от family_code flow, следующий шаг здесь —
        ввод имени пользователя.
        """
        return (
            UIRenderer.render_family_join_intro(
                intended_role=intended_role,
                has_standalone_child_profile=has_standalone_child_profile,
                via_code=False,
            )
            + "\n\n"
            + "✍️ <b>Как к вам обращаться?</b>\n"
            + "Введите ваше имя, например: Иван или Лиза."
        )

    @staticmethod
    def render_family_join_intro(
        *,
        intended_role: str,
        has_standalone_child_profile: bool = False,
        via_code: bool = False,
    ) -> str:
        """
        Объясняет последствия вступления в семью.

        via_code=True:
            пользователь вводит family_code вручную.
        via_code=False:
            пользователь открыл role-specific join_<token>.
        """
        role_text = {
            "child": "ребёнка",
            "parent": "родителя",
            "observer": "наблюдателя",
        }.get(
            intended_role,
            "участника семьи",
        )
        source_text = (
            "по коду семьи.\n\n"
            "🛡 <i>Для более безопасного подключения попросите администратора\n"
            "отправить персональную ссылку-приглашение</i>"
        ) if via_code else "по приглашению"
        lines = [
            "👨‍👩‍👧 <b>Вступление в семью</b>",
            "",
            f"Вы присоединяетесь к семье в роли <b>{role_text}</b> "
            f"{source_text}.",
        ]
        if intended_role == "child":
            if has_standalone_child_profile:
                lines.extend([
                    "",
                    "✅ Ваш самостоятельный профиль сохранится.",
                    "✅ Расписание и дополнительные занятия сохранятся в профиле.",
                    "✅ Профиль станет доступен родителям этой семьи.",
                    "",
                    "⚠️ Если родители уже создали отдельный профиль "
                    "именно для вас, попросите у них персональную ссылку "
                    "для привязки Telegram. Не используйте общее "
                    "приглашение, чтобы не создать два профиля одного ребёнка.",
                ])
            else:
                lines.extend([
                    "",
                    "После вступления родители смогут видеть ваше расписание "
                    "и управлять дополнительными занятиями в пределах "
                    "назначенных прав.",
                ])
        elif intended_role == "parent":
            lines.extend([
                "",
                "Вы получите доступ к расписанию учеников, "
                "которых администратор семьи сделал доступными для вас.",
                "",
                "Право изменять дополнительные занятия "
                "определяет администратор семьи.",
            ])
        elif intended_role == "observer":
            lines.extend([
                "",
                "Вы получите доступ к просмотру расписания детей семьи.",
                "",
                "По умолчанию наблюдатель не может изменять "
                "дополнительные занятия и настройки детей.",
            ])
        lines.extend([
            "",
            "✅ <b>Продолжите регистрацию?</b>",
        ])
        return "\n".join(lines)

#=======================
# Дополнительные занятия
#=======================
    DAYS_MAP_SHORT = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}
    FULL_DAYS_MAP = {
        1: "Понедельник", 2: "Вторник", 3: "Среда", 
        4: "Четверг", 5: "Пятница", 6: "Суббота", 7: "Воскресенье"
    }

    @staticmethod
    def render_extra_classes_menu() -> tuple[str, None]:
        return "🎨 <b>Дополнительные занятия</b>\n\nУправление кружками и секциями:", None

    @staticmethod
    def render_extra_class_day() -> tuple[str, None]:
        return "📅 Выберите день недели для занятия:", None

    @staticmethod
    def render_extra_class_edit_day() -> tuple[str, None]:
        return "📅 Выберите новый день недели:", None

    @staticmethod
    def render_extra_class_invalid_reminder() -> tuple[str, None]:
        return "❌ Неверный формат! Введите число (например, 15) или '-'):", None

    @staticmethod
    def render_extra_class_time_start() -> tuple[str, None]:
        return "⏳ Введите время начала занятия:\n<i>💡 Можно вводить 16:00, 16.00, 1600 или 16</i>", None

    @staticmethod
    def render_extra_class_time_end() -> tuple[str, None]:
        return "⏳ Введите время окончания занятия:\n<i>💡 Например: 17:30, 17.30 или 1730</i>", None

    @staticmethod
    def render_extra_class_location() -> tuple[str, None]:
        return "📍 Введите место проведения:\n<i>Например: Спорткомплекс, ул. Ленина 5</i>", None

    @staticmethod
    def render_extra_class_edit_location() -> tuple[str, None]:
        """
        Prompt изменения location существующего дополнительного занятия.
        """
        return (
            "📍 <b>Изменить место занятия</b>\n\n"
            "Введите новое место: кабинет, адрес, площадку или ссылку.\n\n"
            "Чтобы убрать указанное место, отправьте символ: <code>-</code>",   
            None,
        )

    @staticmethod
    def render_extra_class_reminder() -> tuple[str, None]:
        return "⏰ За сколько минут напомнить ребёнку?\n<i>Введите число (например: 45)</i>:", None

    @staticmethod
    def render_extra_class_invalid_time() -> tuple[str, None]:
        return "❌ Не удалось распознать время!\nПожалуйста, введите в формате ЧЧ:ММ (например, 15:30 или 1530).", None

    @staticmethod
    def render_extra_class_title() -> tuple[str, None]:
        return "✏️ Введите название занятия:\n<i>Например: Футбол, Шахматы, Английский</i>", None

    @staticmethod
    def render_extra_class_invalid_range() -> tuple[str, None]:
        return "❌ Ошибка: Время начала не может быть позже или равно времени окончания. Введите корректное время (ЧЧ:ММ):", None

    @staticmethod
    def render_extra_class_success() -> tuple[str, None]:
        return "✅ Доп. занятие сохранено и будет учитываться в расписании.", None

    @staticmethod
    def render_extra_class_error() -> tuple[str, None]:
        return "❌ Произошла ошибка при сохранении.", None

    @staticmethod
    def render_extra_class_locked() -> str:
        return "🔒 Редактирование и удаление занятий запрещено родителем."

    @staticmethod
    def render_extra_no_children() -> tuple[str, None]:
        return "❌ У вас нет привязанных детей. Сначала добавьте ребенка в семью через меню настроек.", None

    @staticmethod
    def render_extra_classes_list(
        view_models: list[ExtraClassViewModel],
        show_id: bool = False,
    ) -> tuple[str, None]:
        """
        Список доп. занятий (Этап 5: принимает ViewModel).
        """
        if not view_models:
            return "📋 <b>Список дополнительных занятий пуст.</b>", None

        text = "📋 <b>Ваши дополнительные занятия:</b>\n\n"
        current_day = -1

        for vm in view_models:
            if vm.day_of_week != current_day:
                current_day = vm.day_of_week
                text += "───────────────\n"
                text += f"📅 <b>{vm.day_of_week_text}</b>\n"
                text += "───────────────\n"

            safe_title = UIRenderer.escape_html(vm.title)
            safe_loc = UIRenderer.escape_html(vm.location)

            if show_id:
                text += (
                    f"ID: <code>{vm.id}</code> | "
                    f"🕐 {vm.time_start}-{vm.time_end}\n"
                )
            else:
                text += f"🕐 {vm.time_start}-{vm.time_end}\n"

            text += f"📝 Занятие: <b>{safe_title}</b>\n"
            text += f"📍 Место: {safe_loc}\n"
            text += f"⏰ Напоминание: {vm.reminder_minutes}мин\n"
            text += " \n"

        return text, None

    @staticmethod
    def render_extra_class_edit_prompt(
        view_models: list[ExtraClassViewModel],
    ) -> tuple[str, None]:
        """
        Prompt редактирования (Этап 5: принимает ViewModel).
        """
        if not view_models:
            return "Список пуст. Изменять нечего.", None
        text, _ = UIRenderer.render_extra_classes_list(
            view_models,
            show_id=True,
        )
        text += "\n✏️ <b>Введите ID занятия для изменения:</b>"
        return text, None


    @staticmethod
    def render_extra_class_edit_field_select() -> tuple[str, None]:
        return "Что именно вы хотите изменить?", None

    @staticmethod
    def render_extra_class_updated() -> tuple[str, None]:
        return "✅ Занятие успешно обновлено.", None

    @staticmethod
    def render_extra_class_delete_prompt(
        view_models: list[ExtraClassViewModel],
    ) -> tuple[str, None]:
        """
        Prompt удаления (Этап 5: принимает ViewModel).
        """
        if not view_models:
            return "Список пуст. Удалять нечего.", None
        text, _ = UIRenderer.render_extra_classes_list(
            view_models,
            show_id=True,
        )
        text += "\n🗑 <b>Введите ID занятия для удаления:</b>"
        return text, None

    @staticmethod
    def render_extra_class_deleted() -> tuple[str, None]:
        return "✅ Занятие успешно удалено.", None

    @staticmethod
    def render_extra_class_not_found() -> tuple[str, None]:
        return "❌ Занятие с таким ID не найдено или вам не принадлежит. Введите правильный ID:", None

    @staticmethod
    def render_extra_student_select() -> tuple[str, None]:
        return "👥 <b>Выберите ребенка</b>\n\nДля кого вы хотите настроить дополнительные занятия?", None


    @staticmethod
    def render_adult_student_extra_classes_permissions(
        vm: StudentProfileViewModel,
        permissions: list[AdultStudentExtraClassesPermissionDTO],
    ) -> str:
        """
        Права взрослых на кружки (Этап 5: ViewModel).
        """
        lines = [
            "👥 <b>Права взрослых</b>",
            "",
            f"👤 Ученик: <b>{UIRenderer.escape_html(vm.name)}</b>",
            f"🎓 Класс: <b>{UIRenderer.escape_html(vm.class_name)}</b>",
            f"👥 {UIRenderer.escape_html(vm.group_name)}",
            vm.telegram_status,
            "",
        ]
        if not permissions:
            lines.extend([
                "В семье нет других взрослых, которым можно "
                "выдать право управления дополнительными занятиями.",
                "",
                "Администратор семьи всегда может управлять "
                "занятиями ученика.",
            ])
            return "\n".join(lines)
        lines.extend([
            "Нажмите на взрослого, чтобы включить или выключить "
            "его право редактировать кружки.",
            "",
        ])
        for permission in permissions:
            role_label = (
                "Родитель"
                if permission.adult_role == "parent"
                else "Наблюдатель"
            )
            status = (
                "ВКЛ 🟢"
                if permission.can_manage_extra_classes
                else "ВЫКЛ 🔴"
            )
            adult_name = UIRenderer.escape_html(
                permission.adult_name,
                fallback="Участник семьи",
            )
            lines.append(
                f"• {role_label}: <b>{adult_name}</b> — {status}"
            )
        lines.extend([
            "",
            "Администратор семьи всегда может управлять "
            "дополнительными занятиями.",
        ])
        return "\n".join(lines)


    @staticmethod
    def render_student_extra_classes_menu(
        vm: StudentProfileViewModel,
    ) -> tuple[str, None]:
        """
        Заголовок меню допзанятий (Этап 5: принимает ViewModel).
        """
        return (
            "🎨 <b>Дополнительные занятия</b>\n\n"
            f"👤 Ученик: <b>{UIRenderer.escape_html(vm.name)}</b>\n"
            f"🎓 Класс: <b>{UIRenderer.escape_html(vm.class_name)}</b>\n"
            f"👥 {UIRenderer.escape_html(vm.group_name)}\n"
            f"{vm.telegram_status}\n\n"
            "Выберите действие:",
            None,
        )


    #-----------------    
    #ИНВАЙТЫ
    #-----------------
    @staticmethod
    def render_family_invite_role_menu() -> str:
        return (
            "📨 <b>Пригласить участника в семью</b>\n\n"
            "Выберите роль приглашённого человека.\n\n"
            "Роль фиксируется в приглашении и не может быть "
            "изменена получателем."
        )

    @staticmethod
    def render_family_invite_created(
        role_label: str,
        expires_at,
    ) -> str:
        # Этап 6: дата — в местном времени через format_dt
        # (раньше сырой "2026-09-10 12:10:46+00:00").
        return (
            "✅ <b>Приглашение создано</b>\n\n"
            f"Роль: <b>{UIRenderer.escape_html(role_label)}</b>\n"
            f"Действует до: <code>{UIRenderer.escape_html(UIRenderer.format_dt(expires_at))}</code>\n"
            "Использований: <b>0 / 1</b>\n\n"
            "Нажмите <b>«📤 Отправить приглашение»</b> "
            "и выберите чат приглашённого человека.\n\n"
            "Приглашённый пользователь откроет ссылку и автоматически "
            "начнёт регистрацию в назначенной роли."
        )

    @staticmethod
    def _family_invite_role_label(
        intended_role: str,
    ) -> str:
        return {
            "child": "👶 Ребёнок с Telegram",
            "parent": "👨‍👩‍👧 Родитель",
            "observer": "👁 Наблюдатель",
        }.get(
            intended_role,
            "Неизвестная роль",
        )

    @staticmethod
    def render_active_family_invites(
        invites: list[FamilyInviteDTO],
    ) -> str:
        """
        Рендерит список active role-specific family invites.

        Этап 6: expires_at — в местном времени через format_dt.
        """
        if not invites:
            return (
                "📬 <b>Активные приглашения</b>\n\n"
                "Сейчас нет активных приглашений."
            )
        lines = [
            "📬 <b>Активные приглашения</b>",
            "",
            "Выберите приглашение для просмотра, повторной "
            "отправки или отзыва.",
            "",
        ]
        for invite in invites:
            role_label = UIRenderer._family_invite_role_label(
                invite.intended_role,
            )
            lines.append(
                f"{role_label}\n"
                f"⏳ До: <code>{UIRenderer.escape_html(UIRenderer.format_dt(invite.expires_at))}</code>\n"
                f"📊 Использований: "
                f"<b>{invite.uses_count} / {invite.max_uses}</b>\n"
            )
        return "\n".join(lines)

    @staticmethod
    def render_family_invite_details(
        invite: FamilyInviteDTO,
    ) -> str:
        """
        Рендерит один active invite.

        Этап 6: created_at/expires_at — в местном времени.
        """
        role_label = UIRenderer._family_invite_role_label(
            invite.intended_role,
        )
        return (
            "📨 <b>Приглашение в семью</b>\n\n"
            f"Роль: <b>{role_label}</b>\n"
            f"Создано: <code>{UIRenderer.escape_html(UIRenderer.format_dt(invite.created_at))}</code>\n"
            f"Действует до: <code>{UIRenderer.escape_html(UIRenderer.format_dt(invite.expires_at))}</code>\n"
            f"Использований: "
            f"<b>{invite.uses_count} / {invite.max_uses}</b>\n\n"
            "Вы можете отправить ссылку приглашённому человеку "
            "или отозвать приглашение."
        )

    @staticmethod
    def render_family_invite_revoke_confirmation(
        invite: FamilyInviteDTO,
    ) -> str:
        role_label = UIRenderer._family_invite_role_label(
            invite.intended_role,
        )
        return (
            "⚠️ <b>Отозвать приглашение?</b>\n\n"
            f"Роль: <b>{role_label}</b>\n"
            f"Действует до: <code>{UIRenderer.escape_html(UIRenderer.format_dt(invite.expires_at))}</code>\n\n"
            "После отзыва ссылка больше не позволит "
            "присоединиться к семье."
        )
    #-----------------                                           
    @staticmethod
    def render_class_selection(dto: ClassListDTO) -> str:
        if not dto.classes:
            return "❌ Расписание еще не загружено. Подождите и нажмите /start."
        return "Выберите ваш класс:"

    @staticmethod
    def render_main_group_selection() -> tuple[str, None]:
        text = (
            "👥 <b>Выберите вашу основную подгруппу</b>\n\n"
            "Укажите группу для базовых предметов (например, английский или математика).\n"
            "<i>(Группы по технологии добавятся в ваше расписание автоматически)</i>"
        )
        return text, None

    @staticmethod
    def render_error_join() -> str:
        return "❌ Код не найден. Проверьте правильность и отправьте его снова, либо нажмите /start."

    @staticmethod
    def render_main_menu() -> str:
        return "Главное меню:"

    @staticmethod
    def render_admin_stats(dto: AdminStatsDTO) -> str:
        text = f"📊 <b>Статистика пользователей (Всего: {dto.total_users}):</b>\n\n"
        for role, count in dto.role_distribution.items():
            text += f"- {role}: {count}\n"
        return text
# Меню
    @staticmethod
    def render_school_search_menu() -> str:
        return "🏫 <b>Поиск по школе</b>\n\nВыберите нужный раздел:"

    @staticmethod
    def render_family_management_menu() -> str:
        return "👨‍👩‍👧 <b>Управление семьей</b>\n\nВыберите ребенка для настройки:"

    @staticmethod
    def render_parent_student_notification_menu() -> str:
        """
        Экран выбора student profile для настройки подписок взрослого.
        """
        return (
            "🔔 <b>Уведомления по ученикам</b>\n\n"
            "Выберите ученика, для которого хотите настроить "
            "свои уведомления.\n\n"
            "Настройки применяются только к вам и не изменяют "
            "личные настройки Telegram-ребёнка."
        )

# --- render_parent_student_notification_settings — ПОЛНАЯ ЗАМЕНА ---

    @staticmethod
    def render_parent_student_notification_settings(
        vm: ParentStudentNotificationSettingsViewModel,
    ) -> str:
        """
        Экран подписок взрослого (Этап 5: ViewModel).
        """
        def status(value: bool) -> str:
            return "ВКЛ 🟢" if value else "ВЫКЛ 🔴"

        return (
            "🔔 <b>Уведомления по ученику</b>\n\n"
            f"👤 Ученик: <b>{UIRenderer.escape_html(vm.student_name)}</b>\n"
            f"🎓 Класс: <b>{UIRenderer.escape_html(vm.class_name)}</b>\n"
            f"👥 {UIRenderer.escape_html(vm.group_name)}\n"
            f"{vm.telegram_status}\n\n"
            "<b>Ваши подписки</b>\n"
            f"🌅 Утренняя сводка: {status(vm.receive_morning_summary)}\n"
            f"⏰ Напоминания об уроках: "
            f"{status(vm.receive_pre_lesson_reminders)}\n"
            f"🔄 Изменения расписания: "
            f"{status(vm.receive_schedule_changes)}\n"
            f"🎨 Доп. занятия: "
            f"{status(vm.receive_extra_class_reminders)}\n\n"
            f"Права на кружки: {vm.manage_status_text}"
        )

    @staticmethod
    def render_student_telegram_summary_time_prompt(
        vm: StudentTelegramSettingsViewModel,
    ) -> str:
        """
        Prompt изменения времени сводки ребёнка (Этап 5: ViewModel).
        """
        return (
            "🌅 <b>Утренняя сводка ребёнка</b>\n\n"
            f"👤 Ученик: <b>{UIRenderer.escape_html(vm.student_name)}</b>\n"
            f"Текущее время: <b>{vm.morning_summary_time}</b>\n\n"
            "Введите новое время в формате:\n"
            "<code>07:00</code>\n\n"
            "Или отключите сводку кнопкой ниже."
        )


    @staticmethod
    def render_student_telegram_settings(
        vm: StudentTelegramSettingsViewModel,
    ) -> str:
        """
        Экран Telegram-настроек ребёнка (Этап 5: ViewModel).
        """
        def status(value: bool) -> str:
            return "ВКЛ 🟢" if value else "ВЫКЛ 🔴"

        return (
            "📱 <b>Настройки Telegram-ребёнка</b>\n\n"
            f"👤 Ученик: <b>{UIRenderer.escape_html(vm.student_name)}</b>\n"
            f"🎓 Класс: <b>{UIRenderer.escape_html(vm.class_name)}</b>\n"
            f"👥 {UIRenderer.escape_html(vm.group_name)}\n\n"
            "<b>Личные настройки ребёнка</b>\n"
            f"🔔 Уведомления: {status(vm.is_notifications_enabled)}\n"
            f"🌅 Утренняя сводка: {vm.morning_summary_time}\n"
            f"⏰ Напоминания об уроках: {vm.pre_lesson_text}\n"
            f"🔄 Изменения расписания: "
            f"{status(vm.receive_schedule_changes)}\n"
            f"🎨 Напоминания о кружках: "
            f"{status(vm.receive_extra_class_reminders)}\n"
            f"✏️ Самостоятельное управление кружками: "
            f"{status(vm.can_manage_own_extra_classes)}\n\n"
            f"🔒 Блокировка настроек ребёнка: <b>{vm.lock_text}</b>"
        )


    @staticmethod
    def render_settings_main(
        user_dto: UserProfileDTO,
        family_code: str | None = None,
        class_name: str | None = None,
        group_names: str | None = None,
    ) -> str:
        role_map = {"parent": "👨‍👩‍👧 Родитель", "child": "👶 Ребёнок", "observer": "👁 Наблюдатель", "teacher": "Учитель",}
        role_name = role_map.get(user_dto.role, "Незарегистрирован")
        # ЭКРАНИРОВАНИЕ
        safe_name = UIRenderer.escape_html(
            user_dto.name,
            fallback="Пользователь",
        )
        if user_dto.role == "teacher":
            family_line = "👨‍🏫 Профиль учителя подключён"
        elif family_code:
            family_line = (
                "👨‍👩‍👧 Код семьи: "
                f"<code>{UIRenderer.escape_html(family_code)}</code>"
            )
        else:
            family_line = "👨‍👩‍👧 Код семьи: Не в семье"
        lines = [
            f"⚙️ <b>Ваши настройки профиля, {safe_name}</b>!",
            "",
            f"👤 Роль: <b>{role_name}</b>",
            family_line,
        ]
        if class_name:
            lines.append(
                f"🎓 Класс: <b>{UIRenderer.escape_html(class_name)}</b>"
            )
        if group_names:
            lines.append(
                f"👥 Группа: <b>{UIRenderer.escape_html(group_names)}</b>"
            )
        lines.extend([
            "",
            "Выберите действие:",
        ])
        return "\n".join(lines)

    @staticmethod
    def render_family_members_menu(
        view_models: list[FamilyMemberViewModel],
    ) -> str:
        """
        Список состава семьи (Этап 5: принимает ViewModel).

        Сортировка уже выполнена билдером.
        """
        text = "👨‍👩‍👧 <b>Ваша семья</b>\n\n"
        for vm in view_models:
            me_flag = " <i>(Вы)</i>" if vm.is_current_user else ""
            safe_name = UIRenderer.escape_html(vm.name, "Неизвестно")

            if vm.role == "child":
                safe_class = UIRenderer.escape_html(vm.class_name)
                text += (
                    f"{vm.role_display}: <b>{safe_name}</b>{me_flag} "
                    f"— {safe_class}\n"
                )
            else:
                text += (
                    f"{vm.role_display}: <b>{safe_name}</b>{me_flag}\n"
                )

        # Подсказка в конце
        if view_models and view_models[0].is_current_user:
            current_role = view_models[0].role
        else:
            current_role = ""

        if current_role == "parent":
            text += "\n⚙️ <i>Выберите ребенка ниже для настройки профиля:</i>"
        else:
            text += "\n🔒 <i>Управление настройками доступно только родителям.</i>"

        return text

    @staticmethod
    def render_family_management_error() -> str:
        return "👨‍👩‍👧 <b>Управление семьей</b>\n\nВы не состоите в семье. Обратитесь к администратору семьи, запросите код и перерегистрируйте учетную запись."
# Сводка
    @staticmethod
    def render_summary_time_prompt(name: str | None = None) -> str:
        # ЭКРАНИРОВАНИЕ
        safe_name = UIRenderer.escape_html(name)
        target = f" для {safe_name}" if name else " вашей"
        return (
            f"⏰ Введите желаемое время{target} утренней сводки (например, 07:00, 7.30 или 715).\n\n"
            f"<i>Вы также можете полностью отключить утреннюю сводку кнопкой ниже.</i>"
        )

    @staticmethod
    def render_invalid_time_format() -> str:
        return "❌ Не удалось распознать время. Пожалуйста, введите в формате ЧЧ:ММ (например, 07:00, 7.30 или 715)."

    # Меню расписаний
    MONTHS_MAP_GEN = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
        7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }

    @staticmethod
    def _format_date_header(date_iso: str) -> str:
        date_obj = datetime.fromisoformat(date_iso)
        day_name = UIRenderer.FULL_DAYS_MAP.get(date_obj.isoweekday(), "")
        return f"━━━━━━━━━━━━━━━━━\n📅 {day_name}, {date_obj.strftime('%d.%m.%Y')}\n━━━━━━━━━━━━━━━━━\n"
# вывод расписания
    @staticmethod
    def render_child_day_schedule(dto: 'DayScheduleDTO', name: str | None = None) -> tuple[str, None]:
        if not dto.lessons:
            return f"{UIRenderer._format_date_header(dto.date_iso)}\n🏖 <b>Занятий нет</b>", None
        main_lessons = [l for l in dto.lessons if not l.get("is_extra")]
        extra_lessons = [l for l in dto.lessons if l.get("is_extra")]
        text = UIRenderer._format_date_header(dto.date_iso)
        if main_lessons:
            text += "\n"  
            grouped_lessons = {}
            for l in main_lessons:
                num = l['lesson_num'] if l['lesson_num'] else 99
                if num not in grouped_lessons:
                    grouped_lessons[num] = []
                grouped_lessons[num].append(l)
            for num, parallel_lessons in grouped_lessons.items():
                first = parallel_lessons[0]
                num_str = f"{first.get('display_num', '•')}." 
                time_str = f"{first['start_time']} - {first['end_time']}"
                if len(parallel_lessons) == 1:
                    l = first
                    icon = "🔄" if l['is_exchange'] else ("🚫" if l['is_cancelled'] else "📚")
                    # ЭКРАНИРОВАНИЕ
                    safe_room = UIRenderer.escape_html(l.get('room_name'), "")
                    room = f" → {safe_room}" if safe_room and safe_room != "—" else ""
                    safe_subj = UIRenderer.escape_html(l.get('subject_name'), "Без предмета")
                    name_str = "ОТМЕНА" if l['is_cancelled'] else safe_subj
                    safe_grp = UIRenderer.escape_html(l.get('group_name'), "")
                    grp_label = f" ({safe_grp})" if l.get('group_id') != "ALL" and safe_grp else ""
                    safe_class = UIRenderer.escape_html(l.get('class_name'), "")
                    class_label = f" [{safe_class}]" if safe_class else ""
                    text += f"{icon} {num_str} {time_str} | {name_str}{grp_label}{class_label}{room}\n"
                else:
                    text += f"📚 {num_str} {time_str}\n"
                    for i, l in enumerate(parallel_lessons):
                        is_last = (i == len(parallel_lessons) - 1)
                        prefix = " └ " if is_last else " ├ "
                        icon = "🔄" if l['is_exchange'] else ("🚫" if l['is_cancelled'] else "")
                        icon_str = f"{icon} " if icon else ""
                        # ЭКРАНИРОВАНИЕ
                        safe_room = UIRenderer.escape_html(l.get('room_name'), "")
                        room = f" → {safe_room}" if safe_room and safe_room != "—" else ""
                        safe_subj = UIRenderer.escape_html(l.get('subject_name'), "Без предмета")
                        name_str = "ОТМЕНА" if l['is_cancelled'] else safe_subj
                        raw_grp = l.get('group_name') or f"Группа {l.get('group_id')}"
                        safe_grp = UIRenderer.escape_html(raw_grp)
                        grp_label = f" ({safe_grp})" if l.get('group_id') != "ALL" else ""
                        safe_class = UIRenderer.escape_html(l.get('class_name'), "")
                        class_label = f" [{safe_class}]" if safe_class else ""
                        text += f"  {prefix}{icon_str}{name_str}{grp_label}{class_label}{room}\n"
        if extra_lessons:
            text += "\n🎨 <b>Доп. занятия</b>\n\n"
            for i, l in enumerate(extra_lessons, 1):
                # ЭКРАНИРОВАНИЕ
                safe_room = UIRenderer.escape_html(l.get('room_name'), "")
                room = f" → {safe_room}" if safe_room and safe_room != "—" else ""
                safe_subj = UIRenderer.escape_html(l.get('subject_name'), "Занятие")
                text += f"🎸 {i}. {l['start_time']} - {l['end_time']} | {safe_subj}{room}\n"
        return text, None

    @staticmethod
    def render_week_summary(dto: 'WeekSummaryDTO') -> tuple[str, None]:
        text = "📆 <b>Расписание на неделю</b>\n\n"
        for day in dto.days:
            date_obj = datetime.fromisoformat(day.date_iso)
            day_short = UIRenderer.DAYS_MAP_SHORT.get(date_obj.isoweekday(), "").upper()
            date_str = date_obj.strftime('%d.%m.%Y')
            extras = f" 🎨{day.extra_count}" if day.extra_count > 0 else ""
            exchanges = f" 🔄{day.exchange_count}" if day.exchange_count > 0 else ""
            text += f"{day_short} {date_str} | {day.lesson_count} уроков{extras}{exchanges}\n"
        text += "\n<i>Нажмите на день для подробностей</i>"
        return text, None

    @staticmethod
    def render_full_week_schedule(dto: 'FullWeekScheduleDTO') -> tuple[str, None]:
        text = "📆 <b>Расписание на всю неделю</b>\n\n"
        for day_dto in dto.days:
            if day_dto.lessons:
                day_text, _ = UIRenderer.render_child_day_schedule(day_dto)
                text += day_text + "\n"
        return text, None   

    # методы для формирования расписания для поиска
    @staticmethod
    def render_search_class_select() -> str:
        return "🎓 <b>Выберите класс для просмотра расписания:</b>"

    @staticmethod
    def render_search_teacher_select() -> str:
        return "👨‍🏫 <b>Выберите преподавателя:</b>"

    @staticmethod
    def render_search_day_select(name: str) -> str:
        # ЭКРАНИРОВАНИЕ
        safe_name = UIRenderer.escape_html(name)
        return f"📅 Выберите день недели для: <b>{safe_name}</b>"

    # Выбор групп
    @staticmethod
    def render_group_selection_multi() -> tuple[str, None]:
        text = (
            "👥 <b>Выберите все ваши подгруппы</b>\n\n"
            "Отметьте группы по всем предметам (например, <i>1 группа</i> для английского "
            "и <i>Группа 3</i> для технологии).\n\n"
            "Когда отметите все нужные, нажмите <b>«💾 Подтвердить выбор»</b>."
        )
        return text, None
# Уведомления
    @staticmethod
    def render_notifications_menu(user_dto: 'UserProfileDTO') -> str:
        """
        Меню настроек уведомлений пользователя.

        Этап 6: исправлен копипаст-докstring (раньше описывал
        напоминание об уроке).
        """
        text = "🔔 <b>Настройки уведомлений</b>\n\n"
        text += f"3️⃣ Утренние сводки: {'✅ Включены' if user_dto.morning_summary_time else '❌ Выключены'}\n"
        if user_dto.morning_summary_time:
            text += f"   ⏰ Время утренней сводки: {user_dto.morning_summary_time}\n"
        return text

    @staticmethod
    def render_lesson_reminder(dto: LessonReminderDTO) -> str:
        # ЭКРАНИРОВАНИЕ
        safe_child = UIRenderer.escape_html(dto.child_name)
        safe_subj = UIRenderer.escape_html(dto.subject_name)
        safe_room = UIRenderer.escape_html(dto.room_name, "—")
        child_line = (
            f"👤 Ребёнок: <b>{safe_child}</b>\n"
            if dto.child_name
            else ""
        )
        if dto.is_extra:
            return (
                "🎨 <b>Скоро дополнительное занятие</b>\n"
                f"{child_line}"
                f"🕐 Начало: <b>{dto.start_time}</b>\n"
                f"📝 Занятие: <b>{safe_subj}</b>\n"
                f"📍 Место: {safe_room}"
            )
        return (
            "⏰ <b>Скоро урок</b>\n"
            f"{child_line}"
            f"🕐 Начало: <b>{dto.start_time}</b>\n"
            f"📚 Предмет: <b>{safe_subj}</b>\n"
            f"🏫 Кабинет: {safe_room}"
        )

    @staticmethod
    def render_change_reminder(dto: ChangeReminderDTO) -> str:
        # ЭКРАНИРОВАНИЕ
        safe_subj = UIRenderer.escape_html(dto.subject_name)
        if dto.watch_target_title:
            target_line = (
                "🎓 Отслеживаемый класс: "
                f"<b>{UIRenderer.escape_html(dto.watch_target_title)}</b>\n"
            )
        elif dto.child_name:
            target_line = (
                "👤 Ребёнок: "
                f"<b>{UIRenderer.escape_html(dto.child_name)}</b>\n"
            )
        else:
            target_line = ""
        if dto.is_cancelled:
            return (
                "🚫 <b>Отмена урока</b>\n"
                f"{target_line}"
                f"📅 Дата: {dto.date}\n"
                f"🔢 Урок: {dto.lesson_num}\n"
                f"📚 Предмет: <b>{safe_subj}</b>"
            )
        return (
            "🔄 <b>Изменение в расписании</b>\n"
            f"{target_line}"
            f"📅 Дата: {dto.date}\n"
            f"🔢 Урок: {dto.lesson_num}\n"
            f"📚 Предмет: <b>{safe_subj}</b>"
        )
    if False:        
        @staticmethod
        def render_morning_summary(dto: MorningSummaryDTO) -> str:
            from datetime import datetime
            date_obj = datetime.fromisoformat(dto.date_iso)
            date_str = date_obj.strftime('%d.%m')
            
            header = f"🌅 <b>Утренняя сводка на сегодня ({date_str})</b>"
            if dto.child_name:
                # ЭКРАНИРОВАНИЕ
                safe_child = UIRenderer.escape_html(dto.child_name)
                safe_class = UIRenderer.escape_html(dto.class_id, "—")
                header += f"\n👤 <b>{safe_child} ({safe_class})</b>"
                
            if not dto.lessons:
                return f"{header}\n\n🏖 Занятий нет.\n"
                
            main_lessons = [l for l in dto.lessons if not l.is_extra]
            extra_lessons = [l for l in dto.lessons if l.is_extra]
            
            text = header + "\n"
            
            if main_lessons:
                text += "\n📚 <b>Основное расписание</b>\n"
                
                grouped = {}
                for l in main_lessons:
                    num = l.lesson_num if l.lesson_num else 99
                    if num not in grouped:
                        grouped[num] = []
                    grouped[num].append(l)
                    
                for num, parallel in grouped.items():
                    first = parallel[0]
                    num_str = f"{first.lesson_num}." if first.lesson_num else "•"
                    time_str = f"{first.start_time} - {first.end_time}"
                    
                    if len(parallel) == 1:
                        l = first
                        icon = "🔄" if l.is_exchange else ("🚫" if l.is_cancelled else "📚")
                        
                        # ЭКРАНИРОВАНИЕ
                        safe_room = UIRenderer.escape_html(l.room_name, "")
                        room = f" → {safe_room}" if l.room_name and l.room_name != "—" else ""
                        
                        safe_subj = UIRenderer.escape_html(l.subject_name or "Без предмета")
                        name_str = "ОТМЕНА" if l.is_cancelled else safe_subj
                        
                        safe_grp = UIRenderer.escape_html(l.group_name, "")
                        grp_label = f" ({safe_grp})" if l.group_name else ""
                        
                        text += f"{icon} {num_str} {time_str} | {name_str}{grp_label}{room}\n"
                    else:
                        text += f"📚 {num_str} {time_str}\n"
                        for i, l in enumerate(parallel):
                            is_last = (i == len(parallel) - 1)
                            prefix = " └ " if is_last else " ├ "
                            
                            icon = "🔄" if l.is_exchange else ("🚫" if l.is_cancelled else "")
                            icon_str = f"{icon} " if icon else ""
                            
                            # ЭКРАНИРОВАНИЕ
                            safe_room = UIRenderer.escape_html(l.room_name, "")
                            room = f" → {safe_room}" if l.room_name and l.room_name != "—" else ""
                            
                            safe_subj = UIRenderer.escape_html(l.subject_name or "Без предмета")
                            name_str = "ОТМЕНА" if l.is_cancelled else safe_subj
                            
                            safe_grp = UIRenderer.escape_html(l.group_name, "")
                            grp_label = f" ({safe_grp})" if l.group_name else ""
                            
                            text += f"  {prefix}{icon_str}{name_str}{grp_label}{room}\n"
                            
            if extra_lessons:
                text += "\n🎨 <b>Доп. занятия</b>\n"
                for i, l in enumerate(extra_lessons, 1):
                    # ЭКРАНИРОВАНИЕ
                    safe_room = UIRenderer.escape_html(l.room_name, "")
                    room = f" → {safe_room}" if l.room_name and l.room_name != "—" else ""
                    
                    safe_subj = UIRenderer.escape_html(l.subject_name)
                    text += f"🎸 {i}. {l.start_time} - {l.end_time} | {safe_subj}{room}\n"
                    
            return text + "\n"

    # Выбрать и доработать метод render_morning_summary, чтобы он корректно отображал сводку для одного ребёнка, учитывая его имя и класс.    
    @staticmethod
    def render_morning_summary(dto: MorningSummaryDTO) -> str:
        """
        Рендерит сводку расписания одного ребёнка.

        Если child_name указан, это часть объединённой сводки взрослого.
        Если child_name отсутствует, это личная сводка ребёнка.

        Этап 6: ВСЕ пользовательские данные экранируются.
        Раньше имя ребёнка/класс с символом "<" ломали HTML —
        и сводка этому пользователю вообще не доставлялась.
        """
        header = "🌅 <b>Расписание на сегодня</b>\n"
        if dto.child_name:
            header += (
                "👤 Ребёнок: "
                f"<b>{UIRenderer.escape_html(dto.child_name)}</b>\n"
            )
        if dto.class_id:
            header += (
                "🎓 Класс: "
                f"{UIRenderer.escape_html(dto.class_id, '—')}\n"
            )
        if not dto.lessons:
            return f"{header}\nНа сегодня занятий нет."
        lines = [header]
        for lesson in dto.lessons:
            safe_subj = UIRenderer.escape_html(lesson.subject_name, "—")
            safe_room = UIRenderer.escape_html(lesson.room_name, "—")
            if lesson.is_extra:
                location = safe_room
                lines.append(
                    f"🎨 {lesson.start_time}–{lesson.end_time} | "
                    f"<b>{safe_subj}</b> "
                    f"({location})"
                )
                continue
            status = ""
            if lesson.is_cancelled:
                status = " 🚫 <b>ОТМЕНА</b>"
            elif lesson.is_exchange:
                status = " 🔄 <b>ЗАМЕНА</b>"
            group_text = (
                f" · {UIRenderer.escape_html(lesson.group_name)}"
                if lesson.group_name
                else ""
            )
            lines.append(
                f"{lesson.lesson_num}. "
                f"{lesson.start_time}–{lesson.end_time} | "
                f"<b>{safe_subj}</b> | "
                f"каб. {safe_room}"
                f"{group_text}"
                f"{status}"
            )
        return "\n".join(lines)
 
# перерегистрация профиля   
    @staticmethod
    def render_profile_reset_confirmation(
        dto: ProfileResetImpactDTO,
    ) -> str:
        """
        Текст подтверждения перерегистрации с учётом роли пользователя.
        """
        if dto.is_family_admin:
            return (
                "⚠️ <b>Расформировать семью и перерегистрироваться?</b>\n\n"
                "Вы являетесь администратором семьи. "
                "Автоматической передачи прав администратора другому "
                "взрослому пока нет.\n\n"
                "При подтверждении:\n"
                f"• семья будет расформирована;\n"
                f"• участников семьи: <b>{dto.family_members_count}</b>;\n"
                f"• детей в семье: <b>{dto.children_count}</b>;\n"
                f"• дополнительных занятий будет удалено: "
                f"<b>{dto.extra_classes_count}</b>;\n"
                "• связи родителей, наблюдателей и детей будут удалены;\n"
                "• virtual-профили детей без Telegram будут удалены;\n"
                "• остальные пользователи останутся в боте, "
                "но будут отвязаны от семьи.\n\n"
                "Telegram-профили реальных детей сохранятся:\n"
                "• дети смогут пользоваться расписанием самостоятельно;\n"
                "• их класс и группа сохранятся;\n"
                "• их дополнительные занятия сохранятся в профиле;\n\n"
                "Это действие нельзя отменить."
            )
        role_name = {
            "child": "ребёнка",
            "parent": "родителя",
            "observer": "наблюдателя",
            "teacher": "учителя",
        }.get(dto.role, "пользователя")
        extra_line = ""
        if dto.role == "child":
            # Обработка ребенка, который состоит в семье
            if dto.family_id is not None:
                extra_line = (
                    "\n\n⚠️ <b>Дополнительные занятия останутся "
                    "в семейном профиле ребёнка.</b>\n"
                    "После отвязки Telegram они будут доступны "
                    "родителям в семье, но не появятся в новом "
                    "самостоятельном профиле."
                )
                return (
                    "⚠️ <b>Отвязать Telegram от семейного профиля?</b>\n\n"
                    "Telegram перестанет быть связан с семьёй.\n"
                    "Вы сможете зарегистрироваться заново как самостоятельный пользователь."
                    f"{extra_line}\n\n"
                    "Продолжить?"
                )
            # Для самостоятельного ребенка (не в семье)
            extra_line = ""
            if dto.extra_classes_count > 0:
                extra_line = (
                    "\n\n"
                    f"🎨 Дополнительные занятия ученика: "
                    f"<b>{dto.extra_classes_count}</b>\n"
                    "Они сохранятся в вашем профиле."
                )
            return (
                "⚠️ <b>Перерегистрироваться?</b>\n\n"
                "Ваш Telegram-профиль будет сброшен.\n"
                "Профиль ученика, школьное расписание и дополнительные "
                "занятия сохранятся в профиле."
                f"{extra_line}\n\n"
                "После сброса потребуется пройти регистрацию заново."
            )
        family_line = (
            "\n• вы будете отвязаны от семьи;"
            if dto.family_id is not None
            else ""
        )
        return (
            f"⚠️ <b>Перерегистрировать профиль {role_name}?</b>\n\n"
            "При подтверждении:\n"
            "• текущие настройки профиля будут сброшены;"
            f"{family_line}"
            f"{extra_line}\n"
            "• вы сможете пройти регистрацию заново.\n\n"
            "Это действие нельзя отменить."
        )

    @staticmethod
    def render_watch_targets_menu(
        view_models: list[WatchTargetViewModel],
    ) -> str:
        """
        Список отслеживаемых классов (Этап 5: принимает ViewModel).
        """
        if not view_models:
            return (
                "🎓 <b>Мои отслеживаемые классы</b>\n\n"
                "Вы пока не добавили ни одного класса.\n\n"
                "Добавьте класс, чтобы самостоятельно смотреть "
                "расписание без привязки к профилю ребёнка."
            )
        lines = [
            "🎓 <b>Мои отслеживаемые классы</b>",
            "",
            "Выберите класс для управления.",
            "",
        ]
        for vm in view_models:
            status = "🟢" if vm.is_enabled else "⚫"
            title = UIRenderer.escape_html(vm.title)
            lines.append(
                f"• {status} <b>{title}</b> — "
                f"{UIRenderer.escape_html(vm.group_name)}, "
                f"{vm.is_enabled_text}"
            )
        return "\n".join(lines)

    @staticmethod
    def render_watch_target_details(
        vm: WatchTargetViewModel,
    ) -> str:
        """
        Карточка отслеживаемого класса (Этап 5: принимает ViewModel).
        """
        title = UIRenderer.escape_html(vm.title)
        return (
            "🎓 <b>Отслеживаемый класс</b>\n\n"
            f"Название: <b>{title}</b>\n"
            f"Класс: <b>{UIRenderer.escape_html(vm.class_name)}</b>\n"
            f"Группа: <b>{UIRenderer.escape_html(vm.group_name)}</b>\n"
            f"Изменения расписания: {vm.changes_notify_text}\n\n"
            f"Статус: {vm.is_enabled_text}\n\n"
            "Этот класс не связан с профилем ребёнка. "
            "Он используется только для вашего самостоятельного "
            "просмотра расписания."
        )

# Виртуальный ученик
    @staticmethod
    def render_family_students(
        view_models: list[StudentProfileViewModel],
    ) -> str:
        """
        Список учеников семьи (Этап 5: принимает ViewModel).

        Все NIKA ID уже расшифрованы билдером в сервисе.
        """
        if not view_models:
            return (
                "🧒 <b>Ученики семьи</b>\n\n"
                "В семье пока нет профилей учеников.\n\n"
                "Администратор семьи может добавить ученика "
                "с Telegram или без Telegram."
            )
        lines = [
            "🧒 <b>Ученики семьи</b>",
            "",
            "Выберите ученика для просмотра профиля.",
            "",
        ]
        for vm in view_models:
            safe_name = UIRenderer.escape_html(vm.name)
            lines.append(
                f"• <b>{safe_name}</b>\n"
                f"  🎓 Класс: {UIRenderer.escape_html(vm.class_name)}\n"
                f"  👥 {UIRenderer.escape_html(vm.group_name)}\n"
                f"  {vm.telegram_status}\n"
            )
        return "\n".join(lines)

    @staticmethod
    def render_student_details(
        vm: StudentProfileViewModel,
    ) -> str:
        """
        Карточка ученика (Этап 5: принимает ViewModel).
        """
        return (
            "🧒 <b>Профиль ученика</b>\n\n"
            f"Имя: <b>{UIRenderer.escape_html(vm.name)}</b>\n"
            f"Класс: <b>{UIRenderer.escape_html(vm.class_name)}</b>\n"
            f"Группа: <b>{UIRenderer.escape_html(vm.group_name)}</b>\n"
            f"{vm.telegram_status}\n\n"
            "Профиль ученика существует независимо от Telegram-аккаунта."
        )


    @staticmethod
    def render_virtual_student_name_prompt() -> str:
        return (
            "🧒 <b>Добавить ученика без Telegram</b>\n\n"
            "Введите имя ребёнка."
        )

    @staticmethod
    def render_virtual_student_delete_confirmation(
        vm: StudentProfileViewModel,
    ) -> str:
        """
        Подтверждение удаления ученика (Этап 5: принимает ViewModel).
        """
        return (
            "⚠️ <b>Удалить ученика?</b>\n\n"
            f"Ученик: <b>{UIRenderer.escape_html(vm.name)}</b>\n"
            f"Класс: <b>{UIRenderer.escape_html(vm.class_name)}</b>\n"
            f"Группа: <b>{UIRenderer.escape_html(vm.group_name)}</b>\n\n"
            "Будут удалены:\n"
            "• профиль ученика;\n"
            "• его дополнительные занятия;\n"
            "• настройки уведомлений взрослых.\n\n"
            "Telegram-профиль отсутствует, поэтому этот ученик "
            "может быть удалён полностью."
        )

    @staticmethod
    def render_student_claim_invite_created(
        vm: StudentProfileViewModel,
        expires_at,
        deep_link: str,
    ) -> str:
        """
        Экран family admin после выпуска claim token
        (Этап 5: ViewModel + expires_at + deep_link).
        """
        return (
            "📱 <b>Ссылка для привязки Telegram</b>\n\n"
            f"👤 Ученик: <b>{UIRenderer.escape_html(vm.name)}</b>\n"
            f"🎓 Класс: <b>{UIRenderer.escape_html(vm.class_name)}</b>\n"
            f"👥 {UIRenderer.escape_html(vm.group_name)}\n\n"
            "Отправьте ссылку ребёнку. После открытия ссылки он "
            "подтвердит профиль, введёт имя и выберет класс/группу.\n\n"
            f"Ссылка действует до: <code>{UIRenderer.escape_html(UIRenderer.format_dt(expires_at))}</code>\n\n"
            f"<code>{UIRenderer.escape_html(deep_link)}</code>"
        )

    @staticmethod
    def render_student_claim_confirmation(
        *,
        student_name: str,
        class_name: str,
        group_name: str,
        has_standalone_profile: bool = False,
    ) -> str:
        safe_name = UIRenderer.escape_html(
            student_name,
            fallback="Ученик",
        )
        safe_class = UIRenderer.escape_html(
            class_name,
            fallback="—",
        )
        group_text = (
            "Весь класс"
            if group_name == "ALL"
            else UIRenderer.escape_html(group_name)
        )
        lines = [
            "🔗 <b>Привязка Telegram</b>",
            "",
            "Telegram будет привязан к семейному профилю:",
            f"🧒 <b>{safe_name}</b>",
            f"🎓 Класс: <b>{safe_class}</b>",
            f"👥 {group_text}",
        ]
        if has_standalone_profile:
            lines.extend([
                "",
                "⚠️ <b>У вас уже есть самостоятельный профиль.</b>",
                "",
                "После подтверждения он будет объединён с семейным профилем.",
                "Все ваши дополнительные занятия сохранятся и будут",
                "перенесены в семейный профиль.",
            ])
        lines.extend([
            "",
            "Продолжить?",
        ])
        return "\n".join(lines)

    @staticmethod
    def render_student_claim_name_prompt() -> str:
        return (
            "✏️ <b>Имя ученика</b>\n\n"
            "Введите имя, которое будет отображаться у ученика "
            "в расписании и настройках семьи."
        )

    @staticmethod
    def render_student_claim_cancelled() -> str:
        return (
            "❌ Привязка Telegram отменена.\n\n"
            "Ссылка не использована. Ребёнок может открыть её "
            "повторно, пока не истечёт срок действия."
        )

    @staticmethod
    def render_student_edit_class_prompt(
        vm: StudentProfileViewModel,
    ) -> str:
        """
        Запрос выбора класса family admin (Этап 5: ViewModel).
        """
        return (
            "🎓 <b>Изменение класса и группы</b>\n\n"
            f"👤 Ученик: <b>{UIRenderer.escape_html(vm.name)}</b>\n"
            f"Текущий класс: <b>{UIRenderer.escape_html(vm.class_name)}</b>\n"
            f"Текущая группа: <b>{UIRenderer.escape_html(vm.group_name)}</b>\n\n"
            "Выберите новый класс."
        )

    @staticmethod
    def render_student_edit_group_prompt(
        vm: StudentProfileViewModel,
        new_class_name: str,
    ) -> str:
        """
        Запрос выбора группы family admin (Этап 5: ViewModel).

        new_class_name — ВЫБРАННЫЙ новый класс (ещё не сохранён),
        передаётся отдельным параметром, не из ViewModel.
        """
        return (
            "👥 <b>Изменение группы</b>\n\n"
            f"👤 Ученик: <b>{UIRenderer.escape_html(vm.name)}</b>\n"
            f"Новый класс: <b>{UIRenderer.escape_html(new_class_name)}</b>\n\n"
            "Выберите группу."
        )



    #----------------------
    #   УЧИТЕЛЬ
    #----------------------
    @staticmethod
    def render_teacher_selection() -> str:
        return (
            "👨‍🏫 <b>Регистрация учителя</b>\n\n"
            "Выберите себя из списка учителей школы.\n\n"
            "Расписание будет привязано к выбранному "
            "профилю учителя."
        )

    @staticmethod
    def render_teacher_registration_success(
        *,
        name: str | None,
        teacher_name: str,
    ) -> str:
        safe_teacher_name = UIRenderer.escape_html(
            teacher_name,
            fallback="Учитель",
        )
        return UIRenderer.render_registration_success(
            name=name,
            role="teacher",
            title="Профиль учителя создан",
            intro=(
                f"Профиль расписания: "
                f"<b>{safe_teacher_name}</b>."
            ),
            next_step=(
                "⬇️ Начните с кнопки "
                "«📅 Моё расписание»."
            ),
        )
#==============================================================
# middlewares
#==============================================================   
    @staticmethod
    def render_system_error() -> str:
        """
        Сообщение о непредвиденной ошибке (HTML, для сообщений).

        Намеренно БЕЗ деталей: traceback в чат — утечка путей,
        SQL и внутренних данных. Полный стек уходит только в лог.
        """
        return (
            "😔 <b>Произошла непредвиденная ошибка</b>\n\n"
            "Мы записали её в журнал и разберёмся.\n"
            "Попробуйте повторить действие ещё раз.\n"
            "Если проблема повторяется — отправьте /start."
        )

    @staticmethod
    def render_system_error_plain() -> str:
        """
        Тот же смысл без HTML-тегов — для callback-алертов
        (callback.answer не поддерживает parse_mode).
        """
        return (
            "😔 Произошла непредвиденная ошибка.\n"
            "Попробуйте повторить действие ещё раз. "
            "Если повторяется — /start."
        )
