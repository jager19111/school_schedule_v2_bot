from dataclasses import dataclass, field
from typing import List, Optional
import datetime

@dataclass
class Class:
    id: str
    name: str
    course: int

@dataclass
class Teacher:
    id: str
    name: str

@dataclass
class Room:
    id: str
    name: str

@dataclass
class Subject:
    id: str
    name: str

@dataclass
class Period:
    id: str
    name: str
    date_begin: datetime.date
    date_end: datetime.date

@dataclass
class LessonInstance:
    id: str
    period_id: str
    class_id: str
    date: str  # YYYY-MM-DD
    weekday: int # 1-7
    lesson_num: int
    start_time: str
    end_time: str
    
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None
    teacher_id: Optional[str] = None
    teacher_name: Optional[str] = None
    room_id: Optional[str] = None
    room_name: Optional[str] = None
    group_id: str = "ALL"
    group_name: str = "Весь класс"
    
    is_exchange: bool = False
    is_cancelled: bool = False
    
    groups_raw: List[str] = field(default_factory=list)
    subjects_raw: List[str] = field(default_factory=list)
    rooms_raw: List[str] = field(default_factory=list)