from dataclasses import dataclass
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field

@dataclass
class ClassListDTO:
    classes: Dict[str, str]  # id -> name

@dataclass
class GroupListDTO:
    groups: Dict[str, str]  # id -> name

@dataclass
class FamilyCreatedDTO:
    family_code: str

@dataclass
class SchoolDictionariesDTO:
    """Объединенный DTO для передачи справочников школы с хелперами чтения."""
    classes: dict[str, str]
    groups: dict[str, str]

    def get_readable_class(self, class_id: str | None) -> str:
        """Возвращает название класса или прочерк."""
        return self.classes.get(class_id, class_id) if class_id else "—"

    def get_readable_group(self, group_id: str | None) -> str:
        """Расшифровывает ID группы, обрабатывая ALL и множественные группы."""
        if not group_id or group_id == "ALL":
            return "Весь класс"
        
        names = [
            self.groups.get(g.strip(), f"Группа {g.strip()}") 
            for g in str(group_id).split(",")
        ]
        return ", ".join(names)

    @property
    def as_class_list(self) -> ClassListDTO:
        """Helper-свойство: отдает готовый ClassListDTO для клавиатур."""
        return ClassListDTO(classes=self.classes)
    @property
    def as_group_list(self) -> GroupListDTO:
        """Helper-свойство: отдает готовый GroupListDTO для клавиатур."""
        return GroupListDTO(groups=self.groups)
    
@dataclass
class FamilyInviteDTO:
    """
    Role-specific invite в семью.
    """
    id: int

    token: str
    family_id: int
    intended_role: str

    expires_at: str

    max_uses: int = 1
    uses_count: int = 0
    is_revoked: bool = False

    created_at: Optional[str] = None
    used_by_user_id: Optional[int] = None
    used_at: Optional[str] = None

@dataclass
class ScheduleWatchTargetDTO:
    """
    Самостоятельно отслеживаемый класс/группа.

    Не связан с профилем ребёнка и не требует family_id.
    """
    id: int

    owner_user_id: int

    class_id: str
    group_id: str

    title: Optional[str] = None
    is_enabled: bool = True
    receive_schedule_changes: bool = True

    created_at: Optional[str] = None
    updated_at: Optional[str] = None

@dataclass
class ScheduleViewTargetDTO:
    """
    Универсальная цель Schedule Hub.

    kind:
    - student: student_profiles;
    - watch: schedule_watch_targets.
    """
    kind: str

    target_id: int

    class_id: str
    group_id: str

    title: str

    telegram_user_id: Optional[int] = None
    is_enabled: bool = True

@dataclass
class StudentProfileDTO:
    """
    Доменный профиль ученика.

    family_id:
    - задан для ученика семьи;
    - None для самостоятельного Telegram-ребёнка.

    telegram_user_id:
    - None для virtual student;
    - Telegram user_id, если ребёнок подключён к bot.
    """
    id: int

    family_id: int | None

    name: str
    class_id: str
    group_id: str

    telegram_user_id: int | None = None
    is_active: bool = True

    created_at: str | None = None
    updated_at: str | None = None

@dataclass
class StudentClaimInviteDTO:
    """
    Одноразовое приглашение привязать Telegram account
    к существующему virtual student profile.
    """
    id: int

    token: str

    student_id: int
    family_id: int

    created_by_user_id: int

    expires_at: str

    is_revoked: bool = False

    used_by_user_id: int | None = None
    created_at: str | None = None
    used_at: str | None = None

    student_name: str | None = None
    student_class_id: str | None = None
    student_group_id: str | None = None
    
@dataclass
class StudentAccessDTO:
    """
    Права взрослого на конкретный student profile.
    """
    adult_user_id: int
    student_id: int

    can_view: bool
    can_manage_extra_classes: bool
    is_family_admin: bool
                    
@dataclass
class ActionResponseDTO:
    """ DTO для ответа на действие (например, создание семьи, обновление профиля и т.п.). 
    """
    success: bool
    error_code: Optional[str] = None
    data: Optional[Any] = None

@dataclass
class ProfileResetImpactDTO:
    """
    Последствия сброса профиля/выхода из семьи.

    Используется только до подтверждения destructive action.
    """
    user_id: int
    role: Optional[str]
    family_id: Optional[int]
    is_family_admin: bool

    family_members_count: int = 0
    children_count: int = 0
    extra_classes_count: int = 0
    
@dataclass
class UserProfileDTO:
    """DTO личного профиля пользователя."""

    user_id: int
    role: Optional[str]
    is_fully_registered: bool

    name: Optional[str] = None
    family_id: Optional[int] = None
    class_id: Optional[str] = None
    group_id: Optional[str] = None
    teacher_id: Optional[str] = None

    morning_summary_time: Optional[str] = None
    pre_lesson_offset_minutes: int = 10
    receive_schedule_changes: bool = True
    receive_extra_class_reminders: bool = True
    can_manage_own_extra_classes: bool = True
    changes_window_days: int = 3
    is_notifications_enabled: bool = True
    global_extra_reminder: int = 30

    
@dataclass
class AdminStatsDTO:
    """ DTO для статистики по пользователям. """
    total_users: int
    role_distribution: Dict[str, int]

@dataclass
class NikaSourceHealthDTO:
    """
    Диагностическое состояние NIKA source и локального schedule cache.

    Команда не делает network request:
    она показывает только уже сохранённый state.
    """
    status: str

    lesson_count: int = 0

    today_date: str | None = None

    coverage_start_date: str | None = None
    coverage_end_date: str | None = None

    coverage_is_current: bool = False
    coverage_has_future: bool = False

    js_filename: str | None = None
    export_date: str | None = None
    export_time: str | None = None

    last_checked_at: str | None = None
    last_changed_at: str | None = None

    last_error: str | None = None
    last_error_at: str | None = None
        
@dataclass
class LessonDTO:
    """ DTO для одного урока. 
    """
    lesson_num: int
    start_time: str
    end_time: str
    subject_name: str
    room_name: str
    is_cancelled: bool
    is_exchange: bool

# Возможно не нужно
@dataclass
class DayScheduleDTO:
    """
    DTO для расписания на один день.
    """
    date_iso: str  # YYYY-MM-DD
    lessons: List[Dict[str, Any]] = field(default_factory=list)

# для недельной сводки

@dataclass
class DaySummaryDTO:
    """ DTO для сводки по одному дню. """
    date_iso: str
    lesson_count: int
    extra_count: int
    exchange_count: int

@dataclass
class WeekSummaryDTO:
    """ DTO для сводки по неделе. """
    week_start_iso: str
    days: List[DaySummaryDTO]

@dataclass
class FullWeekScheduleDTO:
    """ DTO для полного расписания на неделю. """
    week_start_iso: str
    days: List['DayScheduleDTO']
    


@dataclass
class ParentStudentNotificationSettingsDTO:
    """
    Персональные настройки уведомлений взрослого
    по конкретному student profile.

    Это не настройки Telegram-ребёнка из users.
    Они принадлежат связи:

    parent/observer
    → parent_student_settings
    → student_profiles.id
    """
    parent_user_id: int
    student_id: int

    student_name: str
    student_class_id: str
    student_group_id: str
    telegram_user_id: int | None = None

    receive_morning_summary: bool = True
    receive_pre_lesson_reminders: bool = True
    receive_schedule_changes: bool = True
    receive_extra_class_reminders: bool = True

    can_manage_extra_classes: bool = False

@dataclass
class StudentTelegramSettingsDTO:
    """
    Личные Telegram-настройки ученика.

    Используется только если student profile привязан к Telegram user:
    student_profiles.telegram_user_id IS NOT NULL.

    Настройки находятся в users, но управляются family admin
    через student_profiles.id.
    """
    student_id: int
    telegram_user_id: int

    student_name: str
    class_id: str
    group_id: str

    is_notifications_enabled: bool = True

    morning_summary_time: str | None = None
    pre_lesson_offset_minutes: int = 10

    receive_schedule_changes: bool = True
    receive_extra_class_reminders: bool = True

    can_manage_own_extra_classes: bool = True

    child_notification_settings_locked: bool = False
            

# Доп задания

@dataclass
class ExtraClassDTO:
    id: int

    family_id: int | None
    student_id: int

    day_of_week: int
    time_start: str
    time_end: str
    title: str
    location: str | None
    reminder_minutes: int

    created_at: str | None = None
    updated_at: str | None = None
    
@dataclass
class ExtraClassItemDTO:
    """ 
    DTO для одного доп. занятия ребёнка.
    """
    id: int
    day_of_week: int
    time_start: str
    time_end: str
    title: str
    location: Optional[str]
    reminder_minutes: int  # <-- НОВОЕ ПОЛЕ

@dataclass
class ExtraClassListDTO:
    """ DTO для списка доп. занятий ребёнка.
    """
    items: List[ExtraClassItemDTO]
    
    
@dataclass
class TeacherListDTO:
    """
    DTO для списка учителей.
    """
    teachers: Dict[str, str]  # id -> name
    
@dataclass
class FamilyMemberDTO:
    """ DTO для одного члена семьи. 
    """
    user_id: int
    name: str
    role: str
    class_id: Optional[str] = None

@dataclass
class ExtraClassesAccessDTO:
    """
    Права инициатора на дополнительные занятия конкретного student profile.

    can_view:
    Инициатор может видеть занятия ученика.

    can_manage:
    Инициатор может создавать, изменять и удалять занятия ученика.
    """
    actor_user_id: int
    target_student_id: int

    can_view: bool
    can_manage: bool


@dataclass
class AdultStudentExtraClassesPermissionDTO:
    """
    Право взрослого управлять дополнительными занятиями
    конкретного student profile.

    Family admin не обязан присутствовать в этом списке,
    потому что его право является implicit и всегда равно True.
    """
    adult_user_id: int
    adult_name: str
    adult_role: str

    student_id: int

    can_manage_extra_classes: bool
                
# Уведомления

@dataclass
class LessonReminderDTO:
    """
    Напоминание об уроке или дополнительном занятии.

    child_name заполняется только для взрослого получателя.
    Для ребёнка оно остаётся None, потому что сообщение относится к нему самому.
    """
    subject_name: str
    start_time: str
    room_name: str
    is_extra: bool = False
    child_name: Optional[str] = None
    

@dataclass
class ChangeReminderDTO:
    """
    Уведомление о замене или отмене урока.

    child_name задан только для взрослого получателя.
    Для ребёнка остаётся None.
    """
    date: str
    lesson_num: int
    subject_name: str
    is_cancelled: bool
    child_name: Optional[str] = None
    watch_target_title: Optional[str] = None

@dataclass
class MorningLessonDTO:
    lesson_num: Optional[int]
    start_time: str
    end_time: str
    subject_name: str
    room_name: str
    is_cancelled: bool
    is_exchange: bool
    is_extra: bool = False
    group_name: Optional[str] = None

@dataclass
class MorningSummaryDTO:
    """
    Утренняя сводка расписания одного ребёнка.

    Для ребёнка-получателя child_name остаётся None.
    Для взрослого получателя child_name содержит имя ребёнка.
    """
    date_iso: str
    lessons: List[MorningLessonDTO]
    child_name: Optional[str] = None
    class_id: Optional[str] = None
    