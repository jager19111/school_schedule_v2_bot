# services/notification/context.py

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from core.models.dto import (
    ScheduleChangeRecipientDTO,
    TeacherChangeRecipientDTO,
    PreLessonRecipientDTO,
    TeacherPreLessonRecipientDTO,
)

@dataclass
class NotificationTickContext:
    """
    Единый контекст тика рассылки.
    Хранит кеши (для предотвращения N+1) и собирает метрики на протяжении всего тика.
    """
    tick_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    # Системные кеши
    blocked_ids: Set[int] = field(default_factory=set)
    blocked_ids_loaded: bool = False
    display_numbers_cache: Dict[Tuple[str, str], Dict[int, str]] = field(default_factory=dict)
    
    # Кеши получателей
    change_recipients_cache: Dict[Tuple[str, str], List[ScheduleChangeRecipientDTO]] = field(default_factory=dict)
    teacher_change_cache: Dict[str, List[TeacherChangeRecipientDTO]] = field(default_factory=dict)
    
    pre_lesson_recipients_cache: Dict[Tuple[str, str], List[PreLessonRecipientDTO]] = field(default_factory=dict)
    teacher_pre_lesson_cache: Dict[str, List[TeacherPreLessonRecipientDTO]] = field(default_factory=dict)

    # Стандартизированные метрики
    processed_entities: int = 0
    candidates: int = 0
    pending: int = 0
    sent: int = 0
    failed: int = 0
    queries: int = 0

    @property
    def metrics_summary(self) -> str:
        """Строгий формат сводки для логгера."""
        return (
            f"[Tick {self.tick_id}] "
            f"candidates={self.candidates}, pending={self.pending}, "
            f"sent={self.sent}, failed={self.failed}, queries={self.queries}"
        )