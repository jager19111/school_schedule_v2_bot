from datetime import datetime, timedelta, timezone, date
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from core.models.dto import ( ClassListDTO, GroupListDTO, UserProfileDTO, TeacherListDTO, 
                             FamilyMemberDTO, FamilyInviteDTO, ScheduleWatchTargetDTO, ScheduleViewTargetDTO, StudentProfileDTO, ParentStudentNotificationSettingsDTO,
                            AdultStudentExtraClassesPermissionDTO, StudentTelegramSettingsDTO,
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
    def get_role_selection() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👶 Ребёнок", callback_data="role:child")],
            [InlineKeyboardButton(text="👨‍👩‍👧 Родитель", callback_data="role:parent")],
            [InlineKeyboardButton(text="👁 Наблюдатель", callback_data="role:observer")],
            [InlineKeyboardButton(text="👨‍🏫 Учитель", callback_data="role:teacher")],
            
        ])

    @staticmethod
    def get_parent_family_action() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Создать новую семью", callback_data="family:create")],
            [InlineKeyboardButton(text="🔗 Присоединиться по коду", callback_data="family:join")]
        ])

    @staticmethod
    def get_child_family_action() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Присоединиться к семье", callback_data="family:join")],
            [InlineKeyboardButton(text="▶️ Продолжить без семьи", callback_data="family:skip")]
        ])

    @staticmethod
    def get_class_selection(dto: ClassListDTO) -> InlineKeyboardMarkup | None:
        if not dto.classes:
            return None
            
        buttons = []
        row = []
        for c_id, c_name in dto.classes.items():
            row.append(InlineKeyboardButton(text=c_name, callback_data=f"class:{c_id}"))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row: 
            buttons.append(row)
            
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def get_main_group_selection(dto: 'GroupListDTO') -> InlineKeyboardMarkup:
        """Отображает только чистые основные группы (ID 0 и 1)."""
        buttons = [[InlineKeyboardButton(text="Весь класс (без подгрупп)", callback_data="group:ALL")]]
        
        main_ids = {"0", "1"}
        added_count = 0
        
        for g_id, g_name in dto.groups.items():
            if g_id in main_ids:
                buttons.append([InlineKeyboardButton(text=g_name, callback_data=f"group:{g_id}")])
                added_count += 1
                
        # Фолбэк: если у старших классов нет ID 0 и 1, выводим те, где есть цифры 1 или 2 (исключая 3)
        if added_count == 0:
            for g_id, g_name in dto.groups.items():
                if "1" in g_name or "2" in g_name:
                    buttons.append([InlineKeyboardButton(text=g_name, callback_data=f"group:{g_id}")])
                    
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
            [InlineKeyboardButton(text="🎓 Расписание классов", callback_data="search:classes")],
            [InlineKeyboardButton(text="👨‍🏫 Расписание учителей", callback_data="search:teachers")]
        ])
# на удаление
    @staticmethod
    def get_parent_settings_kb(user_dto: 'UserProfileDTO') -> InlineKeyboardMarkup:
        """Настройки родителя."""
        summary_time = user_dto.morning_summary_time if user_dto.morning_summary_time else "ВЫКЛ"
        changes_status = "ВКЛ 🟢" if user_dto.is_notifications_enabled else "ВЫКЛ 🔴"

        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👨‍👩‍👧 Управление семьей", callback_data="settings:family")],
            [InlineKeyboardButton(text=f"⏰ Время моей утренней сводки: {summary_time}", callback_data="settings:my_summary_time")],
            [InlineKeyboardButton(text=f"🔔 Мои уведомления об изменениях: {changes_status}", callback_data="settings:my_notifications")],
            [InlineKeyboardButton(text="🔄 Перерегистрироваться / Выйти", callback_data="auth:restart")]
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
                    callback_data="settings:change_class",
                )
            ])

        if user_dto.role == "teacher":
            buttons.append([
                InlineKeyboardButton(
                    text="👨‍🏫 Сменить профиль учителя",
                    callback_data="settings:change_teacher",
                )
            ])
    
        if user_dto.role in ("parent", "observer"):
            buttons.append([
                InlineKeyboardButton(
                    text="👨‍👩‍👧 Управление семьей",
                    callback_data="settings:family",
                )
            ])
            buttons.append([
                InlineKeyboardButton(
                    text="🎓 Мои отслеживаемые классы",
                    callback_data="watch:menu",
                )
            ])
            buttons.append([
                InlineKeyboardButton(
                    text="🔔 Уведомления по детям",
                    callback_data="settings:children_notifications",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="🔔 Мои уведомления",
                callback_data="settings:notifications",
            )
        ])

        buttons.append([
            InlineKeyboardButton(
                text="🔄 Перерегистрироваться / Выйти",
                callback_data="auth:restart",
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
            [InlineKeyboardButton(text=f"🌅 Утренняя сводка: {morning_time}", callback_data="settings:my_summary_time")],
            [InlineKeyboardButton(text=f"🔄 Изменения в расписании: {changes_state}", callback_data="set_notif:changes")],
            [InlineKeyboardButton(text=f"⏰ Начало урока: {pre_lesson_state}", callback_data="set_notif:prelesson")],
            [InlineKeyboardButton(text=f"🎨 Доп. занятия: {extra_state}", callback_data="set_notif:extra")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:main")]
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
                        callback_data=(
                            f"student_tg:toggle:notif:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=(
                            f"🌅 Утренняя сводка: {summary_time}"
                        ),
                        callback_data=(
                            f"student_tg:summary:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=(
                            "⏰ Напоминания об уроках: "
                            f"{prelesson_text}"
                        ),
                        callback_data=(
                            f"student_tg:prelesson:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=changes_text,
                        callback_data=(
                            f"student_tg:toggle:changes:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=extra_text,
                        callback_data=(
                            f"student_tg:toggle:extra:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=own_extra_text,
                        callback_data=(
                            f"student_tg:toggle:own_extra:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=lock_text,
                        callback_data=(
                            f"student_tg:lock:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К профилю ученика",
                        callback_data=f"student:show:{student_id}",
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
                    callback_data=f"extra:add:{target_student_id}",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="📋 Список занятий",
                callback_data=f"extra:list:{target_student_id}",
            )
        ])

        if can_edit:
            buttons.append([
                InlineKeyboardButton(
                    text="✏️ Изменить занятие",
                    callback_data=f"extra:edit:{target_student_id}",
                )
            ])

            buttons.append([
                InlineKeyboardButton(
                    text="🗑 Удалить занятие",
                    callback_data=f"extra:delete:{target_student_id}",
                )
            ])

        if can_switch_student:
            buttons.append([
                InlineKeyboardButton(
                    text="⬅️ К выбору ученика",
                    callback_data="extra:students",
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="extra:back",
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
                InlineKeyboardButton(text="Название", callback_data=f"edit_ext:title:{class_id}"),
                InlineKeyboardButton(text="Время", callback_data=f"edit_ext:time:{class_id}")
            ],
            [
                InlineKeyboardButton(text="Место", callback_data=f"edit_ext:loc:{class_id}"),
                InlineKeyboardButton(text="Напоминание", callback_data=f"edit_ext:rem:{class_id}")
            ],
            [
                InlineKeyboardButton(text="День недели", callback_data=f"edit_ext:day:{class_id}") # <-- ДОБАВЛЕНО
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="extra:cancel")]
        ])

    
    @staticmethod
    def get_cancel_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="extra:cancel")]
        ])

    @staticmethod
    def get_back_to_extra_menu(target_user_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"extra:menu:{target_user_id}")]
        ])
        
    @staticmethod
    def get_day_selection_kb() -> InlineKeyboardMarkup:
        """Клавиатура выбора дня недели для доп. занятий[cite: 2]."""
        days = [
            ("Пн", 1), ("Вт", 2), ("Ср", 3), 
            ("Чт", 4), ("Пт", 5), ("Сб", 6), ("Вс", 7)
        ]
        buttons = [
            [InlineKeyboardButton(text=name, callback_data=f"extraday:{num}") for name, num in days[i:i+3]] 
            for i in range(0, 7, 3)
        ]
        # Добавляем кнопку отмены вниз
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="extra:cancel")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def get_skip_cancel_keyboard(skip_callback: str) -> InlineKeyboardMarkup:
        """Клавиатура с кнопками Пропустить и Отмена."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data=skip_callback)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="extra:cancel")]
        ])
        
    # Сводка. удалить после рефакторинга
    @staticmethod
    def get_summary_time_prompt_kb() -> InlineKeyboardMarkup:
        """Клавиатура при запросе времени для сводки."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔕 Выключить сводку", callback_data="set_time:off")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="settings:cancel_input")]
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
                        callback_data=(
                            f"student_tg:summary_off:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data=f"student_tg:show:{student_id}",
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
                    callback_data=f"sched:day:{previous_date}",
                ),
                InlineKeyboardButton(
                    text="Следующий ➡️",
                    callback_data=f"sched:day:{next_date}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📆 Показать неделю",
                    callback_data=f"sched:week:{week_start_iso}",
                ),
            ],
        ]

        if show_target_switch:
            buttons.append([
                InlineKeyboardButton(
                    text="🎯 Сменить цель",
                    callback_data="sched:targets",
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
                    callback_data=(
                        f"sched:day:{target_date.isoformat()}"
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
                callback_data=f"sched:week:{week_start_iso}",
            )
        else:
            details_button = InlineKeyboardButton(
                text="📋 Подробно всю неделю",
                callback_data=f"sched:full_week:{week_start_iso}",
            )

        buttons = [
            day_buttons[:3],
            day_buttons[3:],
            [details_button],
            [
                InlineKeyboardButton(
                    text="⬅️ Предыдущая неделя",
                    callback_data=f"sched:week:{previous_week}",
                ),
                InlineKeyboardButton(
                    text="Следующая неделя ➡️",
                    callback_data=f"sched:week:{next_week}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📅 К ближайшему дню",
                    callback_data="sched:smart_day",
                ),
            ],
        ]

        if show_target_switch:
            buttons.append([
                InlineKeyboardButton(
                    text="🎯 Сменить цель",
                    callback_data="sched:targets",
                )
            ])

        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )
    
    @staticmethod
    def get_schedule_targets_kb(
        targets: list[ScheduleViewTargetDTO],
        classes_dict: dict,
        groups_dict: dict,
    ) -> InlineKeyboardMarkup:
        """
        Выбор цели Schedule Hub.

        student — реальный или virtual student profile.
        watch — самостоятельный отслеживаемый класс.
        """
        buttons = []

        for target in targets:
            # Получаем человекочитаемое название группы для всех типов целей
            if not target.group_id or target.group_id == "ALL":
                group_text = "Весь класс"
            else:
                names = [
                    groups_dict.get(g.strip(), f"Группа {g.strip()}") 
                    for g in str(target.group_id).split(",")
                ]
                group_text = ", ".join(names)

            if target.kind == "student":
                icon = (
                    "📱"
                    if target.telegram_user_id is not None
                    else "🧒"
                )
                callback_data = (
                    f"sched:target:student:{target.target_id}"
                )

                # Для ученика выводим: Иконка · Имя · Класс · Группа
                class_name = classes_dict.get(target.class_id, target.class_id or "—")
                button_text = f"{icon} {target.title} · {class_name} · {group_text}"

            else:
                icon = "🎓"
                callback_data = (
                    f"sched:target:watch:{target.target_id}"
                )

                # Для отслеживаемого класса в title уже заложено имя класса, класс не дублируем
                button_text = f"{icon} {target.title} · {group_text}"

            buttons.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=callback_data,
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="settings:main",
            )
        ])

        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )
             
    @staticmethod
    def get_search_days_kb(target_id: str, is_teacher: bool, week_start_iso: str, is_full: bool = False) -> InlineKeyboardMarkup:
        from datetime import datetime, timedelta
        start_date = datetime.fromisoformat(week_start_iso).date()
        prefix = "sch_t" if is_teacher else "sch_c"

        days = []
        for i in range(6):  # Пн-Сб
            day_date_obj = start_date + timedelta(days=i)
            day_date_iso = day_date_obj.isoformat()
            day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"][i]
            
            # НОВОЕ: Динамическая подпись даты в кнопку
            btn_text = f"{day_name} {day_date_obj.strftime('%d.%m')}"
            days.append(InlineKeyboardButton(text=btn_text, callback_data=f"{prefix}:{target_id}:{day_date_iso}"))

        buttons = [days[0:3], days[3:6]]

        if not is_full:
            fw_cb = f"{prefix}_fw:{target_id}:{week_start_iso}"
            buttons.append([InlineKeyboardButton(text="📋 Все дни подробно", callback_data=fw_cb)])
        else:
            w_cb = f"{prefix}_w:{target_id}:{week_start_iso}"
            buttons.append([InlineKeyboardButton(text="🗓 По дням", callback_data=w_cb)])

        prev_week = (start_date - timedelta(days=7)).isoformat()
        next_week = (start_date + timedelta(days=7)).isoformat()

        buttons.append([
            InlineKeyboardButton(text="⬅️ Пред. нед", callback_data=f"{prefix}_w:{target_id}:{prev_week}"),
            InlineKeyboardButton(text="След. нед ➡️", callback_data=f"{prefix}_w:{target_id}:{next_week}")
        ])

        back_cb = "search:teachers" if is_teacher else "search:classes"
        buttons.append([InlineKeyboardButton(text="⬅️ Назад к списку", callback_data=back_cb)])

        return InlineKeyboardMarkup(inline_keyboard=buttons)

  
    # Клавиатуры для поиска классов и учителей

    @staticmethod
    def get_search_classes_kb(dto: ClassListDTO) -> InlineKeyboardMarkup:
        buttons = []
        row = []
        for c_id, c_name in dto.classes.items():
            row.append(InlineKeyboardButton(text=c_name, callback_data=f"srch_cls:{c_id}"))
            if len(row) == 4:  # По 4 класса в ряд
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="search:back")])
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
            row.append(InlineKeyboardButton(text=name_str, callback_data=f"srch_tch:{t_id}"))
            if len(row) == 2:  # По 2 учителя в ряд
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="search:back")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def get_family_management_error_kb() -> InlineKeyboardMarkup:
        """Клавиатура-заглушка для ребёнка без семьи."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Перерегистрироваться", callback_data="auth:restart")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:main")]
        ])
        
    # Клавитура семьи
    @staticmethod
    def get_family_management_kb(
        members: list[FamilyMemberDTO],
        current_user: UserProfileDTO,
        classes_dict: dict,
        is_family_admin: bool,
    ) -> InlineKeyboardMarkup:
        buttons = []

        # Любой parent/observer видит доступные семейные профили.
        # Конкретная проверка доступа к ученику остаётся в handler/service.
        if current_user.role in ("parent", "observer"):
            buttons.append([
                InlineKeyboardButton(
                    text="🧒 Ученики семьи",
                    callback_data="family:students",
                )
            ])
            
        # Только creator/admin семьи может выдавать invites.
        if is_family_admin:
            buttons.append([
                InlineKeyboardButton(
                    text="📨 Пригласить участника",
                    callback_data="family:invite_menu",
                )
            ])

            buttons.append([
                InlineKeyboardButton(
                    text="📬 Активные приглашения",
                    callback_data="family:invites",
                )
            ])
            
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ Назад к настройкам",
                callback_data="settings:main",
            )
        ])

        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )

      
    @staticmethod
    def get_extra_students_select_kb(
        students: list[StudentProfileDTO],
        classes_dict: dict,
        groups_dict: dict,
    ) -> InlineKeyboardMarkup:
        """
        Выбор student profile для работы с допзанятиями.

        Доступ к каждой кнопке уже предварительно отфильтрован
        StudentsService.get_students_for_adult(), но service всё равно
        повторно проверяет права на каждом действии.
        """
        buttons = []

        for student in students:
            icon = (
                "📱"
                if student.telegram_user_id is not None
                else "🧒"
            )

            # Получаем человекочитаемое имя класса
            class_name = classes_dict.get(student.class_id, student.class_id or "—")

            # Получаем человекочитаемое имя группы (с поддержкой мультигрупп)
            if not student.group_id or student.group_id == "ALL":
                group_text = "Весь класс"
            else:
                names = [
                    groups_dict.get(g.strip(), f"Группа {g.strip()}") 
                    for g in str(student.group_id).split(",")
                ]
                group_text = ", ".join(names)

            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"{icon} {student.name} "
                        f"· {class_name} "
                        f"· {group_text}"
                    ),
                    callback_data=f"extra:menu:{student.id}",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="settings:main",
            )
        ])

        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )
                

    @staticmethod
    def get_student_notification_select_kb(
        students: list[StudentProfileDTO],
        classes_dict: dict,
        groups_dict: dict,
    ) -> InlineKeyboardMarkup:
        """
        Выбор student profile для персональных подписок взрослого.

        В список передаются только профили, доступные текущему взрослому
        через StudentsService.get_students_for_adult().
        """
        buttons = []

        for student in students:
            icon = (
                "📱"
                if student.telegram_user_id is not None
                else "🧒"
            )

            # Получаем человекочитаемое имя класса
            class_name = classes_dict.get(student.class_id, student.class_id or "—")

            # Получаем человекочитаемое имя группы (с поддержкой мультигрупп)
            if not student.group_id or student.group_id == "ALL":
                group_label = "весь класс"
            else:
                names = [
                    groups_dict.get(g.strip(), f"группа {g.strip()}") 
                    for g in str(student.group_id).split(",")
                ]
                group_label = ", ".join(names)

            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"{icon} {student.name} "
                        f"· {class_name} "
                        f"· {group_label}"
                    ),
                    callback_data=f"psn:student:{student.id}",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К настройкам",
                callback_data="settings:main",
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
                        callback_data=(
                            f"psn:toggle:morning:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=(
                            "⏰ Напоминания об уроках: "
                            f"{status(dto.receive_pre_lesson_reminders)}"
                        ),
                        callback_data=(
                            f"psn:toggle:prelesson:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=(
                            "🔄 Изменения расписания: "
                            f"{status(dto.receive_schedule_changes)}"
                        ),
                        callback_data=(
                            f"psn:toggle:changes:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=(
                            "🎨 Доп. занятия: "
                            f"{status(dto.receive_extra_class_reminders)}"
                        ),
                        callback_data=(
                            f"psn:toggle:extra:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К ученикам",
                        callback_data="settings:children_notifications",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⚙️ Главные настройки",
                        callback_data="settings:main",
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
                    callback_data=(
                        "student_perm:toggle:"
                        f"{student_id}:"
                        f"{permission.adult_user_id}"
                    ),
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К профилю ученика",
                callback_data=f"student:show:{student_id}",
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
                        callback_data="auth:restart_confirm",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data="settings:main",
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
                        callback_data="family:invite_role:child",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="👨‍👩‍👧 Родителя",
                        callback_data="family:invite_role:parent",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="👁 Наблюдателя",
                        callback_data="family:invite_role:observer",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад к семье",
                        callback_data="settings:family",
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
                        callback_data="family:invite_menu",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К семье",
                        callback_data="settings:family",
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
                    callback_data=(
                        f"family:invite:{invite.id}"
                    ),
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="📨 Создать приглашение",
                callback_data="family:invite_menu",
            )
        ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К семье",
                callback_data="settings:family",
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
                        callback_data=(
                            f"family:invite_revoke:{invite_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К приглашениям",
                        callback_data="family:invites",
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
                        callback_data=(
                            f"family:invite_revoke_confirm:{invite_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data=f"family:invite:{invite_id}",
                    )
                ],
            ]
        )
        
        
        
    @staticmethod
    def get_watch_targets_menu_kb(
        targets: list[ScheduleWatchTargetDTO],
        classes_dict: dict,
        groups_dict: dict,
    ) -> InlineKeyboardMarkup:
        """
        Список самостоятельных классов пользователя.
        """
        buttons = []

        for target in targets:
            status = "🟢" if target.is_enabled else "⚫"

            # Вызываем внутренний хелпер
            class_name, group_name = Keyboards._format_class_and_group(
                target.class_id, target.group_id, classes_dict, groups_dict
            )
            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"{status} {target.title or class_name} · {group_name}"
                    ),
                    callback_data=f"watch:target:{target.id}",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="➕ Добавить класс",
                callback_data="watch:add",
            )
        ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К настройкам",
                callback_data="settings:main",
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
                    callback_data=f"watch:class:{class_id}",
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
                callback_data="watch:menu",
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
                    callback_data="watch:group:ALL",
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
                    callback_data=f"watch:group:{group_id}",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ Назад к выбору класса",
                callback_data="watch:add",
            )
        ])

        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )
        
    @staticmethod
    def get_watch_target_details_kb(
        target_id: int,
        is_enabled: bool,
        receive_schedule_changes: bool,
    ) -> InlineKeyboardMarkup:
        status_text = (
            "⚫ Выключить отслеживание"
            if is_enabled
            else "🟢 Включить отслеживание"
        )
        changes_text = (
            "🔄 Изменения: ВКЛ 🟢"
            if receive_schedule_changes
            else "🔄 Изменения: ВЫКЛ 🔴"
        )
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📅 Открыть расписание",
                        callback_data=f"watch:open:{target_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=changes_text,
                        callback_data=f"watch:changes:{target_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=status_text,
                        callback_data=f"watch:toggle:{target_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🗑 Удалить класс",
                        callback_data=f"watch:delete:{target_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К списку классов",
                        callback_data="watch:menu",
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
                        callback_data=(
                            f"watch:delete_confirm:{target_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data=f"watch:target:{target_id}",
                    )
                ],
            ]
        )
        
    @staticmethod
    def get_family_students_kb(
        students: list[StudentProfileDTO],
        classes_dict: dict,
        groups_dict: dict,
        *,
        is_family_admin: bool,
    ) -> InlineKeyboardMarkup:
        """
        Список student_profiles семьи.

        Parent/observer видит учеников, доступных через
        parent_student_settings. Family admin может добавить ученика.
        """
        buttons = []

        for student in students:
            telegram_status = (
                "📱"
                if student.telegram_user_id is not None
                else "🧒"
            )

            # Получаем человекочитаемое имя класса
            class_name = classes_dict.get(student.class_id, student.class_id or "—")

            # Получаем человекочитаемое имя группы
            if not student.group_id or student.group_id == "ALL":
                group_text = "Весь класс"
            else:
                names = [
                    groups_dict.get(g.strip(), f"Группа {g.strip()}") 
                    for g in str(student.group_id).split(",")
                ]
                group_text = ", ".join(names)

            buttons.append([
                InlineKeyboardButton(
                    text=(
                        f"{telegram_status} {student.name} "
                        f"· {class_name} "
                        f"· {group_text}"
                    ),
                    callback_data=f"student:show:{student.id}",
                )
            ])

        if is_family_admin:
            buttons.append([
                InlineKeyboardButton(
                    text="➕ Добавить ученика",
                    callback_data="student:add",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К семье",
                callback_data="settings:family",
            )
        ])

        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )
        
    @staticmethod
    def get_student_details_kb(
        *,
        student_id: int,
        telegram_user_id: int | None,
        is_family_admin: bool,
    ) -> InlineKeyboardMarkup:
        """
        Действия над student profile.

        Family admin:
        - меняет class/group;
        - управляет правами других взрослых на кружки;
        - создаёт claim link для virtual student;
        - удаляет только virtual student.

        Имя Telegram-linked ученика не меняется отсюда:
        ребёнок меняет его через осознанную перерегистрацию/claim.
        """
        buttons = []

        if is_family_admin:
            buttons.append([
                InlineKeyboardButton(
                    text="🎓 Изменить класс / группу",
                    callback_data=f"student:edit_class:{student_id}",
                )
            ])

            if telegram_user_id is not None:
                buttons.append([
                    InlineKeyboardButton(
                        text="📱 Настройки Telegram-ребёнка",
                        callback_data=(
                            f"student_tg:show:{student_id}"
                        ),
                    )
                ])
    
            buttons.append([
                InlineKeyboardButton(
                    text="👥 Права взрослых на кружки",
                    callback_data=f"student:extra_permissions:{student_id}",
                )
            ])

        if telegram_user_id is None and is_family_admin:
            buttons.append([
                InlineKeyboardButton(
                    text="📱 Привязать Telegram",
                    callback_data=f"student:claim:{student_id}",
                )
            ])

            buttons.append([
                InlineKeyboardButton(
                    text="🗑 Удалить ученика",
                    callback_data=f"student:delete:{student_id}",
                )
            ])

        if telegram_user_id is not None:
            buttons.append([
                InlineKeyboardButton(
                    text="📱 Telegram-профиль подключён",
                    callback_data=f"student:show:{student_id}",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К ученикам",
                callback_data="family:students",
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
                        callback_data=f"student:claim:{student_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К ученику",
                        callback_data=f"student:show:{student_id}",
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
                        callback_data="claim:confirm",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data="claim:cancel",
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
                    callback_data=f"student:class:{class_id}",
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
                callback_data="family:students",
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
                    callback_data="student:group:ALL",
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
                    callback_data=f"student:group:{group_id}",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К выбору класса",
                callback_data="student:add",
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
                        callback_data=(
                            f"student:delete_confirm:{student_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Отмена",
                        callback_data=f"student:show:{student_id}",
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
                        callback_data="claim:cancel",
                    )
                ]
            ]
        )
    if False:       
        @staticmethod
        def get_claim_class_selection_kb(
            dto: ClassListDTO,
        ) -> InlineKeyboardMarkup:
            buttons = []
            row = []

            for class_id, class_name in dto.classes.items():
                row.append(
                    InlineKeyboardButton(
                        text=class_name,
                        callback_data=f"claim:class:{class_id}",
                    )
                )

                if len(row) == 3:
                    buttons.append(row)
                    row = []

            if row:
                buttons.append(row)

            buttons.append([
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="claim:cancel",
                )
            ])

            return InlineKeyboardMarkup(
                inline_keyboard=buttons,
            )
            
        @staticmethod
        def get_claim_group_selection_kb(
            dto: GroupListDTO,
        ) -> InlineKeyboardMarkup:
            buttons = [
                [
                    InlineKeyboardButton(
                        text="Весь класс",
                        callback_data="claim:group:ALL",
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
                        callback_data=f"claim:group:{group_id}",
                    )
                ])

            buttons.append([
                InlineKeyboardButton(
                    text="⬅️ К выбору класса",
                    callback_data="claim:back_to_class",
                )
            ])

            buttons.append([
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="claim:cancel",
                )
            ])

            return InlineKeyboardMarkup(
                inline_keyboard=buttons,
            )    
            
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
                    callback_data=(
                        f"student:edit_class_select:"
                        f"{student_id}:{class_id}"
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
                callback_data=f"student:show:{student_id}",
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
                    callback_data=(
                        f"student:edit_group_select:"
                        f"{student_id}:ALL"
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
                    callback_data=(
                        f"student:edit_group_select:"
                        f"{student_id}:{group_id}"
                    ),
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К выбору класса",
                callback_data=f"student:edit_class:{student_id}",
            )
        ])

        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К профилю ученика",
                callback_data=f"student:show:{student_id}",
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
                    callback_data=f"reg_teacher:{teacher_id}",
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
                callback_data="reg_teacher:cancel",
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
                        callback_data=(
                            f"teacher_sched:day:{previous_date}"
                        ),
                    ),
                    InlineKeyboardButton(
                        text="Следующий ➡️",
                        callback_data=(
                            f"teacher_sched:day:{next_date}"
                        ),
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="📆 Показать неделю",
                        callback_data=(
                            f"teacher_sched:week:{week_start}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📅 К ближайшему дню",
                        callback_data="teacher_sched:smart_day",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⚙️ Настройки",
                        callback_data="settings:main",
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
                    callback_data=(
                        f"teacher_sched:day:"
                        f"{target_date.isoformat()}"
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
                callback_data=(
                    f"teacher_sched:week:{week_start_iso}"
                ),
            )
            if is_full
            else InlineKeyboardButton(
                text="📋 Подробно всю неделю",
                callback_data=(
                    f"teacher_sched:full_week:{week_start_iso}"
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
                        callback_data=(
                            f"teacher_sched:week:{previous_week}"
                        ),
                    ),
                    InlineKeyboardButton(
                        text="Следующая неделя ➡️",
                        callback_data=(
                            f"teacher_sched:week:{next_week}"
                        ),
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="📅 К ближайшему дню",
                        callback_data="teacher_sched:smart_day",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⚙️ Настройки",
                        callback_data="settings:main",
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
                    callback_data=(
                        f"teacher_change:{teacher_id}"
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
                callback_data="settings:main",
            )
        ])

        return InlineKeyboardMarkup(
            inline_keyboard=buttons,
        )