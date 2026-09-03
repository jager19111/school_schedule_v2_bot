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
    success: bool
    error_code: Optional[str] = None
    data: Optional[Any] = None

@dataclass
class UserProfileDTO:
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
    pre_lesson_offset_minutes: int = 15
    changes_window_days: int = 3
    is_notifications_enabled: bool = True
    
@dataclass
class AdminStatsDTO:
    total_users: int
    role_distribution: Dict[str, int]
    
@dataclass
class LessonDTO:
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
    date_iso: str
    lesson_count: int
    extra_count: int
    exchange_count: int

@dataclass
class WeekSummaryDTO:
    week_start_iso: str
    days: List[DaySummaryDTO]

@dataclass
class FullWeekScheduleDTO:
    week_start_iso: str
    days: List['DayScheduleDTO']
    
@dataclass
class ChildInfoDTO:
    user_id: int
    name: str
    class_id: str

@dataclass
class ChildrenListDTO:
    children: List[ChildInfoDTO]
    action: str
    
# Доп задания

@dataclass
class ExtraClassItemDTO:
    id: int
    day_of_week: int
    time_start: str
    time_end: str
    title: str
    location: Optional[str]
    reminder_minutes: int  # <-- НОВОЕ ПОЛЕ

@dataclass
class ExtraClassListDTO:
    items: List[ExtraClassItemDTO]