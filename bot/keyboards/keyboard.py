from datetime import datetime, timedelta, timezone, date
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from core.models.dto import ClassListDTO, GroupListDTO, ChildrenListDTO, UserProfileDTO, TeacherListDTO

class Keyboards:
    @staticmethod
    def get_role_selection() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👶 Ребёнок", callback_data="role:child")],
            [InlineKeyboardButton(text="👨‍👩‍👧 Родитель", callback_data="role:parent")],
            [InlineKeyboardButton(text="👁 Наблюдатель", callback_data="role:observer")]
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
    def get_group_selection(dto: GroupListDTO) -> InlineKeyboardMarkup:
        buttons = [[InlineKeyboardButton(text="Весь класс (без групп)", callback_data="group:ALL")]]
        for g_id, g_name in dto.groups.items():
            buttons.append([InlineKeyboardButton(text=g_name, callback_data=f"group:{g_id}")])
            
        return InlineKeyboardMarkup(inline_keyboard=buttons)

# Основное меню

    @staticmethod
    def get_main_menu() -> ReplyKeyboardMarkup:
        """Универсальная нижняя клавиатура для всех ролей."""
        kb = [
            [KeyboardButton(text="📅 Мое расписание")],
            [KeyboardButton(text="📆 Моя неделя"), KeyboardButton(text="➕ Доп. занятия")],
            [KeyboardButton(text="🏫 Поиск по школе"), KeyboardButton(text="⚙️ Настройки")]
        ]
        return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

    @staticmethod
    def get_school_search_kb() -> InlineKeyboardMarkup:
        """Меню поиска по школе."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎓 Расписание классов", callback_data="search:classes")],
            [InlineKeyboardButton(text="👨‍🏫 Расписание учителей", callback_data="search:teachers")]
        ])

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
    def get_family_management_kb(dto: 'ChildrenListDTO') -> InlineKeyboardMarkup:
        """Список детей для управления."""
        buttons = []
        if dto.children:
            for child in dto.children:
                btn_text = f"👦/👧 {child.name} ({child.class_id or '?'})"
                buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"family:child_settings:{child.user_id}")])
        buttons.append([InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="settings:main")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def get_child_settings_kb(child_dto: 'UserProfileDTO') -> InlineKeyboardMarkup:
        """Точечные настройки конкретного ребенка."""
        notif_status = "ВКЛ 🟢" if child_dto.is_notifications_enabled else "ВЫКЛ 🔴"
        summary_time = child_dto.morning_summary_time if child_dto.morning_summary_time else "ВЫКЛ"
        parent_notif = "ВКЛ 🟢" if child_dto.notify_parent_about_me else "ВЫКЛ 🔴"
        lock_status = "ВКЛ 🔴" if child_dto.parent_control_notifications else "ВЫКЛ 🟢"

        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎓 Изменить класс/группу", callback_data=f"child_set:class:{child_dto.user_id}")],
            [InlineKeyboardButton(text=f"🔔 Уведомления {child_dto.name}: {notif_status}", callback_data=f"child_set:notif:{child_dto.user_id}")],
            [InlineKeyboardButton(text=f"⏰ Время сводки {child_dto.name}: {summary_time}", callback_data=f"child_set:time:{child_dto.user_id}")],
            [InlineKeyboardButton(text=f"📱 Присылать сводки мне: {parent_notif}", callback_data=f"child_set:parent_notif:{child_dto.user_id}")],
            [InlineKeyboardButton(text=f"🔒 Запрет изменения настроек: {lock_status}", callback_data=f"child_set:lock:{child_dto.user_id}")],
            [InlineKeyboardButton(text="⬅️ Назад к составу семьи", callback_data="settings:family")]
        ])
#-----------------------

    @staticmethod
    def get_settings_menu(user_dto: UserProfileDTO) -> InlineKeyboardMarkup:
        """Динамическая клавиатура настроек на основе DTO[cite: 4]."""
        kb_lines = [
            [InlineKeyboardButton(text="🎓 Сменить класс", callback_data="settings:change_class")],
            [InlineKeyboardButton(text="📚 Сменить группу", callback_data="settings:change_group")]
        ]
        
        # Блокировка настроек уведомлений для ребенка, если включен контроль[cite: 3]
        if not (user_dto.role == 'child' and user_dto.parent_control_notifications):
            kb_lines.append([InlineKeyboardButton(text="🔔 Настройки уведомлений", callback_data="settings:notifications")])
            
        return InlineKeyboardMarkup(inline_keyboard=kb_lines)

    @staticmethod
    def get_parent_children_menu(dto: ChildrenListDTO) -> InlineKeyboardMarkup | None:
        """Клавиатура со списком детей[cite: 4]."""
        if not dto.children:
            return None
            
        buttons = []
        for child in dto.children:
            btn_text = f"👦/👧 {child.name} ({child.class_id})"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"p_{dto.action}:{child.user_id}")])
            
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    # Доп занятия  ExtraClassesService
    @staticmethod
    def get_extra_classes_menu() -> InlineKeyboardMarkup:
        """Клавиатура управления доп. занятиями."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить занятие", callback_data="extra:add")],
            [InlineKeyboardButton(text="📋 Список занятий", callback_data="extra:list")],
            [InlineKeyboardButton(text="✏️ Изменить занятие", callback_data="extra:edit")], # <-- ДОБАВЛЕНО
            [InlineKeyboardButton(text="🗑 Удалить занятие", callback_data="extra:delete")]
        ])
 #       ]
 #       return InlineKeyboardMarkup(inline_keyboard=buttons)
 
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
    def get_back_to_extra_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="extra:menu")]
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
        
    # Сводка
    @staticmethod
    def get_summary_time_prompt_kb() -> InlineKeyboardMarkup:
        """Клавиатура при запросе времени для сводки."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔕 Выключить сводку", callback_data="set_time:off")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="settings:cancel_input")]
        ])
        
        
        
# Просмотр расписания

    @staticmethod
    def get_day_nav_kb(current_date_iso: str) -> InlineKeyboardMarkup:
        """Клавиатура: Предыдущий / Следующий день."""
        curr_date = datetime.fromisoformat(current_date_iso).date()
        prev_date = (curr_date - timedelta(days=1)).isoformat()
        next_date = (curr_date + timedelta(days=1)).isoformat()
        
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️ Предыдущий", callback_data=f"sched:day:{prev_date}"),
                InlineKeyboardButton(text="Следующий ➡️", callback_data=f"sched:day:{next_date}")
            ]
        ])

    @staticmethod
    def get_week_nav_kb(week_start_iso: str, is_full: bool = False) -> InlineKeyboardMarkup:
        """Клавиатура недельного меню."""
        start_date = datetime.fromisoformat(week_start_iso).date()
        prev_week = (start_date - timedelta(days=7)).isoformat()
        next_week = (start_date + timedelta(days=7)).isoformat()
        
        days = []
        for i in range(6): # Пн-Сб
            day_date = (start_date + timedelta(days=i)).isoformat()
            day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"][i]
            days.append(InlineKeyboardButton(text=day_name, callback_data=f"sched:day:{day_date}"))
            
        buttons = [
            days[0:3],
            days[3:6]
        ]
        
        if not is_full:
            buttons.append([InlineKeyboardButton(text="📋 Все дни подробно", callback_data=f"sched:fullweek:{week_start_iso}")])
        else:
            buttons.append([InlineKeyboardButton(text="🗓 Краткая сводка", callback_data=f"sched:week:{week_start_iso}")])
            
        buttons.append([
            InlineKeyboardButton(text="⬅️ Пред. неделя", callback_data=f"sched:week:{prev_week}"),
            InlineKeyboardButton(text="След. неделя ➡️", callback_data=f"sched:week:{next_week}")
        ])
        
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

    # В классе Keyboards:

    @staticmethod
    def get_search_days_kb(target_id: str, is_teacher: bool, week_start_iso: str, is_full: bool = False) -> InlineKeyboardMarkup:
        from datetime import datetime, timedelta
        start_date = datetime.fromisoformat(week_start_iso).date()
        prefix = "sch_t" if is_teacher else "sch_c"

        days = []
        for i in range(6):  # Пн-Сб
            day_date = (start_date + timedelta(days=i)).isoformat()
            day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"][i]
            days.append(InlineKeyboardButton(text=day_name, callback_data=f"{prefix}:{target_id}:{day_date}"))

        buttons = [days[0:3], days[3:6]]

        # НОВОЕ: Кнопка полной недели
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