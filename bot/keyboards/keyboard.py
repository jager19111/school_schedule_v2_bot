# bot/keyboards/keyboard.py — ЧАСТЬ 1 из 2
#
# ЭТАП 4, финальный шаг протокола: сторона СБОРКИ коллбэков переходит
# на bot/callbacks.py. Теперь и билд, и парс живут в одном модуле —
# смена формата возможна только там.
#
# Изменения:
# - все callback_data=f"..." заменены на callbacks.build_*(...);
# - все литералы точных значений — на константы;
# - ФОРМАТ СТРОК НА ПРОВОДЕ НЕ ИЗМЕНЁН (байт-в-байт);
# - сохранены все тексты кнопок, раскладки и docstrings.
#
# СКЛЕЙКА: содержимое ЧАСТИ 2 дописать в конец этого файла
# (класс Keyboards продолжается, файл = часть1 + часть2).

from datetime import datetime, timedelta, timezone, date

from bot import callbacks
from services.help_service import HelpLinksDTO
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from core.models.dto import ( ClassListDTO, GroupListDTO, UserProfileDTO, TeacherListDTO, 
                             FamilyMemberDTO, FamilyInviteDTO, ScheduleWatchTargetDTO, ScheduleViewTargetDTO, StudentProfileDTO, ParentStudentNotificationSettingsDTO,
                            AdultStudentExtraClassesPermissionDTO, StudentTelegramSettingsDTO, StudentProfileViewModel, ScheduleTargetViewModel, WatchTargetViewModel
)


class Keyboards:

    @staticmethod
    def _week_start_for_date(date_iso: str) -> str:
        """Возвращает понедельник недели для переданной ISO-даты."""
        date_value = datetime.fromisoformat(date_iso).date()
        monday = date_value - timedelta(
            days=date_value.isoweekday() - 1
        )
        return monday.isoformat()

# Внутренний хелпер для клавиатур (не ходит в базу, просто мапит словари)
    @staticmethod
    def _format_class_and_group(class_id: str | None, group_id: str | None, classes_dict: dict, groups_dict: dict) -> tuple[str, str]:
        class_name = classes_dict.get(class_id, class_id or "—")
        if not group_id or group_id == "ALL":
            group_name = "Весь класс"
        else:
            group_name = groups_dict.get(group_id, f"Группа {group_id}")
        return class_name, group_name

    @staticmethod
    def get_help_kb(
        *,
        links: HelpLinksDTO,
        role: str | None,
        section: str,
        show_back_to_settings: bool,
    ) -> InlineKeyboardMarkup:
        """
        Клавиатура справки.

        section нужен, чтобы на внутренних страницах справки
        показывать кнопку возврата к оглавлению.
        role используется только для решения, нужно ли показывать
        кнопку возврата в Settings.
        """
        buttons = [
            [
                InlineKeyboardButton(
                    text="👨‍👩‍👧 Семья и приглашения",
                    callback_data=callbacks.build_help("family"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🧒 Ученику",
                    callback_data=callbacks.build_help("child"),
                ),
                InlineKeyboardButton(
                    text="👨‍👩‍👧 Родителю",
                    callback_data=callbacks.build_help("parent"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👁 Наблюдателю",
                    callback_data=callbacks.build_help("observer"),
                ),
                InlineKeyboardButton(
                    text="👩‍🏫 Учителю",
                    callback_data=callbacks.build_help("teacher"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔔 Уведомления",
                    callback_data=callbacks.build_help("notifications"),
                ),
                InlineKeyboardButton(
                    text="🎨 Доп. занятия",
                    callback_data=callbacks.build_help("extras"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔐 Данные и приватность",
                    callback_data=callbacks.build_help("privacy"),
                ),
            ],
        ]
        # Контакты и donation показываем только на support page.
        # Так пользователь сначала читает объяснение, а уже потом
        # осознанно выбирает внешний переход.
        if section == "support":
            support_buttons = []
            if links.author_contact_url:
                support_buttons.append(
                    InlineKeyboardButton(
                        text="💬 Связаться с автором",
                        url=links.author_contact_url,
                    )
                )
            if links.donation_url:
                support_buttons.append(
                    InlineKeyboardButton(
                        text="❤️ Поддержать проект",
                        url=links.donation_url,
                    )
                )
            # Если contact/donation ещё не заданы в config,
            # всё равно оставляем внутреннюю кнопку, чтобы UX
            # не выглядел пустым.
            if not support_buttons:
                support_buttons.append(
                    InlineKeyboardButton(
                        text="💬 Поддержка и обратная связь",
                        callback_data=callbacks.build_help("support"),
                    )
                )
            buttons.append(support_buttons)
        else:
            buttons.append([
                InlineKeyboardButton(
                    text="💬 Поддержка и обратная связь",
                    callback_data=callbacks.build_help("support"),
                )
            ])
        # Полная браузерная справка полезна на любой странице.
        if links.public_help_url:
            buttons.append([
                InlineKeyboardButton(
                    text="📖 Полная справка в браузере",
                    url=links.public_help_url,
                )
            ])            
        # На внутренних страницах справки всегда нужна навигация
        # обратно к главному экрану справки.
        if section != "main":
            buttons.append([
                InlineKeyboardButton(
                    text="ℹ️ К оглавлению",
                    callback_data=callbacks.build_help("main"),
                )
            ])
        # У зарегистрированного пользователя всегда есть путь назад.
        # show_back_to_settings оставлен для явного управления
        # при вызове из Settings.
        if role is not None or show_back_to_settings:
            buttons.append([
                InlineKeyboardButton(
                    text="⬅️ К настройкам",
                    callback_data=callbacks.SETTINGS_MAIN,
                )
            ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_role_selection() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👶 Ребёнок", callback_data=callbacks.build_role("child"))],
            [InlineKeyboardButton(text="👨‍👩‍👧 Родитель", callback_data=callbacks.build_role("parent"))],
            [InlineKeyboardButton(text="👁 Наблюдатель", callback_data=callbacks.build_role("observer"))],
            [InlineKeyboardButton(text="👨‍🏫 Учитель", callback_data=callbacks.build_role("teacher"))],
        ])

    @staticmethod
    def get_parent_family_action() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Создать новую семью", callback_data=callbacks.FAMILY_CREATE)],
            [InlineKeyboardButton(text="🔗 Присоединиться по коду", callback_data=callbacks.FAMILY_JOIN)]
        ])

    @staticmethod
    def get_child_family_action() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Присоединиться к семье", callback_data=callbacks.FAMILY_JOIN)],
            [InlineKeyboardButton(text="▶️ Продолжить без семьи", callback_data=callbacks.FAMILY_SKIP)]
        ])

    @staticmethod
    def get_class_selection(dto: ClassListDTO) -> InlineKeyboardMarkup | None:
        if not dto.classes:
            return None
        buttons = []
        row = []
        for c_id, c_name in dto.classes.items():
            row.append(InlineKeyboardButton(text=c_name, callback_data=callbacks.build_class_selection(c_id)))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row: 
            buttons.append(row)
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def get_main_group_selection(dto: 'GroupListDTO') -> InlineKeyboardMarkup:
        """Отображает только чистые основные группы (ID 0 и 1)."""
        buttons = [[InlineKeyboardButton(text="Весь класс (без подгрупп)", callback_data=callbacks.build_group_selection("ALL"))]]
        main_ids = {"0", "1"}
        added_count = 0
        for g_id, g_name in dto.groups.items():
            if g_id in main_ids:
                buttons.append([InlineKeyboardButton(text=g_name, callback_data=callbacks.build_group_selection(g_id))])
                added_count += 1
        # Фолбэк: если у старших классов нет ID 0 и 1, выводим те, где есть цифры 1 или 2 (исключая 3)
        if added_count == 0:
            for g_id, g_name in dto.groups.items():
                if "1" in g_name or "2" in g_name:
                    buttons.append([InlineKeyboardButton(text=g_name, callback_data=callbacks.build_group_selection(g_id))])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

# Основное меню
    @staticmethod
    def get_main_menu() -> ReplyKeyboardMarkup:
        """Универсальная нижняя клавиатура для всех ролей."""
        keyboard = [
            [KeyboardButton(text="📅 Моё расписание")],
            [KeyboardButton(text="🏫 Поиск по школе")],
            [KeyboardButton(text="➕ Доп. занятия"), KeyboardButton(text="⚙️ Настройки")]
        ]
        return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

    @staticmethod
    def get_school_search_kb() -> InlineKeyboardMarkup:
        """Меню поиска по школе."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎓 Расписание классов", callback_data=callbacks.SEARCH_CLASSES)],
            [InlineKeyboardButton(text="👨‍🏫 Расписание учителей", callback_data=callbacks.SEARCH_TEACHERS)]
        ])

# на удаление
    @staticmethod
    def get_parent_settings_kb(user_dto: 'UserProfileDTO') -> InlineKeyboardMarkup:
        """Настройки родителя."""
        summary_time = user_dto.morning_summary_time if user_dto.morning_summary_time else "ВЫКЛ"
        changes_status = "ВКЛ 🟢" if user_dto.is_notifications_enabled else "ВЫКЛ 🔴"
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👨‍👩‍👧 Управление семьей", callback_data=callbacks.SETTINGS_FAMILY)],
            [InlineKeyboardButton(text=f"⏰ Время моей утренней сводки: {summary_time}", callback_data=callbacks.SETTINGS_MY_SUMMARY_TIME)],
            [InlineKeyboardButton(text=f"🔔 Мои уведомления об изменениях: {changes_status}", callback_data=callbacks.SETTINGS_MY_NOTIFICATIONS)],
            [InlineKeyboardButton(text="🔄 Перерегистрироваться / Выйти", callback_data=callbacks.AUTH_RESTART)]
        ])

    @staticmethod
    def get_settings_main_kb(
        user_dto: UserProfileDTO,
    ) -> InlineKeyboardMarkup:
        """Главное меню настроек пользователя."""
        buttons = []
        if user_dto.role == "child":
            buttons.append([
                InlineKeyboardButton(
                    text="🎓 Сменить класс/группу",
                    callback_data=callbacks.SETTINGS_CHANGE_CLASS,
                )
            ])
        if user_dto.role == "teacher":
            buttons.append([
                InlineKeyboardButton(
                    text="👨‍🏫 Сменить профиль учителя",
                    callback_data=callbacks.SETTINGS_CHANGE_TEACHER,
                )
            ])
        if user_dto.role in ("parent", "observer"):
            buttons.append([
                InlineKeyboardButton(
                    text="👨‍👩‍👧 Управление семьей",
                    callback_data=callbacks.SETTINGS_FAMILY,
                )
            ])
            buttons.append([
                InlineKeyboardButton(
                    text="🎓 Мои отслеживаемые классы",
                    callback_data=callbacks.WATCH_MENU,
                )
            ])
            buttons.append([
                InlineKeyboardButton(
                    text="🔔 Уведомления по детям",
                    callback_data=callbacks.SETTINGS_CHILDREN_NOTIFICATIONS,
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="🔔 Мои уведомления",
                callback_data=callbacks.SETTINGS_NOTIFICATIONS,
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="ℹ️ Справка",
                callback_data=callbacks.build_help("main"),
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="♻️ Перерегистрация/Выход",
                callback_data=callbacks.AUTH_RESTART,
            )
        ])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def get_notifications_kb(user_dto: 'UserProfileDTO') -> InlineKeyboardMarkup:
        """Отдельное меню управления всеми уведомлениями."""
        morning_time = user_dto.morning_summary_time if user_dto.morning_summary_time else "ВЫКЛ"
        changes_state = "ВКЛ 🟢" if user_dto.receive_schedule_changes else "ВЫКЛ 🔴"
        pre_lesson_state = f"{user_dto.pre_lesson_offset_minutes} мин 🟢" if user_dto.pre_lesson_offset_minutes > 0 else "ВЫКЛ 🔴"
        extra_state = "ВКЛ 🟢" if user_dto.receive_extra_class_reminders else "ВЫКЛ 🔴"
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🌅 Утренняя сводка: {morning_time}", callback_data=callbacks.SETTINGS_MY_SUMMARY_TIME)],
            [InlineKeyboardButton(text=f"🔄 Изменения в расписании: {changes_state}", callback_data=callbacks.SET_NOTIF_CHANGES)],
            [InlineKeyboardButton(text=f"⏰ Начало урока: {pre_lesson_state}", callback_data=callbacks.SET_NOTIF_PRELESSON)],
            [InlineKeyboardButton(text=f"🎨 Доп. занятия: {extra_state}", callback_data=callbacks.SET_NOTIF_EXTRA)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=callbacks.SETTINGS_MAIN)]
        ])

    @staticmethod
    def get_student_telegram_settings_kb(
        dto: StudentTelegramSettingsDTO,
    ) -> InlineKeyboardMarkup:
        """
        Личные настройки Telegram-linked student profile.

        Все callbacks содержат student_profiles.id,
        а не users.user_id.
        """
        def bool_status(value: bool) -> str:
            return "ВКЛ 🟢" if value else "ВЫКЛ 🔴"
        notifications_text = (
            "🔔 Уведомления ребёнка: "
            f"{bool_status(dto.is_notifications_enabled)}"
        )
        summary_time = (
            dto.morning_summary_time
            if dto.morning_summary_time
            else "ВЫКЛ"
        )
        prelesson_text = (
            f"{dto.pre_lesson_offset_minutes} мин 🟢"
            if dto.pre_lesson_offset_minutes > 0
            else "ВЫКЛ 🔴"
        )
        changes_text = (
            "🔄 Изменения расписания: "
            f"{bool_status(dto.receive_schedule_changes)}"
        )
        extra_text = (
            "🎨 Напоминания о кружках: "
            f"{bool_status(dto.receive_extra_class_reminders)}"
        )
        own_extra_text = (
            "✏️ Ребёнок редактирует кружки: "
            f"{bool_status(dto.can_manage_own_extra_classes)}"
        )
        lock_text = (
            "🔒 Блокировка настроек: ВКЛ 🔒"
            if dto.child_notification_settings_locked
            else "🔒 Блокировка настроек: ВЫКЛ 🔓"
        )
        student_id = dto.student_id
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=notifications_text,
                        callback_data=callbacks.build_student_tg_toggle(
                            "notif",
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=(
                            f"🌅 Утренняя сводка: {summary_time}"
                        ),
                        callback_data=callbacks.build_student_tg_summary(
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=(
                            "⏰ Напоминания об уроках: "
                            f"{prelesson_text}"
                        ),
                        callback_data=callbacks.build_student_tg_prelesson(
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=changes_text,
                        callback_data=callbacks.build_student_tg_toggle(
                            "changes",
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=extra_text,
                        callback_data=callbacks.build_student_tg_toggle(
                            "extra",
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=own_extra_text,
                        callback_data=callbacks.build_student_tg_toggle(
                            "own_extra",
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=lock_text,
                        callback_data=callbacks.build_student_tg_lock(
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К профилю ученика",
                        callback_data=callbacks.build_student_show(
                            student_id,
                        ),
                    )
                ],
            ]
        )

#-----------------------
    # Доп занятия  ExtraClassesService
    @staticmethod
    def get_extra_classes_menu(
        *,
        target_student_id: int,
        can_add: bool,
        can_edit: bool,
        can_switch_student: bool,
    ) -> InlineKeyboardMarkup:
        """
        Меню допзанятий конкретного student profile.

        Все callback payload содержат student_profiles.id,
        а не Telegram users.user_id.

        can_switch_student=True:
        parent/observer может выбрать другого доступного ученика.
        can_switch_student=False:
        child работает только со своим profile и получает кнопку «Назад».
        """
        buttons = []
        if can_add:
            buttons.append([
                InlineKeyboardButton(
                    text="➕ Добавить занятие",
                    callback_data=callbacks.build_extra_add(target_student_id),
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="📋 Список занятий",
                callback_data=callbacks.build_extra_list(target_student_id),
            )
        ])
        if can_edit:
            buttons.append([
                InlineKeyboardButton(
                    text="✏️ Изменить занятие",
                    callback_data=callbacks.build_extra_edit(target_student_id),
                )
            ])
            buttons.append([
                InlineKeyboardButton(
                    text="🗑 Удалить занятие",
                    callback_data=callbacks.build_extra_delete(target_student_id),
                )
            ])
        if can_switch_student:
            buttons.append([
                InlineKeyboardButton(
                    text="⬅️ К выбору ученика",
                    callback_data=callbacks.EXTRA_STUDENTS,
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=callbacks.EXTRA_BACK,
                )
            ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_extra_edit_fields_kb(class_id: int) -> InlineKeyboardMarkup:
        """Клавиатура выбора поля для правки занятия."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Название", callback_data=callbacks.build_edit_field("title", class_id)),
                InlineKeyboardButton(text="Время", callback_data=callbacks.build_edit_field("time", class_id))
            ],
            [
                InlineKeyboardButton(text="Место", callback_data=callbacks.build_edit_field("loc", class_id)),
                InlineKeyboardButton(text="Напоминание", callback_data=callbacks.build_edit_field("rem", class_id))
            ],
            [
                InlineKeyboardButton(text="День недели", callback_data=callbacks.build_edit_field("day", class_id))
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=callbacks.EXTRA_CANCEL)]
        ])

    @staticmethod
    def get_cancel_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=callbacks.EXTRA_CANCEL)]
        ])

    @staticmethod
    def get_back_to_extra_menu(target_user_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=callbacks.build_extra_menu(target_user_id))]
        ])

    @staticmethod
    def get_day_selection_kb() -> InlineKeyboardMarkup:
        """Клавиатура выбора дня недели для доп. занятий."""
        days = [
            ("Пн", 1), ("Вт", 2), ("Ср", 3), 
            ("Чт", 4), ("Пт", 5), ("Сб", 6), ("Вс", 7)
        ]
        buttons = [
            [InlineKeyboardButton(text=name, callback_data=callbacks.build_extra_day(num)) for name, num in days[i:i+3]] 
            for i in range(0, 7, 3)
        ]
        # Добавляем кнопку отмены вниз
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=callbacks.EXTRA_CANCEL)])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def get_skip_cancel_keyboard(skip_callback: str) -> InlineKeyboardMarkup:
        """Клавиатура с кнопками Пропустить и Отмена."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data=skip_callback)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=callbacks.EXTRA_CANCEL)]
        ])

    @staticmethod
    def get_summary_time_prompt_kb() -> InlineKeyboardMarkup:
        """Клавиатура при запросе времени для сводки."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔕 Выключить сводку", callback_data=callbacks.SET_TIME_OFF)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=callbacks.SETTINGS_CANCEL_INPUT)]
        ])

    @staticmethod
    def get_student_telegram_summary_time_kb(
        *,
        student_id: int,
    ) -> InlineKeyboardMarkup:
        """
        Keyboard для ручного ввода времени личной сводки ребёнка.
        """
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔕 Выключить сводку",
                        callback_data=callbacks.build_student_tg_summary_off(
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data=callbacks.build_student_tg_show(
                            student_id,
                        ),
                    )
                ],
            ]
        )        
        
# Просмотр расписания
    @staticmethod
    def get_schedule_day_kb(
        current_date_iso: str,
        *,
        show_target_switch: bool
    ) -> InlineKeyboardMarkup:
        """Навигация дневного расписания в Schedule Hub."""
        current_date = datetime.fromisoformat(
            current_date_iso
        ).date()
        previous_date = (
            current_date - timedelta(days=1)
        ).isoformat()
        next_date = (
            current_date + timedelta(days=1)
        ).isoformat()
        week_start_iso = Keyboards._week_start_for_date(
            current_date_iso
        )
        buttons = [
            [
                InlineKeyboardButton(
                    text="⬅️ Предыдущий",
                    callback_data=callbacks.build_sched_day(previous_date),
                ),
                InlineKeyboardButton(
                    text="Следующий ➡️",
                    callback_data=callbacks.build_sched_day(next_date),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📆 Показать неделю",
                    callback_data=callbacks.build_sched_week(week_start_iso),
                ),
            ],
        ]
        if show_target_switch:
            buttons.append([
                InlineKeyboardButton(
                    text="🎯 Сменить цель",
                    callback_data=callbacks.SCHED_TARGETS,
                )
            ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_schedule_week_kb(
        week_start_iso: str,
        *,
        show_target_switch: bool,
        is_full: bool = False,
    ) -> InlineKeyboardMarkup:
        """
        Навигация недельного расписания.

        Каждый день открывает дневной экран, откуда пользователь всегда
        может вернуться к неделе через «📆 Показать неделю».
        """
        week_start = datetime.fromisoformat(
            week_start_iso
        ).date()
        day_buttons = []
        for offset in range(6):
            target_date = week_start + timedelta(days=offset)
            day_name = [
                "Пн",
                "Вт",
                "Ср",
                "Чт",
                "Пт",
                "Сб",
            ][offset]
            day_buttons.append(
                InlineKeyboardButton(
                    text=(
                        f"{day_name} "
                        f"{target_date.strftime('%d.%m')}"
                    ),
                    callback_data=callbacks.build_sched_day(
                        target_date.isoformat()
                    ),
                )
            )
        previous_week = (
            week_start - timedelta(days=7)
        ).isoformat()
        next_week = (
            week_start + timedelta(days=7)
        ).isoformat()
        if is_full:
            details_button = InlineKeyboardButton(
                text="🗓 Краткая неделя",
                callback_data=callbacks.build_sched_week(week_start_iso),
            )
        else:
            details_button = InlineKeyboardButton(
                text="📋 Подробно всю неделю",
                callback_data=callbacks.build_sched_full_week(week_start_iso),
            )
        buttons = [
            day_buttons[:3],
            day_buttons[3:],
            [details_button],
            [
                InlineKeyboardButton(
                    text="⬅️ Предыдущая неделя",
                    callback_data=callbacks.build_sched_week(previous_week),
                ),
                InlineKeyboardButton(
                    text="Следующая неделя ➡️",
                    callback_data=callbacks.build_sched_week(next_week),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📅 К ближайшему дню",
                    callback_data=callbacks.SCHED_SMART_DAY,
                ),
            ],
        ]
        if show_target_switch:
            buttons.append([
                InlineKeyboardButton(
                    text="🎯 Сменить цель",
                    callback_data=callbacks.SCHED_TARGETS,
                )
            ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_schedule_targets_kb(
        view_models: list[ScheduleTargetViewModel],
    ) -> InlineKeyboardMarkup:
        """
        Выбор цели Schedule Hub (Этап 5: принимает ViewModel).

        Все расшифровки и иконки — в ViewModel.
        Keyboard только строит текст кнопки и callback_data.
        """
        buttons = []
        for vm in view_models:
            if vm.kind == "student":
                # Для ученика: Иконка · Имя · Класс · Группа
                button_text = (
                    f"{vm.icon} {vm.title} · "
                    f"{vm.class_name} · {vm.group_name}"
                )
            else:
                # Для watch target: title уже содержит название класса
                button_text = (
                    f"{vm.icon} {vm.title} · {vm.group_name}"
                )
            buttons.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=callbacks.build_sched_target(
                        vm.kind,
                        vm.target_id,
                    ),
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=callbacks.SETTINGS_MAIN,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_search_days_kb(target_id: str, is_teacher: bool, week_start_iso: str, is_full: bool = False) -> InlineKeyboardMarkup:
        start_date = datetime.fromisoformat(week_start_iso).date()
        days = []
        for i in range(6):  # Пн-Сб
            day_date_obj = start_date + timedelta(days=i)
            day_date_iso = day_date_obj.isoformat()
            day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"][i]
            # НОВОЕ: Динамическая подпись даты в кнопку
            btn_text = f"{day_name} {day_date_obj.strftime('%d.%m')}"
            if is_teacher:
                day_cb = callbacks.build_search_teacher_day(target_id, day_date_iso)
            else:
                day_cb = callbacks.build_search_class_day(target_id, day_date_iso)
            days.append(InlineKeyboardButton(text=btn_text, callback_data=day_cb))
        buttons = [days[0:3], days[3:6]]
        if not is_full:
            if is_teacher:
                fw_cb = callbacks.build_search_teacher_full_week(target_id, week_start_iso)
            else:
                fw_cb = callbacks.build_search_class_full_week(target_id, week_start_iso)
            buttons.append([InlineKeyboardButton(text="📋 Все дни подробно", callback_data=fw_cb)])
        else:
            if is_teacher:
                w_cb = callbacks.build_search_teacher_week(target_id, week_start_iso)
            else:
                w_cb = callbacks.build_search_class_week(target_id, week_start_iso)
            buttons.append([InlineKeyboardButton(text="🗓 По дням", callback_data=w_cb)])
        prev_week = (start_date - timedelta(days=7)).isoformat()
        next_week = (start_date + timedelta(days=7)).isoformat()
        if is_teacher:
            prev_cb = callbacks.build_search_teacher_week(target_id, prev_week)
            next_cb = callbacks.build_search_teacher_week(target_id, next_week)
        else:
            prev_cb = callbacks.build_search_class_week(target_id, prev_week)
            next_cb = callbacks.build_search_class_week(target_id, next_week)
        buttons.append([
            InlineKeyboardButton(text="⬅️ Пред. нед", callback_data=prev_cb),
            InlineKeyboardButton(text="След. нед ➡️", callback_data=next_cb)
        ])
        back_cb = callbacks.SEARCH_TEACHERS if is_teacher else callbacks.SEARCH_CLASSES
        buttons.append([InlineKeyboardButton(text="⬅️ Назад к списку", callback_data=back_cb)])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    # Клавиатуры для поиска классов и учителей
    @staticmethod
    def get_search_classes_kb(dto: ClassListDTO) -> InlineKeyboardMarkup:
        buttons = []
        row = []
        for c_id, c_name in dto.classes.items():
            row.append(InlineKeyboardButton(text=c_name, callback_data=callbacks.build_search_class(c_id)))
            if len(row) == 4:  # По 4 класса в ряд
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=callbacks.SEARCH_BACK)])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def get_search_teachers_kb(dto: 'TeacherListDTO') -> InlineKeyboardMarkup:
        buttons = []
        row = []
        # Сортируем учителей по алфавиту
        sorted_teachers = sorted(dto.teachers.items(), key=lambda x: x[1].name if hasattr(x[1], 'name') else x[1])
        for t_id, t_name in sorted_teachers:
            # Извлекаем строковое имя, если это объект Teacher
            name_str = t_name.name if hasattr(t_name, 'name') else t_name
            row.append(InlineKeyboardButton(text=name_str, callback_data=callbacks.build_search_teacher(t_id)))
            if len(row) == 2:  # По 2 учителя в ряд
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=callbacks.SEARCH_BACK)])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def get_family_management_error_kb() -> InlineKeyboardMarkup:
        """Клавиатура-заглушка для ребёнка без семьи."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Перерегистрироваться", callback_data=callbacks.AUTH_RESTART)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=callbacks.SETTINGS_MAIN)]
        ])

    # Клавитура семьи
    # ВАЖНО: keyboard не использовала members/classes_dict даже в старой
# версии — упрощаем сигнатуру до того, что реально нужно.
    @staticmethod
    def get_family_management_kb(
        *,
        current_role: str,
        is_family_admin: bool,
    ) -> InlineKeyboardMarkup:
        """
        Клавиатура управления семьёй (Этап 5: упрощённая).

        Не зависит от списка членов семьи — только от роли
        текущего пользователя и флага администратора.
        """
        buttons = []

        if current_role in ("parent", "observer"):
            buttons.append([
                InlineKeyboardButton(
                    text="🧒 Ученики семьи",
                    callback_data=callbacks.FAMILY_STUDENTS,
                )
            ])

        if is_family_admin:
            buttons.append([
                InlineKeyboardButton(
                    text="📨 Пригласить участника",
                    callback_data=callbacks.FAMILY_INVITE_MENU,
                )
            ])
            buttons.append([
                InlineKeyboardButton(
                    text="📬 Активные приглашения",
                    callback_data=callbacks.FAMILY_INVITES,
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ Назад к настройкам",
                callback_data=callbacks.SETTINGS_MAIN,
            )
        ])

        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )


    @staticmethod
    def get_extra_students_select_kb(
        view_models: list[StudentProfileViewModel],
    ) -> InlineKeyboardMarkup:
        """
        Выбор student profile для допзанятий (Этап 5: ViewModel).
        """
        buttons = []
        for vm in view_models:
            icon = "📱" if vm.telegram_connected else "🧒"
            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"{icon} {vm.name} "
                        f"· {vm.class_name} "
                        f"· {vm.group_name}"
                    ),
                    callback_data=callbacks.build_extra_menu(
                        vm.student_id,
                    ),
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=callbacks.SETTINGS_MAIN,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_student_notification_select_kb(
        view_models: list[StudentProfileViewModel],
    ) -> InlineKeyboardMarkup:
        """
        Выбор ученика для уведомлений (Этап 5: ViewModel).
        """
        buttons = []
        for vm in view_models:
            icon = "📱" if vm.telegram_connected else "🧒"
            # Для этого экрана группа — lowercase (как в оригинале)
            group_lower = vm.group_name.lower()
            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"{icon} {vm.name} "
                        f"· {vm.class_name} "
                        f"· {group_lower}"
                    ),
                    callback_data=callbacks.build_psn_student(
                        vm.student_id,
                    ),
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К настройкам",
                callback_data=callbacks.SETTINGS_MAIN,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_parent_student_notification_settings_kb(
        dto: ParentStudentNotificationSettingsDTO,
    ) -> InlineKeyboardMarkup:
        """
        Переключатели personal adult subscriptions
        по конкретному student profile.
        """
        def status(value: bool) -> str:
            return "ВКЛ 🟢" if value else "ВЫКЛ 🔴"
        student_id = dto.student_id
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=(
                            "🌅 Утренняя сводка: "
                            f"{status(dto.receive_morning_summary)}"
                        ),
                        callback_data=callbacks.build_psn_toggle(
                            "morning",
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=(
                            "⏰ Напоминания об уроках: "
                            f"{status(dto.receive_pre_lesson_reminders)}"
                        ),
                        callback_data=callbacks.build_psn_toggle(
                            "prelesson",
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=(
                            "🔄 Изменения расписания: "
                            f"{status(dto.receive_schedule_changes)}"
                        ),
                        callback_data=callbacks.build_psn_toggle(
                            "changes",
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=(
                            "🎨 Доп. занятия: "
                            f"{status(dto.receive_extra_class_reminders)}"
                        ),
                        callback_data=callbacks.build_psn_toggle(
                            "extra",
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К ученикам",
                        callback_data=callbacks.SETTINGS_CHILDREN_NOTIFICATIONS,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⚙️ Главные настройки",
                        callback_data=callbacks.SETTINGS_MAIN,
                    )
                ],
            ]
        )

    @staticmethod
    def get_adult_student_extra_classes_permissions_kb(
        *,
        student_id: int,
        permissions: list[
            AdultStudentExtraClassesPermissionDTO
        ],
    ) -> InlineKeyboardMarkup:
        """
        Кнопки управления правами взрослых на кружки student profile.

        Family admin не показывается в списке:
        его право управления считается системным и всегда доступно.
        """
        buttons = []
        for permission in permissions:
            role_label = (
                "👨‍👩‍👧 Родитель"
                if permission.adult_role == "parent"
                else "👁 Наблюдатель"
            )
            state_label = (
                "ВКЛ 🟢"
                if permission.can_manage_extra_classes
                else "ВЫКЛ 🔴"
            )
            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"{role_label}: "
                        f"{permission.adult_name} — "
                        f"{state_label}"
                    ),
                    callback_data=callbacks.build_student_perm_toggle(
                        student_id,
                        permission.adult_user_id,
                    ),
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К профилю ученика",
                callback_data=callbacks.build_student_show(student_id),
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

#перерегистрация
    @staticmethod
    def get_profile_reset_confirmation_kb() -> InlineKeyboardMarkup:
        """
        Подтверждение необратимой операции перерегистрации.
        """
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⚠️ Да, перерегистрироваться",
                        callback_data=callbacks.AUTH_RESTART_CONFIRM,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data=callbacks.SETTINGS_MAIN,
                    )
                ],
            ]
        )

    @staticmethod
    def get_family_invite_role_kb() -> InlineKeyboardMarkup:
        """
        Выбор фиксированной роли нового участника семьи.
        """
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="👶 Ребёнка с Telegram",
                        callback_data=callbacks.build_family_invite_role("child"),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="👨‍👩‍👧 Родителя",
                        callback_data=callbacks.build_family_invite_role("parent"),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="👁 Наблюдателя",
                        callback_data=callbacks.build_family_invite_role("observer"),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад к семье",
                        callback_data=callbacks.SETTINGS_FAMILY,
                    )
                ],
            ]
        )

    @staticmethod
    def get_family_invite_result_kb(
        share_link: str,
        deep_link: str,
    ) -> InlineKeyboardMarkup:
        """
        Доставка family invite.

        share_link открывает Telegram share sheet с готовым текстом.
        deep_link остаётся доступен как резервный вариант.
        """
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📤 Отправить приглашение",
                        url=share_link,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📎 Открыть ссылку приглашения",
                        url=deep_link,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📨 Создать ещё приглашение",
                        callback_data=callbacks.FAMILY_INVITE_MENU,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К семье",
                        callback_data=callbacks.SETTINGS_FAMILY,
                    )
                ],
            ]
        )

    @staticmethod
    def get_active_family_invites_kb(
        invites: list[FamilyInviteDTO],
    ) -> InlineKeyboardMarkup:
        """
        Список active invites family admin.
        """
        buttons = []
        role_icons = {
            "child": "👶",
            "parent": "👨‍👩‍👧",
            "observer": "👁",
        }
        role_names = {
            "child": "Ребёнок",
            "parent": "Родитель",
            "observer": "Наблюдатель",
        }
        for invite in invites:
            icon = role_icons.get(
                invite.intended_role,
                "📨",
            )
            role_name = role_names.get(
                invite.intended_role,
                "Участник",
            )
            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"{icon} {role_name} · "
                        f"до {invite.expires_at}"
                    ),
                    callback_data=callbacks.build_family_invite(invite.id),
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="📨 Создать приглашение",
                callback_data=callbacks.FAMILY_INVITE_MENU,
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К семье",
                callback_data=callbacks.SETTINGS_FAMILY,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_family_invite_details_kb(
        *,
        invite_id: int,
        share_link: str,
    ) -> InlineKeyboardMarkup:
        """
        Действия над active invite.
        """
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📤 Отправить приглашение",
                        url=share_link,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🚫 Отозвать приглашение",
                        callback_data=callbacks.build_family_invite_revoke(
                            invite_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К приглашениям",
                        callback_data=callbacks.FAMILY_INVITES,
                    )
                ],
            ]
        )

    @staticmethod
    def get_family_invite_revoke_confirmation_kb(
        invite_id: int,
    ) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🚫 Да, отозвать",
                        callback_data=callbacks.build_family_invite_revoke_confirm(
                            invite_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data=callbacks.build_family_invite(invite_id),
                    )
                ],
            ]
        )

    @staticmethod
    def get_watch_targets_menu_kb(
        view_models: list[WatchTargetViewModel],
    ) -> InlineKeyboardMarkup:
        """
        Список отслеживаемых классов (Этап 5: принимает ViewModel).
        """
        buttons = []
        for vm in view_models:
            status = "🟢" if vm.is_enabled else "⚫"
            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"{status} {vm.title} · {vm.group_name}"
                    ),
                    callback_data=callbacks.build_watch_target(
                        vm.target_id,
                    ),
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="➕ Добавить класс",
                callback_data=callbacks.WATCH_ADD,
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К настройкам",
                callback_data=callbacks.SETTINGS_MAIN,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_watch_class_selection_kb(
        dto: ClassListDTO,
    ) -> InlineKeyboardMarkup:
        buttons = []
        row = []
        for class_id, class_name in dto.classes.items():
            row.append(
                InlineKeyboardButton(
                    text=class_name,
                    callback_data=callbacks.build_watch_class(class_id),
                )
            )
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=callbacks.WATCH_MENU,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_watch_group_selection_kb(
        dto: GroupListDTO,
    ) -> InlineKeyboardMarkup:
        """
        Выбор группы для самостоятельно отслеживаемого класса.

        На первом этапе используем весь класс и основные группы.
        """
        buttons = [
            [
                InlineKeyboardButton(
                    text="Весь класс",
                    callback_data=callbacks.build_watch_group("ALL"),
                )
            ]
        ]
        primary_groups = {
            "0",
            "1",
        }
        for group_id, group_name in dto.groups.items():
            if group_id not in primary_groups:
                continue
            buttons.append([
                InlineKeyboardButton(
                    text=group_name,
                    callback_data=callbacks.build_watch_group(group_id),
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ Назад к выбору класса",
                callback_data=callbacks.WATCH_ADD,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_watch_target_details_kb(
        vm: WatchTargetViewModel,
    ) -> InlineKeyboardMarkup:
        """
        Карточка отслеживаемого класса (Этап 5: принимает ViewModel).

        Boolean-поля ViewModel определяют текст кнопок-тумблеров.
        """
        status_text = (
            "⚫ Выключить отслеживание"
            if vm.is_enabled
            else "🟢 Включить отслеживание"
        )
        changes_text = (
            "🔄 Изменения: ВКЛ 🟢"
            if vm.receive_schedule_changes
            else "🔄 Изменения: ВЫКЛ 🔴"
        )
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📅 Открыть расписание",
                        callback_data=callbacks.build_sched_watch(
                            vm.target_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=changes_text,
                        callback_data=callbacks.build_watch_changes(
                            vm.target_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=status_text,
                        callback_data=callbacks.build_watch_toggle(
                            vm.target_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🗑 Удалить класс",
                        callback_data=callbacks.build_watch_delete(
                            vm.target_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К списку классов",
                        callback_data=callbacks.WATCH_MENU,
                    )
                ],
            ]
        )


    @staticmethod
    def get_watch_target_delete_confirmation_kb(
        target_id: int,
    ) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑 Да, удалить класс",
                        callback_data=callbacks.build_watch_delete_confirm(
                            target_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data=callbacks.build_watch_target(target_id),
                    )
                ],
            ]
        )

    @staticmethod
    def get_family_students_kb(
        view_models: list[StudentProfileViewModel],
        *,
        is_family_admin: bool,
    ) -> InlineKeyboardMarkup:
        """
        Список student_profiles семьи (Этап 5: принимает ViewModel).

        Parent/observer видит учеников, доступных через
        parent_student_settings. Family admin может добавить ученика.
        """
        buttons = []
        for vm in view_models:
            icon = "📱" if vm.telegram_connected else "🧒"
            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"{icon} {vm.name} "
                        f"· {vm.class_name} "
                        f"· {vm.group_name}"
                    ),
                    callback_data=callbacks.build_student_show(
                        vm.student_id,
                    ),
                )
            ])
        if is_family_admin:
            buttons.append([
                InlineKeyboardButton(
                    text="➕ Добавить ученика",
                    callback_data=callbacks.STUDENT_ADD,
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К семье",
                callback_data=callbacks.SETTINGS_FAMILY,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )


    @staticmethod
    def get_student_details_kb(
        vm: StudentProfileViewModel,
        *,
        is_family_admin: bool,
    ) -> InlineKeyboardMarkup:
        """
        Действия над student profile (Этап 5: принимает ViewModel).
        """
        buttons = []
        if is_family_admin:
            buttons.append([
                InlineKeyboardButton(
                    text="🎓 Изменить класс / группу",
                    callback_data=callbacks.build_student_edit_class(
                        vm.student_id,
                    ),
                )
            ])
            if vm.telegram_connected:
                buttons.append([
                    InlineKeyboardButton(
                        text="📱 Настройки Telegram-ребёнка",
                        callback_data=callbacks.build_student_tg_show(
                            vm.student_id,
                        ),
                    )
                ])
            buttons.append([
                InlineKeyboardButton(
                    text="👥 Права взрослых на кружки",
                    callback_data=callbacks.build_student_extra_permissions(
                        vm.student_id,
                    ),
                )
            ])
        if not vm.telegram_connected and is_family_admin:
            buttons.append([
                InlineKeyboardButton(
                    text="📱 Привязать Telegram",
                    callback_data=callbacks.build_student_claim(
                        vm.student_id,
                    ),
                )
            ])
            buttons.append([
                InlineKeyboardButton(
                    text="🗑 Удалить ученика",
                    callback_data=callbacks.build_student_delete(
                        vm.student_id,
                    ),
                )
            ])
        if vm.telegram_connected:
            buttons.append([
                InlineKeyboardButton(
                    text="📱 Telegram-профиль подключён",
                    callback_data=callbacks.build_student_show(
                        vm.student_id,
                    ),
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К ученикам",
                callback_data=callbacks.FAMILY_STUDENTS,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )


    @staticmethod
    def get_student_claim_invite_result_kb(
        *,
        share_link: str,
        deep_link: str,
        student_id: int,
    ) -> InlineKeyboardMarkup:
        """
        Кнопки после выпуска claim invite.

        share_link открывает стандартный Telegram share sheet.
        deep_link можно скопировать/переслать вручную.
        """
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📤 Отправить ссылку ребёнку",
                        url=share_link,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📎 Открыть ссылку",
                        url=deep_link,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Создать новую ссылку",
                        callback_data=callbacks.build_student_claim(student_id),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К ученику",
                        callback_data=callbacks.build_student_show(student_id),
                    )
                ],
            ]
        )

    @staticmethod
    def get_student_claim_confirmation_kb() -> InlineKeyboardMarkup:
        """
        Подтверждение привязки Telegram к existing student profile.

        Token хранится только в FSM, а не в callback_data.
        """
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Это я",
                        callback_data=callbacks.CLAIM_CONFIRM,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data=callbacks.CLAIM_CANCEL,
                    )
                ],
            ]
        )

    @staticmethod
    def get_student_class_selection_kb(
        dto: ClassListDTO,
    ) -> InlineKeyboardMarkup:
        buttons = []
        row = []
        for class_id, class_name in dto.classes.items():
            row.append(
                InlineKeyboardButton(
                    text=class_name,
                    callback_data=callbacks.build_student_class(class_id),
                )
            )
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К ученикам",
                callback_data=callbacks.FAMILY_STUDENTS,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_student_group_selection_kb(
        dto: GroupListDTO,
    ) -> InlineKeyboardMarkup:
        """
        Выбор группы virtual student.

        Начинаем с ALL и основных групп NIKA 0/1.
        """
        buttons = [
            [
                InlineKeyboardButton(
                    text="Весь класс",
                    callback_data=callbacks.build_student_group("ALL"),
                )
            ]
        ]
        primary_groups = {
            "0",
            "1",
        }
        for group_id, group_name in dto.groups.items():
            if group_id not in primary_groups:
                continue
            buttons.append([
                InlineKeyboardButton(
                    text=group_name,
                    callback_data=callbacks.build_student_group(group_id),
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К выбору класса",
                callback_data=callbacks.STUDENT_ADD,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_student_delete_confirmation_kb(
        student_id: int,
    ) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑 Да, удалить ученика",
                        callback_data=callbacks.build_student_delete_confirm(
                            student_id,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data=callbacks.build_student_show(student_id),
                    )
                ],
            ]
        )

    @staticmethod
    def get_claim_cancel_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data=callbacks.CLAIM_CANCEL,
                    )
                ]
            ]
        )

    # ЭТАП 4: удалён мёртвый блок `if False:` с claim-клавиатурами
    # (get_claim_class_selection_kb / get_claim_group_selection_kb):
    # не использовались нигде с момента появления FSM claim-флоу.

    @staticmethod
    def get_student_edit_class_selection_kb(
        dto: ClassListDTO,
        *,
        student_id: int,
    ) -> InlineKeyboardMarkup:
        """
        Выбор нового класса family admin для student profile.
        """
        buttons = []
        row = []
        for class_id, class_name in dto.classes.items():
            row.append(
                InlineKeyboardButton(
                    text=class_name,
                    callback_data=callbacks.build_student_edit_class_select(
                        student_id,
                        class_id,
                    ),
                )
            )
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К профилю ученика",
                callback_data=callbacks.build_student_show(student_id),
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_student_edit_group_selection_kb(
        dto: GroupListDTO,
        *,
        student_id: int,
    ) -> InlineKeyboardMarkup:
        """
        Выбор новой основной группы student profile.

        Используем «Весь класс» и группы 0/1.
        """
        buttons = [
            [
                InlineKeyboardButton(
                    text="Весь класс",
                    callback_data=callbacks.build_student_edit_group_select(
                        student_id,
                        "ALL",
                    ),
                )
            ]
        ]
        for group_id in ("0", "1"):
            group_name = dto.groups.get(group_id)
            if group_name is None:
                continue
            buttons.append([
                InlineKeyboardButton(
                    text=group_name,
                    callback_data=callbacks.build_student_edit_group_select(
                        student_id,
                        group_id,
                    ),
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К выбору класса",
                callback_data=callbacks.build_student_edit_class(student_id),
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К профилю ученика",
                callback_data=callbacks.build_student_show(student_id),
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_self_edit_class_selection_kb(
        dto: ClassListDTO,
    ) -> InlineKeyboardMarkup:
        """
        Выбор класса для зарегистрированного child.

        Используется только в child self-edit settings flow.
        Не используется при регистрации и family invite.
        """
        buttons = []
        row = []
        for class_id, class_name in dto.classes.items():
            row.append(
                InlineKeyboardButton(
                    text=class_name,
                    callback_data=callbacks.build_self_edit_class(class_id),
                )
            )
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ Назад к настройкам",
                callback_data=callbacks.SELF_EDIT_CANCEL,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_self_edit_group_selection_kb(
        dto: GroupListDTO,
    ) -> InlineKeyboardMarkup:
        """
        Выбор основной группы для child self-edit flow.

        Используются «Весь класс» и основные NIKA-группы 0/1.
        """
        buttons = [
            [
                InlineKeyboardButton(
                    text="Весь класс",
                    callback_data=callbacks.build_self_edit_group("ALL"),
                )
            ]
        ]
        primary_group_ids = {"0", "1"}
        added_count = 0
        for group_id, group_name in dto.groups.items():
            if group_id not in primary_group_ids:
                continue
            buttons.append([
                InlineKeyboardButton(
                    text=group_name,
                    callback_data=callbacks.build_self_edit_group(group_id),
                )
            ])
            added_count += 1
        # Такой же fallback, как в get_main_group_selection(...).
        # Нужен для классов, где IDs групп не 0/1.
        if added_count == 0:
            for group_id, group_name in dto.groups.items():
                normalized_name = str(group_name).lower()
                if (
                    "1" in normalized_name
                    or "2" in normalized_name
                ) and "3" not in normalized_name:
                    buttons.append([
                        InlineKeyboardButton(
                            text=group_name,
                            callback_data=callbacks.build_self_edit_group(group_id),
                        )
                    ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К выбору класса",
                callback_data=callbacks.SELF_EDIT_BACK_TO_CLASS,
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ Назад к настройкам",
                callback_data=callbacks.SELF_EDIT_CANCEL,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    #----------------------
    #   УЧИТЕЛЬ
    #----------------------
    @staticmethod
    def get_teacher_registration_kb(
        dto: TeacherListDTO,
    ) -> InlineKeyboardMarkup:
        """
        Выбор NIKA teacher для регистрации Telegram teacher account.
        """
        buttons = []
        row = []
        teachers = sorted(
            dto.teachers.items(),
            key=lambda item: (
                getattr(item[1], "name", item[1]) or ""
            ).lower(),
        )
        for teacher_id, teacher_name in teachers:
            name = getattr(
                teacher_name,
                "name",
                teacher_name,
            )
            row.append(
                InlineKeyboardButton(
                    text=str(name),
                    callback_data=callbacks.build_teacher_registration(
                        teacher_id,
                    ),
                )
            )
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=callbacks.build_teacher_registration("cancel"),
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

    @staticmethod
    def get_teacher_schedule_day_kb(
        *,
        current_date_iso: str,
    ) -> InlineKeyboardMarkup:
        current_date = datetime.fromisoformat(
            current_date_iso
        ).date()
        previous_date = (
            current_date - timedelta(days=1)
        ).isoformat()
        next_date = (
            current_date + timedelta(days=1)
        ).isoformat()
        week_start = (
            current_date
            - timedelta(days=current_date.isoweekday() - 1)
        ).isoformat()
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Предыдущий",
                        callback_data=callbacks.build_teacher_sched_day(
                            previous_date,
                        ),
                    ),
                    InlineKeyboardButton(
                        text="Следующий ➡️",
                        callback_data=callbacks.build_teacher_sched_day(
                            next_date,
                        ),
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="📆 Показать неделю",
                        callback_data=callbacks.build_teacher_sched_week(
                            week_start,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📅 К ближайшему дню",
                        callback_data=callbacks.TEACHER_SCHED_SMART_DAY,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⚙️ Настройки",
                        callback_data=callbacks.SETTINGS_MAIN,
                    )
                ],
            ]
        )

    @staticmethod
    def get_teacher_schedule_week_kb(
        *,
        week_start_iso: str,
        is_full: bool = False,
    ) -> InlineKeyboardMarkup:
        week_start = datetime.fromisoformat(
            week_start_iso
        ).date()
        day_buttons = []
        for offset in range(6):
            target_date = week_start + timedelta(days=offset)
            day_name = [
                "Пн",
                "Вт",
                "Ср",
                "Чт",
                "Пт",
                "Сб",
            ][offset]
            day_buttons.append(
                InlineKeyboardButton(
                    text=(
                        f"{day_name} "
                        f"{target_date.strftime('%d.%m')}"
                    ),
                    callback_data=callbacks.build_teacher_sched_day(
                        target_date.isoformat(),
                    ),
                )
            )
        previous_week = (
            week_start - timedelta(days=7)
        ).isoformat()
        next_week = (
            week_start + timedelta(days=7)
        ).isoformat()
        details_button = (
            InlineKeyboardButton(
                text="🗓 Краткая неделя",
                callback_data=callbacks.build_teacher_sched_week(
                    week_start_iso,
                ),
            )
            if is_full
            else InlineKeyboardButton(
                text="📋 Подробно всю неделю",
                callback_data=callbacks.build_teacher_sched_full_week(
                    week_start_iso,
                ),
            )
        )
        return InlineKeyboardMarkup(
            inline_keyboard=[
                day_buttons[:3],
                day_buttons[3:],
                [details_button],
                [
                    InlineKeyboardButton(
                        text="⬅️ Предыдущая неделя",
                        callback_data=callbacks.build_teacher_sched_week(
                            previous_week,
                        ),
                    ),
                    InlineKeyboardButton(
                        text="Следующая неделя ➡️",
                        callback_data=callbacks.build_teacher_sched_week(
                            next_week,
                        ),
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="📅 К ближайшему дню",
                        callback_data=callbacks.TEACHER_SCHED_SMART_DAY,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⚙️ Настройки",
                        callback_data=callbacks.SETTINGS_MAIN,
                    )
                ],
            ]
        )

    @staticmethod
    def get_teacher_change_kb(
        dto: TeacherListDTO,
    ) -> InlineKeyboardMarkup:
        """
        Teacher self-service selector.

        Отдельный callback namespace, чтобы не пересекаться
        с registration flow.
        """
        buttons = []
        row = []
        teachers = sorted(
            dto.teachers.items(),
            key=lambda item: (
                str(
                    getattr(
                        item[1],
                        "name",
                        item[1],
                    )
                ).lower()
            ),
        )
        for teacher_id, teacher_name in teachers:
            name = getattr(
                teacher_name,
                "name",
                teacher_name,
            )
            row.append(
                InlineKeyboardButton(
                    text=str(name),
                    callback_data=callbacks.build_teacher_change(
                        teacher_id,
                    ),
                )
            )
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К настройкам",
                callback_data=callbacks.SETTINGS_MAIN,
            )
        ])
        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )
