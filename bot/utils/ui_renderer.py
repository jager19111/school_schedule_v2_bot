# bot/utils/ui_renderer.py

from html import escape
from collections import defaultdict
from typing import List, Tuple, Any, Union, Dict
from datetime import datetime, timedelta, timezone, date
from typing import Callable, Optional

from services.help_service import HelpPageDTO
from core.models.dto import (ClassListDTO, AdminStatsDTO, DayScheduleDTO, ExtraClassListDTO,
                             WeekSummaryDTO, FullWeekScheduleDTO, UserProfileDTO, FamilyMemberDTO,
                             MorningSummaryDTO, ChangeReminderDTO, LessonReminderDTO, ProfileResetImpactDTO, FamilyInviteDTO, 
                            ScheduleWatchTargetDTO, StudentProfileDTO, ParentStudentNotificationSettingsDTO,
                            AdultStudentExtraClassesPermissionDTO, StudentTelegramSettingsDTO, NikaSourceHealthDTO, FreeRoomsStatusDTO,  
                            StudentProfileViewModel, WatchTargetViewModel, ExtraClassViewModel, FamilyMemberViewModel, StudentTelegramSettingsViewModel,
                            ParentStudentNotificationSettingsViewModel, DayChangesDetailDTO, LessonDTO, MorningLessonDTO, DailyChangeSummaryDTO
)

from datetime import datetime
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader

# Инициализируем Jinja2 один раз на уровне модуля.
# autoescape=True автоматически экранирует <, >, & (заменяя UIRenderer.escape_html)
template_env = Environment(
    loader=FileSystemLoader('bot/templates'),
    autoescape=True,
    trim_blocks=True,   # Убирает пустые строки после {% ... %}
    lstrip_blocks=True  # Убирает пробелы перед {% ... %}
)

# Этап 6: форматтер дат. Устанавливается один раз в main.py:
#   UIRenderer.set_date_formatter(time_service.format_base)
# Без установки format_dt() деградирует до str(value) — бот не падает.
_DATE_FORMATTER: Optional[Callable] = None

LessonLike = Union[LessonDTO, Dict[str, Any]]

class UIRenderer:

    # ==========================================================
    # Универсальный доступ к полям (LessonDTO | Dict)
    # ==========================================================

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

    @staticmethod
    def _format_short_date(
        date_iso: str,
    ) -> str:
        try:
            date_obj = datetime.fromisoformat(
                date_iso,
            )
        except ValueError:
            return date_iso

        return date_obj.strftime("%d.%m")

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
        name: str | None,
    ) -> str:
        additional_block = (
            "🛡 <b>Приглашайте близких безопасно:</b>\n\n"
            "Настройки → Семья → Приглашения\n\n"
            "Каждое приглашение:\n"
            "• персональное — заранее выбираете роль (родитель, "
            "ребёнок, наблюдатель);\n"
            "• одноразовое — используется один раз;\n"
            "• ограничено по времени — действует 24 часа;\n"
            "• с коротким кодом — можно продиктовать по телефону "
            "или записать на бумажке.\n\n"
            "Отправляйте ссылку в личных сообщениях. "
            "Срок действия можно проверить и отозвать "
            "в любой момент."
        )
        return UIRenderer.render_registration_success(
            name=name,
            role="parent",
            title="Семейная группа создана",
            is_family_admin=True,
            additional_block=additional_block,
            next_step=(
                "⬇️ Откройте «⚙️ Настройки» → «👨‍👩‍👧 Семья» → «Приглашения», "
                "чтобы позвать ребёнка, второго родителя или бабушку-наблюдателя."
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
                "• приглашать родителей и наблюдателей по персональной ссылке или передав короткий индивидуальный код;\n"
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
        return "Вы хотите создать новую семейную группу или присоединиться к уже существующей?"

    @staticmethod
    def render_child_family_action() -> str:
        return (
            "👶 <b>Присоединиться к семье родителей?</b>\n\n"
            "Родители смогут видеть ваше расписание и помогать "
            "с настройками.\n\n"
            "📋 <b>Как присоединиться:</b>\n"
            "1. Попроси у родителей код приглашения (6 символов, "
            "действует 24 часа)\n"
            "2. Нажми «Присоединиться» и введи код\n\n"
            "Или продолжи самостоятельную регистрацию — "
            "присоединиться можно позже через настройки.\n\n"
            "🛡 <i>Родитель может выдать код приглашения "
            "в разделе «Семья» → «Приглашения».</i>"
        )


    @staticmethod
    def render_family_code_join_intro(
        *,
        intended_role: str,
    ) -> str:
        role_text = {
            "child": "ребёнка",
            "parent": "родителя",
            "observer": "наблюдателя",
        }.get(intended_role, "участника семьи")
        return "\n".join([
            "📋 <b>Введите код приглашения</b>",
            "",
            f"Код для роли <b>{role_text}</b> выдаёт администратор семьи "
            "в разделе «Семья» → «Приглашения».",
            "",
            "• 6 символов, буквы и цифры\n"
            "• одноразовый, действует 24 часа\n"
            "• регистр не важен: XR7K2M = xr7k2m",
            "",
            "Не знаете код? Попросите администратора семьи "
            "создать приглашение и продиктовать вам код.",
        ])

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
            "по коду приглашения (6 символов, одноразовый, "
            "действует 24 часа)"
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
            "parent": "🧑‍🧒 Родитель",
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
        
    @staticmethod
    def render_family_transfer_select(
        candidates: List[FamilyMemberDTO],
    ) -> str:
        """
        Экран выбора получателя полномочий.
        """
        lines = [
            "👑 <b>Передача полномочий</b>",
            "",
            "Выберите, кому передать управление семьёй.",
            "Вы останетесь в семье как обычный родитель.",
            "",
            "<b>Родители семьи:</b>",
        ]
        for candidate in candidates:
            lines.append(
                f"• {UIRenderer.escape_html(candidate.name, fallback='Пользователь')}"
            )
        lines.append("")
        lines.append("⚠️ Передача вступает в силу сразу после подтверждения.")
        return "\n".join(lines)

    @staticmethod
    def render_family_transfer_done(
        target_name: str,
    ) -> str:
        """
        Экран успешной передачи полномочий.
        """
        safe_name = UIRenderer.escape_html(target_name, fallback="Пользователь")
        return "\n".join(
            [
                "✅ <b>Полномочия переданы</b>",
                "",
                f"Управление семьёй теперь у <b>{safe_name}</b>.",
                "Вы остаётесь в семье как обычный родитель.",
            ]
        )
        
    @staticmethod
    def render_family_transfer_confirmation(
        target_name: str,
    ) -> str:
        """
        Экран подтверждения передачи полномочий.
        """
        safe_name = UIRenderer.escape_html(target_name, fallback="Пользователь")
        return (
            "⚠️ <b>Подтверждение передачи</b>",
            "",
            f"Управление семьёй перейдёт к <b>{safe_name}</b>.",
            "",
            "Новый администратор сможет приглашать участников",
            "и отзывать приглашения. Вы останетесь в семье",
            "как обычный родитель.",
        ) and "\n".join(
            [
                "⚠️ <b>Подтверждение передачи</b>",
                "",
                f"Управление семьёй перейдёт к <b>{safe_name}</b>.",
                "",
                "Новый администратор сможет приглашать участников",
                "и отзывать приглашения. Вы останетесь в семье",
                "как обычный родитель.",
            ]
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
        return (
            "❌ Код не найден, истёк или уже использован.\n\n"
            "Попросите у администратора семьи свежий код приглашения "
            "(раздел «Семья» → «Приглашения»)."
        )
        
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
        return "🏫 <b>Поиск по школе</b>\n\nВыберите нужный справочник:"

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
        class_name: str | None = None,
        group_names: str | None = None,
        is_family_admin: bool = False,   # <-- новый параметр
    ) -> str:
        role_map = {"parent": "🧑‍🧒 Родитель", "child": "👶 Ребёнок", "observer": "👁 Наблюдатель", "teacher": "Учитель",}
        role_name = role_map.get(user_dto.role, "Незарегистрирован")
        # ЭКРАНИРОВАНИЕ
        safe_name = UIRenderer.escape_html(
            user_dto.name,
            fallback="Пользователь",
        )
        if user_dto.role == "teacher":
            family_line = "👨‍🏫 Профиль учителя подключён"
        elif getattr(user_dto, "family_id", None) is not None:
            if is_family_admin:
                family_line = "👨‍👩‍👧 Администратор семьи"
            else:
                family_line = "👨‍👩‍👧 Вы в семье"
        else:
            family_line = "👨‍👩‍👧 Не в семье"
        lines = [
            f"⚙️ <b>Ваши настройки профиля, {safe_name}</b>!",
            "",
            #f"👤 Роль: <b>{role_name}</b>",
            f"<b>{role_name}</b>",            
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

# меню семьи
    @staticmethod
    def render_family_members_menu(
        member_vms: list['FamilyMemberViewModel'],
        student_vms: list['StudentProfileViewModel'],
    ) -> str:
        """
        Единый список: состав семьи + профили виртуальных учеников.
        """
        # === БЛОК 1: Состав семьи ===
        text = "👨‍👩‍👧 <b>Ваша семья</b>\n\n"
        for vm in member_vms:
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

        text += "\n"

        # === БЛОК 2: Ученики семьи ===
        if not student_vms:
            text += (
                "🧒 <b>Ученики семьи</b>\n\n"
                "В семье пока нет профилей учеников.\n"
                "Администратор семьи может добавить ученика "
                "с Telegram или без Telegram.\n\n"
            )
        else:
            lines = [
                "🧒 <b>Ученики семьи</b>",
                ""
            ]
            for vm in student_vms:
                safe_name = UIRenderer.escape_html(vm.name)
                lines.append(
                    f"• <b>{safe_name}</b>\n"
                    f"  🎓 Класс: {UIRenderer.escape_html(vm.class_name)}\n"
                    f"  👥 {UIRenderer.escape_html(vm.group_name)}\n"
                    f"  {vm.telegram_status}\n"
                )
            text += "\n".join(lines) + "\n\n"

        # === БЛОК 3: Подсказка ===
        if member_vms and member_vms[0].is_current_user:
            current_role = member_vms[0].role
        else:
            current_role = ""

        if current_role == "parent":
            text += "⚙️ <i>Выберите ребенка ниже для настройки профиля:</i>"
        else:
            text += "🔒 <i>Управление настройками доступно только родителям.</i>"

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




   
    # ==========================================================
    # Расписание дня (DayScheduleDTO)
    # ==========================================================
        

    @staticmethod
    def render_day_schedule(
        dto: 'DayScheduleDTO',
        name: str | None = None,
        show_footer: bool = True
    ) -> tuple[str, None]:
        
        # 1. Форматирование даты
        date_obj = datetime.fromisoformat(dto.date_iso)
        day_name = UIRenderer.FULL_DAYS_MAP.get(date_obj.isoweekday(), "")
        formatted_date = f"{day_name.capitalize()}, {date_obj.strftime('%d.%m')}"

        # 2. Группировка слотов по времени (чтобы объединить параллельные подгруппы)
        grouped = defaultdict(list)
        for l in dto.lessons:
            # Прямое обращение к типизированным полям DTO
            grouped[(l.start_time, l.is_extra)].append(l)

        sorted_slots = [
            grouped[k] for k in sorted(
                grouped.keys(), 
                key=lambda k: k[0].zfill(5) if k[0] and k[0] != "—" else "99:99"
            )
        ]

        # 3. Подсчет изменений
        # Полностью избавляемся от getattr, код читается как обычный английский текст
        changes_count = sum(
            l.is_exchange or l.is_cancelled
            for l in dto.lessons if not l.is_extra
        ) if show_footer else 0

        # 4. Рендер шаблона
        template = template_env.get_template('day_schedule.j2')
        text = template.render(
            dto=dto,
            name=name,
            formatted_date=formatted_date,
            slots=sorted_slots,
            changes_count=changes_count,
            is_teacher=(dto.origin == "teacher"),
            is_school_search=(dto.origin == "class")
        )
        
        return text, None
        
        
    # ==========================================================
    # Детализация изменений (LessonDTO)
    # ==========================================================
        
    @staticmethod
    def render_day_changes_detail(
        dto: 'DayChangesDetailDTO',
    ) -> tuple[str, None]:
        """
        Детализация «было → стало» (только LessonDTO).
        С умной группировкой подгрупп в дерево!
        """
        if not dto.lessons:
            return (
                f"🔄 <b>Изменения на {dto.date_iso}</b>\n\n"
                f"Изменений нет.",
                None,
            )

        text = f"🔄 <b>Изменения на {dto.date_iso}</b>\n\n"

        if dto.origin == "teacher":
            text += "<i>Расписание учителя</i>\n\n"

        # 1. Группируем по номеру урока и времени (чтобы склеить подгруппы)
        from collections import defaultdict
        grouped = defaultdict(list)
        for l in dto.lessons:
            key = (l.lesson_num, l.start_time, l.end_time)
            grouped[key].append(l)

        # 2. Сортируем ключи (по номеру урока и времени)
        sorted_keys = sorted(grouped.keys(), key=lambda k: (k[0] or 99, k[1] or "99:99"))

        for key in sorted_keys:
            parallel_lessons = grouped[key]
            
            # --- ИСПРАВЛЕНИЕ: Сортируем параллельные уроки по имени группы ---
            # Это гарантирует, что Группа 1 всегда будет выше Группы 2
            parallel_lessons.sort(key=lambda x: str(x.group_name or ""))

            first = parallel_lessons[0]
            
            num_str = f"{first.display_num or first.lesson_num}."
            time_str = f"{first.start_time} - {first.end_time}"

            # Заголовок блока (если ВСЕ уроки отменены -> ❌, иначе -> 🔄)
            all_cancelled = all(l.is_cancelled for l in parallel_lessons)
            icon = "❌" if all_cancelled else "🔄"

            text += f"{icon} {num_str} {time_str}\n"

            for i, l in enumerate(parallel_lessons):
                safe_orig_subj = UIRenderer.escape_html(l.original_subject_name, "—")
                safe_new_subj = UIRenderer.escape_html(l.subject_name, "—")
                safe_orig_room = UIRenderer.escape_html(l.original_room_name, "—")
                safe_new_room = UIRenderer.escape_html(l.room_name, "—")
                safe_orig_teacher = UIRenderer.escape_html(l.original_teacher_name, "")
                safe_new_teacher = UIRenderer.escape_html(l.teacher_name, "")
                safe_orig_grp = UIRenderer.escape_html(l.original_group_name, "")
                safe_new_grp = UIRenderer.escape_html(l.group_name, "")

                orig_room_str = f" ({safe_orig_room})" if safe_orig_room and safe_orig_room != "—" else ""
                new_room_str = f" ({safe_new_room})" if safe_new_room and safe_new_room != "—" else ""

                subject_changed = (l.original_subject_name != l.subject_name)
                room_changed = (l.original_room_name != l.room_name)
                teacher_changed = (l.original_teacher_name != l.teacher_name)
                group_changed = safe_orig_grp and safe_new_grp and (safe_orig_grp != safe_new_grp)

                if len(parallel_lessons) == 1:
                    # === ОДИНОЧНЫЙ УРОК (Весь класс или только одна группа изменилась) ===
                    single_grp_str = ""
                    if safe_new_grp and safe_new_grp.lower() != "весь класс":
                        single_grp_str = f"  👥 Группа: <b>{safe_new_grp}</b>\n"

                    if l.is_cancelled:
                        safe_subj = UIRenderer.escape_html(l.original_subject_name or l.subject_name, "Урок")
                        text += (
                            f"  <s>{safe_subj}{orig_room_str}</s>\n"
                            f"  <b>ОТМЕНЕНО</b>\n"
                            f"{single_grp_str}"
                        )
                    else:
                        if subject_changed:
                            text += f"  было: <s>{safe_orig_subj}{orig_room_str}</s>\n"
                            text += f"  стало: <b>{safe_new_subj}{new_room_str}</b>\n"
                        elif room_changed:
                            text += f"  {safe_new_subj}\n"
                            text += f"  было: ({safe_orig_room})\n"
                            text += f"  стало: (<b>{safe_new_room}</b>)\n"
                        elif teacher_changed:
                            text += f"  {safe_new_subj}{new_room_str}\n"
                            text += f"  было: {safe_orig_teacher}\n"
                            text += f"  стало: <b>{safe_new_teacher}</b>\n"
                        else:
                            text += f"  {safe_new_subj}{new_room_str}\n"

                        if group_changed:
                            text += f"  👥 Группа: <s>{safe_orig_grp}</s> → <b>{safe_new_grp}</b>\n"
                        elif single_grp_str:
                            text += single_grp_str
                else:
                    # === МНОЖЕСТВЕННЫЕ ИЗМЕНЕНИЯ В ОДИН СЛОТ (ДЕРЕВО ПОДГРУПП) ===
                    is_last = (i == len(parallel_lessons) - 1)
                    prefix = "  └ " if is_last else "  ├ "
                    
                    # Формируем метку группы
                    if group_changed:
                        grp_label = f"👥 <s>{safe_orig_grp}</s> → <b>{safe_new_grp}</b>: "
                    else:
                        grp_label = f"👥 {safe_new_grp or 'Весь класс'}: "
                        
                    # Добавляем иконку состояния конкретной подгруппы
                    sub_icon = "❌ " if l.is_cancelled else ("🔄 " if not all_cancelled else "")

                    if l.is_cancelled:
                        safe_subj = UIRenderer.escape_html(l.original_subject_name or l.subject_name, "Урок")
                        text += f"{prefix}{sub_icon}{grp_label}<s>{safe_subj}{orig_room_str}</s> ➔ <b>ОТМЕНЕНО</b>\n"
                    else:
                        if subject_changed:
                            text += f"{prefix}{sub_icon}{grp_label}<s>{safe_orig_subj}{orig_room_str}</s> ➔ <b>{safe_new_subj}{new_room_str}</b>\n"
                        elif room_changed:
                            text += f"{prefix}{sub_icon}{grp_label}{safe_new_subj} (<s>{safe_orig_room}</s> ➔ <b>{safe_new_room}</b>)\n"
                        elif teacher_changed:
                            text += f"{prefix}{sub_icon}{grp_label}{safe_new_subj}{new_room_str} (<s>{safe_orig_teacher}</s> ➔ <b>{safe_new_teacher}</b>)\n"
                        else:
                            text += f"{prefix}{sub_icon}{grp_label}{safe_new_subj}{new_room_str}\n"

            text += "\n"

        return text, None

    # ==========================================================
    # Уведомления (MorningLessonDTO)
    # ==========================================================


    @staticmethod
    def render_morning_summary(dto: "MorningSummaryDTO") -> str:
        """
        Основной метод утренней сводки.
        Хендлер вызывает именно его — внутри просто рендерим Jinja2-шаблон,
        всю логику группировки/иконок/деталей теперь делает сам шаблон.
        """
        date_text = UIRenderer._format_short_date(dto.date_iso)

    
        template = template_env.get_template('morning_summary.j2')
        text = template.render(
            dto=dto,
            date_text=date_text,
        )
        
        return text
            

        # ==========================================================
        # Неделя (без изменений)
        # ==========================================================

    @staticmethod
    def render_week_summary(dto: WeekSummaryDTO) -> Tuple[str, None]:
        text = "📆 <b>Сводка на неделю</b>\n\n"
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
    def render_full_week_schedule(dto: FullWeekScheduleDTO) -> Tuple[str, None]:
        text = "📆 <b>Расписание на всю неделю</b>\n\n"
        
        days_texts = []
        for day_dto in dto.days:
            if day_dto.lessons:
                # Отключаем футер с изменениями для просмотра всей недели
                day_text, _ = UIRenderer.render_day_schedule(day_dto, show_footer=False)
                days_texts.append(day_text)
                
        if not days_texts:
            return text + "🏖 Занятий на этой неделе нет.", None
            
        # Склеиваем дни строгим двойным переносом для визуального разделения
        text += "\n\n".join(days_texts)
        return text, None



    # ==========================================================
    # Уведомления (LessonReminderDTO)
    # ==========================================================

    @staticmethod
    def render_lesson_reminder(dto: LessonReminderDTO) -> str:
        safe_child = UIRenderer.escape_html(dto.child_name)
        safe_subj = UIRenderer.escape_html(dto.subject_name)
        safe_room = UIRenderer.escape_html(dto.room_name, "—")

        target = f" у ребёнка <b>{safe_child}</b>" if dto.child_name else ""

        if dto.is_extra:
            room_text = f" в {safe_room}" if safe_room != "—" else ""
            return f"🎨 В {dto.start_time}{target} начнётся дополнительное занятие <b>{safe_subj}</b>{room_text}."

        room_text = f" в кабинете {safe_room}" if safe_room != "—" else ""
        return f"⏰ В {dto.start_time}{target} начнётся урок <b>{safe_subj}</b>{room_text}."
        
    # ==========================================================
    # Уведомления ChangeReminderDTO. # Склеенное изменение расписания
    # ==========================================================
    @staticmethod
    def render_daily_changes_summary(summary: 'DailyChangeSummaryDTO') -> str:
        """
        «Глупый» рендер: просто передает готовый DTO в Jinja2 шаблон.
        Вся бизнес-логика (дедупликация, каскады, скоринг) работает в сервисе collector.py.
        """
        template = template_env.get_template('daily_changes_summary.j2')
        return template.render(summary=summary).strip()
    


    # методы для формирования расписания для поиска
    @staticmethod
    def render_search_class_select() -> str:
        return "🎓 <b>Выберите класс для просмотра расписания:</b>"

    @staticmethod
    def render_search_teacher_select() -> str:
        return "👨‍🏫 <b>Выберите преподавателя:</b>"


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

    
# перерегистрация профиля   
    @staticmethod
    def render_profile_reset_confirmation(
        dto: ProfileResetImpactDTO,
        successor_name: str | None = None,
) -> str:
        """
        Текст подтверждения перерегистрации с учётом роли пользователя.
        """
        if dto.is_family_admin:
            if successor_name:
                safe_successor = UIRenderer.escape_html(successor_name)
                return (
                    "⚠️ <b>Расформировать семью и перерегистрироваться?</b>\n\n"
                    "Вы являетесь администратором семьи. "
                    f"Управление семьёй перейдёт к <b>{safe_successor}</b>.\n\n"
                    "При подтверждении:\n"
                    "• вы будете отвязаны от семьи;\n"
                    "• текущие настройки вашего профиля будут сброшены;\n"
                    "• вы сможете пройти регистрацию заново.\n\n"
                    "Это действие нельзя отменить."
                )
            else:
                return (
                    "⚠️ <b>Расформировать семью и перерегистрироваться?</b>\n\n"
                    "Вы являетесь администратором семьи. "
                    "Вы — единственный родитель: семья будет расформирована, "
                    "профили детей и доп. занятия будут удалены.\n\n"
                    "При подтверждении:\n"
                    "• семья будет расформирована;\n"
                    f"• участников семьи: <b>{dto.family_members_count}</b>;\n"
                    f"• детей в семье: <b>{dto.children_count}</b>;\n"
                    f"• дополнительных занятий будет удалено: <b>{dto.extra_classes_count}</b>;\n"
                    "• связи родителей, наблюдателей и детей будут удалены;\n"
                    "• virtual-профили детей без Telegram будут удалены;\n"
                    "• остальные пользователи останутся в боте, но будут отвязаны от семьи.\n\n"
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
            "Вы добавляете виртуальный профиль ученика. Он позволит вам:\n"
            "• Просматривать его школьное расписание;\n"
            "• Получать утренние сводки и уведомления об изменениях;\n"
            "• Добавлять и управлять его дополнительными занятиями (кружками).\n\n"
            "Ученик без Telegram не сможет получать расписание на свой телефон. "
            "В будущем вы сможете привязать к этому профилю реальный Telegram-аккаунт ребёнка.\n\n"
            "<b>Введите имя ребёнка:</b>"
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

# ==============================================================
# Rooms search
# ==============================================================

 
    @staticmethod
    def render_rooms_main_menu() -> str:
        return "🚪 <b>Поиск кабинетов</b>\n\nВыберите нужный режим:"

    @staticmethod
    def render_free_rooms_now(status: 'FreeRoomsStatusDTO', free_rooms: dict[str, str]) -> str:
        # Инкапсулируем сборку строки времени в рендерере
        if status.is_finished:
            display_time = f"{status.current_time_str} (уроки завершены)"
        else:
            num_str = f"{status.target_num} " if status.target_num else ""
            state_str = "следующий" if status.is_break else "идет"
            display_time = f"{status.current_time_str} ({state_str} {num_str}урок {status.start_time}–{status.end_time})"

        if not free_rooms:
            return f"🔴 <b>Время {display_time}:</b> Сейчас все кабинеты заняты (или школа закрыта)."
            
        rooms_text = ", ".join(free_rooms.values())
        return (
            f"🟢 <b>Свободные кабинеты на {display_time}:</b>\n\n"
            f"{rooms_text}\n\n"
            f"👇 <i>Нажмите на кабинет, чтобы проверить его занятость до конца дня:</i>"
        )
        
    @staticmethod
    def render_search_room_select() -> str:
        return "🚪 <b>Выберите кабинет:</b>"

    @staticmethod
    def render_room_day_schedule(day_dto: 'DayScheduleDTO', target_date_str: str) -> str:
        """Формат: [Урок] Время | Предмет · Класс · Учитель с показом свободных окон"""
        r_name = UIRenderer.escape_html(day_dto.class_name)
        lines = [f"🚪 <b>Занятость: {r_name} ({target_date_str})</b>\n"]
        
        if not day_dto.lessons:
            lines.append("🏖 В этот день кабинет свободен!")
            return "\n".join(lines)

        # 1. Группируем уроки по системному номеру для поиска "окон"
        lessons_by_num = {}
        for l in day_dto.lessons:
            num = l.lesson_num if l.lesson_num is not None else 99
            lessons_by_num.setdefault(num, []).append(l)

        # 2. Определяем диапазон: гарантированно с 1 по 12 урок
        # Если есть нулевой или 13+ уроки, границы расширятся автоматически
        known_nums = [n for n in lessons_by_num.keys() if n != 99]
        start_num = min(known_nums + [1])
        end_num = max(known_nums + [12])

        # 3. Выводим сетку уроков
        for current_num in range(start_num, end_num + 1):
            if current_num not in lessons_by_num:
                # Свободное окно
                lines.append(f"📗 <b>{current_num}.</b> <i>Свободно</i>")
            else:
                # Занятый урок (может быть несколько подгрупп)
                for l in lessons_by_num[current_num]:
                    num_str = f"{l.lesson_num or '•'}."
                    
                    # Моноширинное время с ведущим нулем (8:15 -> 08:15)
                    start = l.start_time.zfill(5) if l.start_time else "00:00"
                    end = l.end_time.zfill(5) if l.end_time else "00:00"
                    time_str = f"<code>{start}–{end}</code>"
                    
                    subj = UIRenderer.escape_html(l.subject_name)
                    
                    parts = [f"<b>{subj}</b>"]
                    if l.class_name:
                        parts.append(UIRenderer.escape_html(l.class_name))
                    if l.teacher_name and l.teacher_name != "—":
                        parts.append(f"<i>{UIRenderer.escape_html(l.teacher_name)}</i>")
                    
                    core_info = " · ".join(parts)
                    lines.append(f"🔸 <b>{num_str}</b> {time_str} | {core_info}")

        # 4. Обработка уроков без номера (например, баги расписания или доп. занятия)
        if 99 in lessons_by_num:
            for l in lessons_by_num[99]:
                start = l.start_time.zfill(5) if l.start_time else "00:00"
                end = l.end_time.zfill(5) if l.end_time else "00:00"
                time_str = f"<code>{start}–{end}</code>"
                
                subj = UIRenderer.escape_html(l.subject_name)
                
                parts = [f"<b>{subj}</b>"]
                if l.class_name:
                    parts.append(UIRenderer.escape_html(l.class_name))
                if l.teacher_name and l.teacher_name != "—":
                    parts.append(f"<i>{UIRenderer.escape_html(l.teacher_name)}</i>")
                
                core_info = " · ".join(parts)
                lines.append(f"🔹 <b>•.</b> {time_str} | {core_info}")
                
        return "\n".join(lines)