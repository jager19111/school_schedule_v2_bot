from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timedelta, timezone, date
from core.models.dto import (ClassListDTO, FamilyCreatedDTO, AdminStatsDTO, DayScheduleDTO, ChildrenListDTO, ExtraClassListDTO,
                             WeekSummaryDTO, FullWeekScheduleDTO, UserProfileDTO, FamilyMemberDTO,
                             MorningSummaryDTO, ChangeReminderDTO, LessonReminderDTO
)
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

#=======================
#Дополнительные занятия
#=======================

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

    @staticmethod
    def render_extra_class_locked() -> str:
        return "🔒 Редактирование и удаление занятий запрещено родителем."
    
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
    
    @staticmethod
    def render_extra_child_select() -> tuple[str, None]:
        return "👥 <b>Выберите ребенка</b>\n\nДля кого вы хотите настроить дополнительные занятия?", None

    @staticmethod
    def render_extra_no_children() -> tuple[str, None]:
        return "❌ У вас нет привязанных детей. Сначала добавьте ребенка в семью через меню настроек.", None
    
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
            f"✅ Вы успешно присоединены к семье!\n\n"
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
 
# под вопросом
    @staticmethod
    def render_parent_children_menu(dto: ChildrenListDTO) -> str:
        if not dto.children:
            return "К вашему профилю пока не привязан ни один ребенок. Используйте настройки семьи."
        return "Выберите ребенка для просмотра расписания:"
    
# Меню

    @staticmethod
    def render_school_search_menu() -> str:
        return "🏫 <b>Поиск по школе</b>\n\nВыберите нужный раздел:"
# На удаление
    @staticmethod
    def render_parent_settings_menu(family_code: str) -> str:
        code_text = f"<code>{family_code}</code>" if family_code else "Не в семье"
        return f"⚙️ <b>Ваши настройки и семья</b>\n\nКод вашей семьи: {code_text}\nВыберите действие:"

    @staticmethod
    def render_family_management_menu() -> str:
        return "👨‍👩‍👧 <b>Управление семьей</b>\n\nВыберите ребенка для настройки:"

    @staticmethod
    def render_child_settings_menu(name: str, class_id: str) -> str:
        cls_text = class_id if class_id else "Не выбран"
        return f"⚙️ <b>Настройки профиля:</b> {name} ({cls_text})"
    
    # В классе UIRenderer:

    @staticmethod
    def render_settings_main(
        user_dto: 'UserProfileDTO', 
        family_code: str | None,
        class_name: str | None = None,
        group_names: str | None = None
    ) -> str:
        role_map = {"parent": "👨‍👩‍👧 Родитель", "child": "👶 Ребёнок", "observer": "👁 Наблюдатель"}
        role_name = role_map.get(user_dto.role, "Неизвестно")
        name_str = user_dto.name if user_dto.name else "Не указано"
        code_str = f"<code>{family_code}</code>" if family_code else "Не в семье"
        
        text = f"⚙️ <b>Ваши настройки профиля, {name_str}</b>\n\n"
        text += f"👤 Роль: {role_name}\n"
        
        # Динамический вывод класса и групп только если они переданы
        if class_name:
            text += f"🎓 Класс: <b>{class_name}</b>\n"
            
        if group_names:
            text += f"👥 Группы: <b>{group_names}</b>\n"
            
        text += f"👨‍👩‍👧 Код семьи: {code_str}\n\n"
        text += "Выберите действие:"
        
        return text
    
 # Меню семьи 
    @staticmethod
    def render_family_members_menu(
        members: list['FamilyMemberDTO'], 
        current_user: 'UserProfileDTO', 
        classes_dict: dict
    ) -> str:
        text = "👨‍👩‍👧 <b>Ваша семья</b>\n\n"
        roles_ru = {"parent": "👨‍👩‍👧 Родитель", "child": "👶 Ребёнок", "observer": "👁 Наблюдатель"}
        
        # Сортируем: сначала взрослые, потом дети
        sorted_members = sorted(members, key=lambda m: 1 if m.role == 'child' else 0)
        
        for m in sorted_members:
            role_str = roles_ru.get(m.role, m.role)
            me_flag = " <i>(Вы)</i>" if m.user_id == current_user.user_id else ""
            
            if m.role == 'child':
                class_name = classes_dict.get(m.class_id, m.class_id) if m.class_id else "Класс не выбран"
                text += f"{role_str}: <b>{m.name}</b>{me_flag} — {class_name}\n"
            else:
                text += f"{role_str}: <b>{m.name}</b>{me_flag}\n"
                
        if current_user.role == 'parent':
            text += "\n⚙️ <i>Выберите ребенка ниже для настройки профиля:</i>"
        else:
            text += "\n🔒 <i>Управление настройками доступно только родителям.</i>"
            
        return text
    
    @staticmethod
    def render_family_management_error() -> str:
        return "👨‍👩‍👧 <b>Управление семьей</b>\n\nВы не состоите в семье. Обратитесь к администратору семьи, запросите код и перерегистрируйте учетную запись."

#    @staticmethod
#    def render_notifications_menu() -> str:
#        return "🔔 <b>Настройки уведомлений</b>\n\nЗдесь вы можете детально настроить, какие оповещения получать:"
    
# Сводка
    @staticmethod
    def render_summary_time_prompt(name: str | None = None) -> str:
        target = f" для {name}" if name else " вашей"
        return (
            f"⏰ Введите желаемое время{target} утренней сводки (например, 07:00, 7.30 или 715).\n\n"
            f"<i>Вы также можете полностью отключить утреннюю сводку кнопкой ниже.</i>"
        )

    @staticmethod
    def render_invalid_time_format() -> str:
        return "❌ Не удалось распознать время. Пожалуйста, введите в формате ЧЧ:ММ (например, 07:00)."
    
    
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
    # В классе UIRenderer:

    @staticmethod
    def render_child_day_schedule(dto: 'DayScheduleDTO', name: str | None = None) -> tuple[str, None]:
        if not dto.lessons:
            return f"{UIRenderer._format_date_header(dto.date_iso)}\n🏖 <b>Занятий нет</b>", None

        main_lessons = [l for l in dto.lessons if not l.get("is_extra")]
        extra_lessons = [l for l in dto.lessons if l.get("is_extra")]

        text = UIRenderer._format_date_header(dto.date_iso)

        if main_lessons:
            text += "\n"  # Просто отступ, без текста "Основное расписание"
            
            grouped_lessons = {}
            for l in main_lessons:
                num = l['lesson_num'] if l['lesson_num'] else 99
                if num not in grouped_lessons:
                    grouped_lessons[num] = []
                grouped_lessons[num].append(l)

            for num, parallel_lessons in grouped_lessons.items():
                first = parallel_lessons[0]
                
                # Читаем вычисленный номер (сдвиг для учеников, абсолютный для учителей)
                num_str = f"{first.get('display_num', '•')}." 
                time_str = f"{first['start_time']} - {first['end_time']}"
                
                if len(parallel_lessons) == 1:
                    l = first
                    icon = "🔄" if l['is_exchange'] else ("🚫" if l['is_cancelled'] else "📚")
                    room = f" → {l.get('room_name')}" if l.get('room_name') and l.get('room_name') != "—" else ""
                    name_str = "ОТМЕНА" if l['is_cancelled'] else (l.get('subject_name') or "Без предмета")
                    grp_label = f" ({l.get('group_name')})" if l.get('group_id') != "ALL" and l.get('group_name') else ""
                    
                    # Подтягиваем название класса (для расписания учителя)
                    c_name = l.get('class_name')
                    class_label = f" [{c_name}]" if c_name else ""
                    
                    text += f"{icon} {num_str} {time_str} | {name_str}{grp_label}{class_label}{room}\n"
                else:
                    text += f"📚 {num_str} {time_str}\n"
                    for i, l in enumerate(parallel_lessons):
                        is_last = (i == len(parallel_lessons) - 1)
                        prefix = " └ " if is_last else " ├ "
                        
                        icon = "🔄" if l['is_exchange'] else ("🚫" if l['is_cancelled'] else "")
                        icon_str = f"{icon} " if icon else ""
                        room = f" → {l.get('room_name')}" if l.get('room_name') and l.get('room_name') != "—" else ""
                        name_str = "ОТМЕНА" if l['is_cancelled'] else (l.get('subject_name') or "Без предмета")
                        grp_name = l.get('group_name') or f"Группа {l.get('group_id')}"
                        grp_label = f" ({grp_name})" if l.get('group_id') != "ALL" else ""
                        
                        # Подтягиваем название класса
                        c_name = l.get('class_name')
                        class_label = f" [{c_name}]" if c_name else ""
                        
                        text += f"  {prefix}{icon_str}{name_str}{grp_label}{class_label}{room}\n"

        if extra_lessons:
            text += "\n🎨 <b>Доп. занятия</b>\n\n"
            for i, l in enumerate(extra_lessons, 1):
                room = f" → {l.get('room_name')}" if l.get('room_name') and l.get('room_name') != "—" else ""
                text += f"🎸 {i}. {l['start_time']} - {l['end_time']} | {l['subject_name']}{room}\n"

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
        return f"📅 Выберите день недели для: <b>{name}</b>"
    
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

    # Доработать!. TODO: Возможно, стоит удалить или объединить с render_notifications_menu
    @staticmethod
    def render_notifications_menu(user_dto: 'UserProfileDTO') -> str:
        text = "🔔 <b>Настройки уведомлений</b>\n\n"
        text += f"1️⃣ Уведомления о заменах и отменах уроков: {'✅ Включены' if user_dto.can_edit_extra_classes else '❌ Выключены'}\n"
        text += f"2️⃣ Уведомления о дополнительных занятиях: {'✅ Включены' if user_dto.global_extra_reminder else '❌ Выключены'}\n"
        text += f"3️⃣ Утренние сводки: {'✅ Включены' if user_dto.morning_summary_time else '❌ Выключены'}\n"
        if user_dto.morning_summary_time:
            text += f"   ⏰ Время утренней сводки: {user_dto.morning_summary_time}\n"
        return text
    
    @staticmethod
    def render_lesson_reminder(dto: 'LessonReminderDTO') -> str:
        icon = "🎨" if dto.is_extra else "🔔"
        lesson_type = "Доп. занятие" if dto.is_extra else "Урок"
        child_str = f" для <b>{dto.child_name}</b>" if dto.child_name else ""
        return f"{icon} {lesson_type}{child_str}: <b>{dto.subject_name}</b> начнется в {dto.start_time} (каб. {dto.room_name})"

    @staticmethod
    def render_change_reminder(dto: 'ChangeReminderDTO') -> str:
        status = "🚫 ОТМЕНЕН" if dto.is_cancelled else "🔄 ИЗМЕНЕН"
        child_str = f" (<b>{dto.child_name}</b>)" if dto.child_name else ""
        return f"❗️ Внимание! {dto.date} урок №{dto.lesson_num}{child_str} ({dto.subject_name}) {status}."

    @staticmethod
    def render_morning_summary(dto: 'MorningSummaryDTO') -> str:
        from datetime import datetime
        date_obj = datetime.fromisoformat(dto.date_iso)
        date_str = date_obj.strftime('%d.%m')
        
        header = f"🌅 <b>Утренняя сводка на сегодня ({date_str})</b>"
        if dto.child_name:
            header += f"\n👤 <b>{dto.child_name} ({dto.class_id})</b>"
            
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
                    room = f" → {l.room_name}" if l.room_name and l.room_name != "—" else ""
                    name_str = "ОТМЕНА" if l.is_cancelled else (l.subject_name or "Без предмета")
                    grp_label = f" ({l.group_name})" if l.group_name else ""
                    
                    text += f"{icon} {num_str} {time_str} | {name_str}{grp_label}{room}\n"
                else:
                    text += f"📚 {num_str} {time_str}\n"
                    for i, l in enumerate(parallel):
                        is_last = (i == len(parallel) - 1)
                        prefix = " └ " if is_last else " ├ "
                        
                        icon = "🔄" if l.is_exchange else ("🚫" if l.is_cancelled else "")
                        icon_str = f"{icon} " if icon else ""
                        room = f" → {l.room_name}" if l.room_name and l.room_name != "—" else ""
                        name_str = "ОТМЕНА" if l.is_cancelled else (l.subject_name or "Без предмета")
                        grp_label = f" ({l.group_name})" if l.group_name else ""
                        
                        text += f"  {prefix}{icon_str}{name_str}{grp_label}{room}\n"
                        
        if extra_lessons:
            text += "\n🎨 <b>Доп. занятия</b>\n"
            for i, l in enumerate(extra_lessons, 1):
                room = f" → {l.room_name}" if l.room_name and l.room_name != "—" else ""
                text += f"🎸 {i}. {l.start_time} - {l.end_time} | {l.subject_name}{room}\n"
                
        return text + "\n"