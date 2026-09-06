from html import escape
from datetime import datetime, timedelta, timezone, date
from core.models.dto import (ClassListDTO, FamilyCreatedDTO, AdminStatsDTO, DayScheduleDTO, ChildrenListDTO, ExtraClassListDTO,
                             WeekSummaryDTO, FullWeekScheduleDTO, UserProfileDTO, FamilyMemberDTO,
                             MorningSummaryDTO, ChangeReminderDTO, LessonReminderDTO, ParentChildNotificationSettingsDTO, AdultExtraClassesPermissionDTO,
                             ProfileResetImpactDTO, FamilyInviteDTO, ScheduleWatchTargetDTO, StudentProfileDTO,
)

class UIRenderer:

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
    def render_parent_family_action() -> str:
        return "Вы хотите создать новую семью или присоединиться к уже существующей?"

    @staticmethod
    def render_child_family_action() -> str:
        return "Вы можете присоединиться к семье (чтобы родители помогали с настройками) или продолжить самостоятельно:"
        
    @staticmethod
    def render_family_code_prompt() -> str:
        return "Введите код семьи (family_code) для подключения:"

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
   
    @staticmethod
    def render_extra_classes_list(dto: 'ExtraClassListDTO', show_id: bool = False) -> tuple[str, None]:
        if not dto.items:
            return "📋 <b>Список дополнительных занятий пуст.</b>", None

        text = "📋 <b>Ваши дополнительные занятия:</b>\n\n"
        current_day = None

        sorted_items = sorted(dto.items, key=lambda x: (x.day_of_week, x.time_start))

        for item in sorted_items:
            if item.day_of_week != current_day:
                current_day = item.day_of_week
                day_name = UIRenderer.FULL_DAYS_MAP.get(current_day, "Неизвестно")
                text += "───────────────\n"
                text += f"📅 <b>{day_name}</b>\n"
                text += "───────────────\n"
            
            # ЭКРАНИРОВАНИЕ
            safe_loc = UIRenderer.escape_html(item.location, "Не указано")
            safe_title = UIRenderer.escape_html(item.title)
            
            if show_id:
                text += f"ID: <code>{item.id}</code> | 🕐 {item.time_start}-{item.time_end}\n"
            else:
                text += f"🕐 {item.time_start}-{item.time_end}\n"
                
            text += f"📝 Занятие: <b>{safe_title}</b>\n"
            text += f"📍 Место: {safe_loc}\n"
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
        text, _ = UIRenderer.render_extra_classes_list(dto, show_id=True)
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

    @staticmethod
    def render_adult_extra_classes_permissions(
        child_name: str,
        permissions: list[AdultExtraClassesPermissionDTO],
    ) -> str:
        """
        Заголовок экрана прав взрослых на занятия конкретного ребёнка.
        """
        safe_child_name = UIRenderer.escape_html(child_name, "Ребёнок")

        if not permissions:
            return (
                "🎨 <b>Права на дополнительные занятия</b>\n\n"
                f"👤 Ребёнок: <b>{safe_child_name}</b>\n\n"
                "Других взрослых в семье пока нет."
            )

        return (
            "🎨 <b>Права взрослых на дополнительные занятия</b>\n\n"
            f"👤 Ребёнок: <b>{safe_child_name}</b>\n\n"
            "Включённое право позволяет взрослому добавлять, изменять "
            "и удалять занятия этого ребёнка."
        )
            
 # ---------------   
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
    def render_final_success(name: str | None) -> str:
        # ЭКРАНИРОВАНИЕ
        safe_name = UIRenderer.escape_html(name, "")
        greeting = f", {safe_name}" if safe_name else ""
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
        return "✅ Вы успешно присоединены к семье!\n\n"

    @staticmethod
    def render_family_created(dto: FamilyCreatedDTO, name: str | None) -> str:
        # ЭКРАНИРОВАНИЕ
        safe_name = UIRenderer.escape_html(name, "")
        greeting = f", {safe_name}" if safe_name else ""
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
        expires_at: str,
    ) -> str:
        return (
            "✅ <b>Приглашение создано</b>\n\n"
            f"Роль: <b>{UIRenderer.escape_html(role_label)}</b>\n"
            f"Действует до: <code>{expires_at}</code>\n"
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
                f"⏳ До: <code>{invite.expires_at}</code>\n"
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
        """
        role_label = UIRenderer._family_invite_role_label(
            invite.intended_role,
        )

        return (
            "📨 <b>Приглашение в семью</b>\n\n"
            f"Роль: <b>{role_label}</b>\n"
            f"Создано: <code>{invite.created_at or '—'}</code>\n"
            f"Действует до: <code>{invite.expires_at}</code>\n"
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
            f"Действует до: <code>{invite.expires_at}</code>\n\n"
            "После отзыва ссылка больше не позволит "
            "присоединиться к семье."
        )
    #-----------------    

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

    @staticmethod
    def render_family_management_menu() -> str:
        return "👨‍👩‍👧 <b>Управление семьей</b>\n\nВыберите ребенка для настройки:"

    @staticmethod
    def render_child_settings_menu(name: str, class_id: str) -> str:
        # ЭКРАНИРОВАНИЕ
        safe_name = UIRenderer.escape_html(name, "Неизвестно")
        safe_class = UIRenderer.escape_html(class_id, "Не выбран")
        return f"⚙️ <b>Настройки профиля:</b> {safe_name} ({safe_class})"

    @staticmethod
    def render_parent_notification_children_menu() -> str:
        """
        Заголовок списка детей для управления подписками взрослого.
        """
        return (
            "🔔 <b>Уведомления по детям</b>\n\n"
            "Выберите ребёнка. Настройки применяются только к вашему "
            "аккаунту и не изменяют настройки других взрослых."
        )

    @staticmethod
    def render_parent_child_notification_settings(
        dto: ParentChildNotificationSettingsDTO,
    ) -> str:
        """
        Экран индивидуальных настроек уведомлений взрослого по ребёнку.
        """
# ЭКРАНИРОВАНИЕ
        safe_child = UIRenderer.escape_html(dto.child_name)
        safe_class = UIRenderer.escape_html(dto.child_class_id, "Класс не выбран")

        return (
            "🔔 <b>Уведомления по ребёнку</b>\n\n"
            f"👤 Ребёнок: <b>{safe_child}</b>\n"
            f"🎓 Класс: {safe_class}\n\n"
            "Настройки ниже относятся только к вам. "
            "Другие взрослые и сам ребёнок управляют своими уведомлениями "
            "независимо."
        )
        
    @staticmethod
    def render_settings_main(
        user_dto: 'UserProfileDTO', 
        family_code: str | None,
        class_name: str | None = None,
        group_names: str | None = None
    ) -> str:
        role_map = {"parent": "👨‍👩‍👧 Родитель", "child": "👶 Ребёнок", "observer": "👁 Наблюдатель"}
        role_name = role_map.get(user_dto.role, "Неизвестно")
        
        # ЭКРАНИРОВАНИЕ
        safe_name = UIRenderer.escape_html(user_dto.name, "Не указано")
        safe_code = UIRenderer.escape_html(family_code)
        code_str = f"<code>{safe_code}</code>" if family_code else "Не в семье"
        
        text = f"⚙️ <b>Ваши настройки профиля, {safe_name}</b>\n\n"
        text += f"👤 Роль: {role_name}\n"
        
        if class_name:
            text += f"🎓 Класс: <b>{UIRenderer.escape_html(class_name)}</b>\n"
            
        if group_names:
            text += f"👥 Группы: <b>{UIRenderer.escape_html(group_names)}</b>\n"
            
        text += f"👨‍👩‍👧 Код семьи: {code_str}\n\n"
        text += "Выберите действие:"
        
        return text
    
    @staticmethod
    def render_family_members_menu(
        members: list['FamilyMemberDTO'], 
        current_user: 'UserProfileDTO', 
        classes_dict: dict
    ) -> str:
        text = "👨‍👩‍👧 <b>Ваша семья</b>\n\n"
        roles_ru = {"parent": "👨‍👩‍👧 Родитель", "child": "👶 Ребёнок", "observer": "👁 Наблюдатель"}
        
        sorted_members = sorted(members, key=lambda m: 1 if m.role == 'child' else 0)
        
        for m in sorted_members:
            role_str = roles_ru.get(m.role, m.role)
            me_flag = " <i>(Вы)</i>" if m.user_id == current_user.user_id else ""
            
            # ЭКРАНИРОВАНИЕ
            safe_name = UIRenderer.escape_html(m.name, "Неизвестно")
            
            if m.role == 'child':
                class_name = classes_dict.get(m.class_id, m.class_id) if m.class_id else "Класс не выбран"
                safe_class = UIRenderer.escape_html(class_name)
                text += f"{role_str}: <b>{safe_name}</b>{me_flag} — {safe_class}\n"
            else:
                text += f"{role_str}: <b>{safe_name}</b>{me_flag}\n"
                
        if current_user.role == 'parent':
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
        Формирует напоминание об уроке или дополнительном занятии.

        Если получатель — взрослый, child_name содержит имя ребёнка и выводится
        отдельной строкой. Для ребёнка child_name=None, имя не дублируется.
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
        safe_child = UIRenderer.escape_html(dto.child_name)
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
        """
        header = "🌅 <b>Расписание на сегодня</b>\n"

        if dto.child_name:
            header += f"👤 Ребёнок: <b>{dto.child_name}</b>\n"

        if dto.class_id:
            header += f"🎓 Класс: {dto.class_id}\n"

        if not dto.lessons:
            return f"{header}\nНа сегодня занятий нет."

        lines = [header]

        for lesson in dto.lessons:
            if lesson.is_extra:
                location = lesson.room_name or "—"
                lines.append(
                    f"🎨 {lesson.start_time}–{lesson.end_time} | "
                    f"<b>{lesson.subject_name}</b> "
                    f"({location})"
                )
                continue

            status = ""
            if lesson.is_cancelled:
                status = " 🚫 <b>ОТМЕНА</b>"
            elif lesson.is_exchange:
                status = " 🔄 <b>ЗАМЕНА</b>"

            group_text = (
                f" · {lesson.group_name}"
                if lesson.group_name
                else ""
            )

            lines.append(
                f"{lesson.lesson_num}. "
                f"{lesson.start_time}–{lesson.end_time} | "
                f"<b>{lesson.subject_name}</b> | "
                f"каб. {lesson.room_name}"
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
                "• остальные пользователи останутся в боте, "
                "но будут отвязаны от семьи.\n\n"
                "Это действие нельзя отменить."
            )

        role_name = {
            "child": "ребёнка",
            "parent": "родителя",
            "observer": "наблюдателя",
            "teacher": "учителя",
        }.get(dto.role, "пользователя")

        extra_line = ""

        if dto.role == "child" and dto.extra_classes_count > 0:
            extra_line = (
                f"\n• ваших дополнительных занятий будет удалено: "
                f"<b>{dto.extra_classes_count}</b>;"
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
        targets: list[ScheduleWatchTargetDTO],
    ) -> str:
        if not targets:
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

        for target in targets:
            title = UIRenderer.escape_html(
                target.title or f"Класс {target.class_id}"
            )

            group = (
                "Весь класс"
                if target.group_id == "ALL"
                else f"Группа {target.group_id}"
            )

            status = (
                "🟢 включено"
                if target.is_enabled
                else "⚫ выключено"
            )

            lines.append(
                f"• <b>{title}</b> — {group}, {status}"
            )

        return "\n".join(lines)
    
    @staticmethod
    def render_watch_target_details(
        target: ScheduleWatchTargetDTO,
        class_name: str,
        group_name: str,
    ) -> str:
        title = UIRenderer.escape_html(
            target.title or class_name
        )

        status = (
            "🟢 Включено"
            if target.is_enabled
            else "⚫ Выключено"
        )
        changes_status = (
            "🟢 Включены"
            if target.receive_schedule_changes
            else "🔴 Выключены"
        )
        return (
            "🎓 <b>Отслеживаемый класс</b>\n\n"
            f"Название: <b>{title}</b>\n"
            f"Класс: <b>{UIRenderer.escape_html(class_name)}</b>\n"
            f"Группа: <b>{UIRenderer.escape_html(group_name)}</b>\n"
            f"Изменения расписания: {changes_status}\n\n"                
            f"Статус: {status}\n\n"
        
            "Этот класс не связан с профилем ребёнка. "
            "Он используется только для вашего самостоятельного "
            "просмотра расписания."
        )
        
        
# Виртуальный ученик
    @staticmethod
    def render_family_students(
        students: list[StudentProfileDTO],
    ) -> str:
        if not students:
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

        for student in students:
            name = UIRenderer.escape_html(
                student.name,
            )

            telegram_status = (
                "📱 Telegram подключён"
                if student.telegram_user_id is not None
                else "🧒 Telegram пока не подключён"
            )

            group_text = (
                "Весь класс"
                if student.group_id == "ALL"
                else f"Группа {student.group_id}"
            )

            lines.append(
                f"• <b>{name}</b>\n"
                f"  🎓 Класс: {student.class_id}\n"
                f"  👥 {group_text}\n"
                f"  {telegram_status}\n"
            )

        return "\n".join(lines)
    
    @staticmethod
    def render_student_details(
        student: StudentProfileDTO,
        class_name: str,
        group_name: str,
    ) -> str:
        telegram_text = (
            "📱 <b>Telegram подключён</b>"
            if student.telegram_user_id is not None
            else "🧒 <b>Telegram пока не подключён</b>"
        )

        return (
            "🧒 <b>Профиль ученика</b>\n\n"
            f"Имя: <b>{UIRenderer.escape_html(student.name)}</b>\n"
            f"Класс: <b>{UIRenderer.escape_html(class_name)}</b>\n"
            f"Группа: <b>{UIRenderer.escape_html(group_name)}</b>\n"
            f"{telegram_text}\n\n"
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
        student: StudentProfileDTO,
    ) -> str:
        return (
            "⚠️ <b>Удалить ученика?</b>\n\n"
            f"Ученик: <b>{UIRenderer.escape_html(student.name)}</b>\n"
            f"Класс: <b>{student.class_id}</b>\n\n"
            "Будут удалены:\n"
            "• профиль ученика;\n"
            "• его дополнительные занятия;\n"
            "• настройки уведомлений взрослых.\n\n"
            "Telegram-профиль отсутствует, поэтому этот ученик "
            "может быть удалён полностью."
        )
        
