from typing import Any, Dict, List, Optional, Set
from core.models.dto import ClassListDTO, FamilyCreatedDTO, AdminStatsDTO, DayScheduleDTO, ChildrenListDTO, ExtraClassListDTO

class UIRenderer:
    @staticmethod
    def render_role_selection() -> str:
        return "Добро пожаловать! Выберите вашу роль:"

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
    DAYS_MAP = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}
    # Клавиатура
    @staticmethod
    def render_extra_classes_menu() -> tuple[str, None]:
        return "🎨 <b>Дополнительные занятия</b>\n\nУправление кружками и секциями:", None

    @staticmethod
    def render_extra_class_time_start() -> tuple[str, None]:
        return "Введите время начала занятия (ЧЧ:ММ):", None

    @staticmethod
    def render_extra_class_time_end() -> tuple[str, None]:
        return "Введите время окончания занятия (ЧЧ:ММ):", None

    @staticmethod
    def render_extra_class_title() -> tuple[str, None]:
        return "Введите название занятия (например, \"Футбол\"):", None

    @staticmethod
    def render_extra_class_invalid_time() -> tuple[str, None]:
        return "❌ Неверный формат! Введите время в формате ЧЧ:ММ (например, 15:30).", None

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
    def render_extra_classes_list(dto: ExtraClassListDTO) -> tuple[str, None]:
        if not dto.items:
            return "📋 <b>Список дополнительных занятий пуст.</b>", None

        text = "📋 <b>Ваши дополнительные занятия:</b>\n\n"
        for item in dto.items:
            day_str = UIRenderer.DAYS_MAP.get(item.day_of_week, "Неизвестно")
            text += f"ID: <code>{item.id}</code> | {day_str} {item.time_start}-{item.time_end}\n"
            text += f"Название: <b>{item.title}</b>\n"
            text += "───────────────\n"

        return text, None

    @staticmethod
    def render_extra_class_delete_prompt(dto: ExtraClassListDTO) -> tuple[str, None]:
        if not dto.items:
            return "Список пуст. Удалять нечего.", None
        
        text, _ = UIRenderer.render_extra_classes_list(dto)
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
    def render_family_created(dto: FamilyCreatedDTO) -> str:
        return (
            f"✅ <b>Семья успешно создана!</b>\n\n"
            f"🔑 Ваш код семьи: <code>{dto.family_code}</code>\n\n"
            f"Передайте этот код детям или родственникам для присоединения.\n"
            f"Настройка завершена. Вы можете просматривать расписание через меню."
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
    def render_success_join() -> str:
        return "✅ Вы успешно присоединены к семье!"

    @staticmethod
    def render_error_join() -> str:
        return "❌ Код не найден. Проверьте правильность и отправьте его снова, либо нажмите /start."

    @staticmethod
    def render_final_success() -> str:
        return "✅ Регистрация завершена! Расписание доступно через меню."

    @staticmethod
    def render_main_menu() -> str:
        return "Главное меню:"

    @staticmethod
    def render_already_registered() -> str:
        return "Вы уже зарегистрированы! Воспользуйтесь меню ниже:"
    
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
    
