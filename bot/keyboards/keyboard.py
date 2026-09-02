from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from core.models.dto import ClassListDTO, GroupListDTO, ChildrenListDTO, UserProfileDTO

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

    @staticmethod
    def get_main_menu() -> ReplyKeyboardMarkup:
        """Отрисовка постоянной нижней клавиатуры."""
        kb = [
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="🗓 Завтра")],
            [KeyboardButton(text="📆 Вся неделя")],
            [KeyboardButton(text="➕ Доп. занятия"), KeyboardButton(text="⚙️ Настройки")]
        ]
        return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

    @staticmethod
    def get_parent_children_menu(dto: ChildrenListDTO) -> InlineKeyboardMarkup | None:
        if not dto.children:
            return None
            
        buttons = []
        for child in dto.children:
            btn_text = f"👦/👧 {child.name} ({child.class_id})"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"p_{dto.action}:{child.user_id}")])
            
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
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
        buttons = [
            [InlineKeyboardButton(text="➕ Добавить занятие", callback_data="extra:add")],
            [InlineKeyboardButton(text="📋 Список занятий", callback_data="extra:list")],
            [InlineKeyboardButton(text="🗑 Удалить занятие", callback_data="extra:delete")]
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
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