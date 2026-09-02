from dataclasses import dataclass
from typing import Dict, Optional, Any, List

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
    class_id: Optional[str] = None
    group_id: Optional[str] = None
    parent_control_notifications: bool = False
    
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

@dataclass
class DayScheduleDTO:
    date_iso: str
    lessons: List[LessonDTO]

@dataclass
class ChildInfoDTO:
    user_id: int
    name: str
    class_id: str

@dataclass
class ChildrenListDTO:
    children: List[ChildInfoDTO]
    action: str