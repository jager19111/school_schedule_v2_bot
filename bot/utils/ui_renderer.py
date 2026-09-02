from typing import Any, Dict, List, Optional, Set
from core.models.dto import ClassListDTO, FamilyCreatedDTO, AdminStatsDTO, DayScheduleDTO, ChildrenListDTO, ExtraClassListDTO

class UIRenderer:
    
    @staticmethod
    def render_role_selection() -> str:
        return "Добро пожаловать! Выберите вашу роль:"

    @staticmethod
    def render_name_prompt() -> str:
        return "Как к вам обращаться? Введите ваше имя (например, Иван или Лиза):"
    
    @staticmethod
    def render_unregistered_error() -> str:
        return "Пожалуйста, сначала пройдите регистрацию (/start) или выберите класс в настройках."

    @staticmethod
    def render_access_denied() -> str:
        return "Эта команда доступна только для вашей текущей роли."

    @staticmethod
    def render_settings_menu() -> str:
        return "⚙️ Меню настроек:"

    @staticmethod
    def render_extra_class_time_start() -> str:
        return "Введите время начала занятия (ЧЧ:ММ):"

    @staticmethod
    def render_extra_class_time_end() -> str:
        return "Введите время окончания занятия (ЧЧ:ММ):"

    @staticmethod
    def render_extra_class_invalid_time() -> str:
        return "❌ Неверный формат! Введите время в формате ЧЧ:ММ (например, 15:30)."
    
    @staticmethod
    def render_parent_family_action() -> str:
        return "Вы хотите создать новую семью или присоединиться к уже существующей?"

    @staticmethod
    def render_child_family_action() -> str:
        return "Вы можете присоединиться к семье (чтобы родители помогали с настройками) или продолжить самостоятельно:"
        
    @staticmethod
    def render_family_code_prompt() -> str:
        return "Введите код семьи (family_code) для подключения:"
# ---------------
# Доп занятия # handlers/extra_classes
# ---------------
    DAYS_MAP_SHORT = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}
    # Клавиатура
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
        return "❌ Неверный формат! Введите число (например, 15) или '-':", None
    
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
# Словарь с полными названиями дней недели
    FULL_DAYS_MAP = {
        1: "Понедельник", 2: "Вторник", 3: "Среда", 
        4: "Четверг", 5: "Пятница", 6: "Суббота", 7: "Воскресенье"
    }
   
    @staticmethod
    def render_extra_classes_list(dto: 'ExtraClassListDTO', show_id: bool = False) -> tuple[str, None]:
        if not dto.items:
            return "📋 <b>Список дополнительных занятий пуст.</b>", None

        text = "📋 <b>Ваши дополнительные занятия:</b>\n\n"
        current_day = None

        # Гарантируем сортировку по дню недели и времени начала
        sorted_items = sorted(dto.items, key=lambda x: (x.day_of_week, x.time_start))

        for item in sorted_items:
            # 1. Группировка: выводим заголовок дня только при его смене
            if item.day_of_week != current_day:
                current_day = item.day_of_week
                day_name = UIRenderer.FULL_DAYS_MAP.get(current_day, "Неизвестно")
                text += "───────────────\n"
                text += f"📅 <b>{day_name}</b>\n"
                text += "───────────────\n"
            # 2. Очистка локации от технических дефисов
            loc_str = item.location if item.location and str(item.location).strip() != "-" else "Не указано"
            
            # 3. Вывод строки времени (без дублирования дня недели)
            if show_id:
                # Используем тег <code> для удобного копирования ID на телефонах
                text += f"ID: <code>{item.id}</code> | 🕐 {item.time_start}-{item.time_end}\n"
            else:
                text += f"🕐 {item.time_start}-{item.time_end}\n"
                
            text += f"📝 Занятие: <b>{item.title}</b>\n"
            text += f"📍 Место: {loc_str}\n"
            text += f"⏰ Напоминание: {item.reminder_minutes}мин\n"
            text += " \n"

        return text, None
    
    @staticmethod
    def render_extra_class_edit_prompt(dto: ExtraClassListDTO) -> tuple[str, None]:
        if not dto.items:
            return "Список пуст. Изменять нечего.", None
        text, _ = UIRenderer.render_extra_classes_list(dto, show_id=True)
        text += "\n✏️ <b>Введите ID занятия для изменения:</b>"
        return text, None

    @staticmethod
    def render_extra_class_edit_field_select() -> tuple[str, None]:
        return "Что именно вы хотите изменить?", None

    @staticmethod
    def render_extra_class_updated() -> tuple[str, None]:
        return "✅ Занятие успешно обновлено.", None

        return text, None

    @staticmethod
    def render_extra_class_delete_prompt(dto: ExtraClassListDTO) -> tuple[str, None]:
        if not dto.items:
            return "Список пуст. Удалять нечего.", None
        text, _ = UIRenderer.render_extra_classes_list(dto, show_id=True) # <-- ИЗМЕНЕНО
        text += "\n🗑 <b>Введите ID занятия для удаления:</b>"
        return text, None
        
    @staticmethod
    def render_extra_class_deleted() -> tuple[str, None]:
        return "✅ Занятие успешно удалено.", None
        
    @staticmethod
    def render_extra_class_not_found() -> tuple[str, None]:
        return "❌ Занятие с таким ID не найдено или вам не принадлежит. Введите правильный ID:", None
 # ---------------   
    @staticmethod
    def render_already_registered(name: str | None) -> str:
        greeting = f", {name}" if name else ""
        return (
            f"👋 С возвращением{greeting}!\n\n"
            f"Вы уже зарегистрированы. Воспользуйтесь меню ниже:"
        )

    @staticmethod
    def render_final_success(name: str | None) -> str:
        greeting = f", {name}" if name else ""
        return (
            f"✅ Привет{greeting}! Регистрация завершена!\n\n"
            f"🤖 <b>Что я умею:</b>\n"
            f"• Показывать твое расписание на день и неделю\n"
            f"• Уведомлять о заменах и отменах уроков\n"
            f"• Напоминать о кружках и доп. занятиях\n\n"
            f"Расписание доступно через главное меню ⬇️"
        )

    @staticmethod
    def render_success_join(name: str | None) -> str:
        greeting = f", {name}" if name else ""
        return (
            f"✅ Привет{greeting}! Вы успешно присоединены к семье!\n\n"
            f"🤖 <b>Что я умею:</b>\n"
            f"• Отображать расписание детей\n"
            f"• Присылать уведомления об изменениях в уроках\n"
            f"• Помогать в управлении дополнительными занятиями\n\n"
            f"Настройка завершена. Расписание доступно через меню ⬇️"
        )

    @staticmethod
    def render_family_created(dto: FamilyCreatedDTO, name: str | None) -> str:
        greeting = f", {name}" if name else ""
        return (
            f"✅ Привет{greeting}! <b>Семья успешно создана!</b>\n\n"
            f"🔑 Ваш код семьи: <code>{dto.family_code}</code>\n\n"
            f"Передайте этот код детям или родственникам для присоединения.\n\n"
            f"🤖 <b>Что я умею:</b>\n"
            f"• Показывать актуальное расписание ваших детей\n"
            f"• Держать вас в курсе отмен и замен уроков\n"
            f"• Контролировать внеурочные занятия\n\n"
            f"Настройка завершена. Вы можете просматривать расписание через меню ⬇️"
        )
        
    @staticmethod
    def render_class_selection(dto: ClassListDTO) -> str:
        if not dto.classes:
            return "❌ Расписание еще не загружено. Подождите и нажмите /start."
        return "Выберите ваш класс:"

    @staticmethod
    def render_group_selection() -> str:
        return "Выберите вашу группу (или 'Весь класс'):"

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
 
    @staticmethod
    def render_child_day_schedule(dto: DayScheduleDTO) -> str:
        if not dto.lessons:
            return f"На сегодня ({dto.date_iso}) уроков не найдено или расписание еще не загружено."
            
        text_lines = [f"📅 <b>Расписание на сегодня ({dto.date_iso})</b>\n"]
        for l in dto.lessons:
            if l.get("is_extra"):
                label = " (Доп. занятие)"
            else:
                label = ""

            status = "🚫 ОТМЕНЕН" if l['is_cancelled'] else ("🔄 (Замена)" if l['is_exchange'] else "")
            room = f"каб. {l.get('room_name', '—')}"
            num = l['lesson_num'] if l['lesson_num'] is not None else "•"

            text_lines.append(
                f"{num}. {l['start_time']}-{l['end_time']} | <b>{l['subject_name']}{label}</b> {room} {status}"
            )
        return "\n".join(text_lines)

    @staticmethod
    def render_parent_children_menu(dto: ChildrenListDTO) -> str:
        if not dto.children:
            return "К вашему профилю пока не привязан ни один ребенок. Используйте настройки семьи."
        return "Выберите ребенка для просмотра расписания:"
    
