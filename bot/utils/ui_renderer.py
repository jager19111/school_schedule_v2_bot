from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from core.models.dto import ClassListDTO, GroupListDTO, FamilyCreatedDTO, AdminStatsDTO
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

class UIRenderer:
    @staticmethod
    def render_role_selection() -> tuple[str, InlineKeyboardMarkup]:
        text = "Добро пожаловать! Выберите вашу роль:"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👶 Ребёнок", callback_data="role:child")],
            [InlineKeyboardButton(text="👨‍👩‍👧 Родитель", callback_data="role:parent")],
            [InlineKeyboardButton(text="👁 Наблюдатель", callback_data="role:observer")]
        ])
        return text, kb

    @staticmethod
    def render_parent_family_action() -> tuple[str, InlineKeyboardMarkup]:
        text = "Вы хотите создать новую семью или присоединиться к уже существующей?"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Создать новую семью", callback_data="family:create")],
            [InlineKeyboardButton(text="🔗 Присоединиться по коду", callback_data="family:join")]
        ])
        return text, kb

    @staticmethod
    def render_child_family_action() -> tuple[str, InlineKeyboardMarkup]:
        text = "Вы можете присоединиться к семье (чтобы родители помогали с настройками) или продолжить самостоятельно:"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Присоединиться к семье", callback_data="family:join")],
            [InlineKeyboardButton(text="▶️ Продолжить без семьи", callback_data="family:skip")]
        ])
        return text, kb
        
    @staticmethod
    def render_family_code_prompt() -> tuple[str, None]:
        return "Введите код семьи (family_code) для подключения:", None

    @staticmethod
    def render_family_created(dto: FamilyCreatedDTO) -> tuple[str, None]:
        text = (
            f"✅ <b>Семья успешно создана!</b>\n\n"
            f"🔑 Ваш код семьи: <code>{dto.family_code}</code>\n\n"
            f"Передайте этот код детям или родственникам для присоединения.\n"
            f"Настройка завершена. Вы можете просматривать расписание через меню."
        )
        return text, None

    @staticmethod
    def render_class_selection(dto: ClassListDTO) -> tuple[str, InlineKeyboardMarkup]:
        if not dto.classes:
            return "❌ Расписание еще не загружено. Подождите и нажмите /start.", None
            
        text = "Выберите ваш класс:"
        buttons = []
        row = []
        for c_id, c_name in dto.classes.items():
            row.append(InlineKeyboardButton(text=c_name, callback_data=f"class:{c_id}"))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        return text, InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def render_group_selection(dto: GroupListDTO) -> tuple[str, InlineKeyboardMarkup]:
        text = "Выберите вашу группу (или 'Весь класс'):"
        buttons = [[InlineKeyboardButton(text="Весь класс (без групп)", callback_data="group:ALL")]]
        for g_id, g_name in dto.groups.items():
            buttons.append([InlineKeyboardButton(text=g_name, callback_data=f"group:{g_id}")])
        return text, InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def render_success_join() -> tuple[str, None]:
        return "✅ Вы успешно присоединены к семье!", None

    @staticmethod
    def render_error_join() -> tuple[str, None]:
        return "❌ Код не найден. Проверьте правильность и отправьте его снова, либо нажмите /start.", None

    @staticmethod
    def render_final_success() -> tuple[str, None]:
        return "✅ Регистрация завершена! Расписание доступно через меню.", None
    

    @staticmethod
    def render_main_menu() -> tuple[str, ReplyKeyboardMarkup]:
        """Отрисовка постоянной нижней клавиатуры[cite: 1, 2]."""
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="🗓 Завтра")],
                [KeyboardButton(text="📆 Вся неделя")],
                [KeyboardButton(text="➕ Доп. занятия"), KeyboardButton(text="⚙️ Настройки")]
            ],
            resize_keyboard=True
        )
        return "Главное меню:", kb

    @staticmethod
    def render_already_registered() -> tuple[str, ReplyKeyboardMarkup]:
        text, kb = UIRenderer.render_main_menu()
        return "Вы уже зарегистрированы! Воспользуйтесь меню ниже:", kb
    
    @staticmethod
    def render_admin_stats(dto: AdminStatsDTO) -> tuple[str, None]:
        """UI Renderer превращает DTO в HTML-текст[cite: 1]."""
        text = f"📊 <b>Статистика пользователей (Всего: {dto.total_users}):</b>\n\n"
        for role, count in dto.role_distribution.items():
            text += f"- {role}: {count}\n"
        return text, None    
    
    