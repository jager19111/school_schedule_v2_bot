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

    telegram_user_id:
    - None для виртуального ученика;
    - user_id Telegram-профиля, если ребёнок подключил bot.
    """
    id: int

    family_id: int

    name: str

    class_id: str
    group_id: str

    telegram_user_id: Optional[int] = None

    is_active: bool = True

    created_at: Optional[str] = None
    updated_at: Optional[str] = None

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
class ChildInfoDTO:
    """
    DTO для информации о ребёнке в списке детей родителя. 
    """
    user_id: int
    name: str
    class_id: str
    group_id: str  # <-- Обязательно добавляем поле

@dataclass
class ParentChildNotificationSettingsDTO:
    """
    Настройки уведомлений одного взрослого относительно одного ребёнка.

    Это не личные настройки пользователя. Они принадлежат связи:
        parent/observer -> конкретный child.
    """
    parent_id: int
    child_id: int

    child_name: str
    child_class_id: Optional[str] = None
    child_group_id: Optional[str] = None

    receive_morning_summary: bool = True
    receive_pre_lesson_reminders: bool = True
    receive_schedule_changes: bool = True
    receive_extra_class_reminders: bool = True
    
@dataclass
class ChildrenListDTO:
    """ DTO для списка детей родителя. 
    """
    children: List[ChildInfoDTO]
    action: str
    
# Доп задания

@dataclass
class ExtraClassDTO:
    id: int

    family_id: int
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

# не использовать в новых методах. удалить после рефакторинга
@dataclass
class AdultExtraClassesPermissionDTO:
    """
    Право конкретного взрослого на управление допзанятиями ребёнка.

    Используется только в UI семейного администратора.
    """
    adult_user_id: int
    adult_name: str
    adult_role: str
    child_user_id: int
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
    