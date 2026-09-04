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
class ActionResponseDTO:
    """ DTO для ответа на действие (например, создание семьи, обновление профиля и т.п.). 
    """
    success: bool
    error_code: Optional[str] = None
    data: Optional[Any] = None

@dataclass
class UserProfileDTO:
    """ DTO для профиля пользователя. """
    user_id: int
    role: Optional[str]
    is_fully_registered: bool
    name: Optional[str] = None               # <-- ДОБАВЛЕНО
    family_id: Optional[int] = None
    class_id: Optional[str] = None
    group_id: Optional[str] = None
    parent_control_notifications: bool = False
    notify_parent_about_me: bool = True      # <-- ДОБАВЛЕНО
    morning_summary_time: Optional[str] = None # <-- ДОБАВЛЕНО
    pre_lesson_offset_minutes: int = 10
    changes_window_days: int = 3
    is_notifications_enabled: bool = True
    global_extra_reminder: int = 30  # <-- ДОБАВЛЕНО
    can_edit_extra_classes: bool = True  # <-- НОВОЕ ПОЛЕ
    
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
class ChildrenListDTO:
    """ DTO для списка детей родителя. 
    """
    children: List[ChildInfoDTO]
    action: str
    
# Доп задания

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
    
# Уведомления

@dataclass
class LessonReminderDTO:
    subject_name: str
    start_time: str
    room_name: str
    is_extra: bool = False

@dataclass
class ChangeReminderDTO:
    date: str
    lesson_num: int
    subject_name: str
    is_cancelled: bool

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

@dataclass
class MorningSummaryDTO:
    date_iso: str
    lessons: List[MorningLessonDTO]