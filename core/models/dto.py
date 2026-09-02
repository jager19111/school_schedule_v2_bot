from dataclasses import dataclass
from typing import Dict, Optional, Any

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
    
@dataclass
class AdminStatsDTO:
    total_users: int
    role_distribution: Dict[str, int]