# bot/core/models/dto.py
#
# ЭТАП 3 (DTO): добавлены поля для original_*, group_changed,
# day_permutation, детализации изменений и расширенной информации
# в уведомлениях о заменах.
#
# ИСПРАВЛЕНИЯ P0:
# 1. Убран SchoolMetadata из DTO — перенесён в core.models.metadata.
# 2. Убраны лишние Any в типах.
# 3. Удалён противоречивый комментарий «Union: LessonDTO | Dict ».
# 4. DayScheduleDTO.lessons строго типизирован как List[LessonDTO].

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, List, Literal, Any, Protocol
from datetime import datetime
class ReplyMarkupProtocol(Protocol):
    """Маркерный протокол для UI-клавиатур, избавляющий DTO от зависимости aiogram."""
    pass

RecipientKind = Literal["student", "adult", "watch", "teacher"]

# ==========================================================
# Справочники
# ==========================================================


@dataclass(frozen=True, slots=True)
class ClassListDTO:
    classes: Dict[str, str]  # id -> name


@dataclass
class GroupListDTO:
    groups: Dict[str, str]  # id -> name

@dataclass
class RoomListDTO:
    rooms: dict[str, str]  # id -> name

@dataclass(frozen=True, slots=True)
class TeacherListDTO:
    """ DTO для списка учителей. """
    teachers: Dict[str, str]  # id -> name


@dataclass(frozen=True, slots=True)
class SchoolDictionariesDTO:
    """Объединенный DTO для передачи справочников школы с хелперами чтения."""
    classes: dict[str, str]
    groups: dict[str, str]

    def get_readable_class(self, class_id: str | int | None) -> str:
        """Возвращает название класса или прочерк. Защищен от int-ключей."""
        if not class_id:
            return "—"
        
        safe_id = str(class_id)
        return self.classes.get(safe_id, safe_id)

    def get_readable_group(self, group_id: str | None) -> str:
        """Расшифровывает ID группы, обрабатывая ALL и множественные группы."""
        if not group_id or str(group_id).strip() == "ALL":
            return "Весь класс"
        
        names = [
            self.groups.get(g.strip(), f"Группа {g.strip()}") 
            for g in str(group_id).split(",") if g.strip()
        ]
        return ", ".join(names) or "Весь класс"

    @property
    def as_class_list(self) -> ClassListDTO:
        """Helper-свойство: отдает готовый ClassListDTO для клавиатур."""
        return ClassListDTO(classes=self.classes)

    @property
    def as_group_list(self) -> GroupListDTO:
        """Helper-свойство: отдает готовый GroupListDTO для клавиатур."""
        return GroupListDTO(groups=self.groups)


# ==========================================================
# ViewModel (без изменений, оставлены для совместимости)
# ==========================================================


@dataclass(frozen=True, slots=True)
class WatchTargetViewModel:
    """
    Модель готовых данных для экрана отслеживаемого класса.

    Все NIKA ID расшифрованы билдером в сервисе.
    Boolean-дубли статусных полей — для клавиатур-тумблеров
    (клавиатура меняет текст кнопки в зависимости от состояния,
    но НЕ расшифровывает ID).
    """
    target_id: int                    # для callback_data
    title: str                        # "10 А" (пользовательское или дефолтное)
    class_name: str                   # "10 А" (расшифрованный class_id)
    group_name: str                   # "Весь класс" / "Английский"

    # --- Статусы для отображения (готовые строки) ---
    is_enabled_text: str              # "🟢 Активно" / "⚫ Пауза"
    changes_notify_text: str          # "🔔 Включены" / "🔴 Выключены"
    telegram_status: str              # "📱 Подключен" / "🧒 Без Telegram"

    # --- Boolean-флаги для клавиатур (текст кнопки-тумблера) ---
    is_enabled: bool                  # для текста кнопки "Выключить/Включить"
    receive_schedule_changes: bool    # для текста кнопки "Изменения: ВКЛ/ВЫКЛ"


@dataclass(frozen=True, slots=True)
class ExtraClassViewModel:
    """
    Модель одного доп. занятия для списка кружков.

    Day-of-week расшифрован билдером.
    Location уже имеет fallback "Не указано".
    Renderer экранирует title и location (пользовательский ввод).
    """
    id: int                     # для callback (delete/edit) и показа ID
    day_of_week: int           # для сортировки (int comparison)
    day_of_week_text: str      # "Понедельник" (pre-computed)
    time_start: str            # "18:00"
    time_end: str              # "19:30"
    title: str                 # "Футбол" (raw, renderer экранирует)
    location: str              # "Спорткомплекс" или "Не указано" (raw)
    reminder_minutes: int      # 45 (renderer форматирует как "45мин")


@dataclass(frozen=True, slots=True)
class StudentProfileViewModel:
    """
    Модель готовых данных для экрана ученика.

    Все NIKA ID расшифрованы в человекочитаемые имена.
    Boolean-поля дублируют статусы для клавиатур
    (клавиатура строит условные кнопки, рендерер — текст).
    """
    student_id: int              # для callback_data
    name: str                    # "Лиза"
    class_name: str             # "10 А" (расшифрованный class_id)
    group_name: str             # "Весь класс" / "Английский"

    # --- Статусы для отображения (готовые строки) ---
    telegram_status: str        # "📱 Подключен" / "🧒 Без Telegram"

    # --- Boolean-флаги для клавиатур (условные кнопки) ---
    telegram_connected: bool     # для кнопки "📱 Настройки Telegram-ребёнка"
    is_active: bool             # для иконки в списке


@dataclass(frozen=True, slots=True)
class FamilyMemberViewModel:
    """
    Модель участника семьи для списка состава.

    Сортировка уже выполнена билдером:
    текущий пользователь первым, затем parent > child > observer.
    """
    user_id: int
    name: str                   # "Лиза"
    role: str                   # "parent" / "child" / "observer" (для логики)
    role_display: str           # "👨‍👩‍👧 Родитель" / "👶 Ребёнок" / "👁 Наблюдатель"
    class_name: str            # "10 А" или "— класс не выбран —" (для ребёнка)
    is_current_user: bool       # для маркера "<i>(Вы)</i>"


@dataclass(frozen=True, slots=True)
class ScheduleTargetViewModel:
    """
    Модель выбора цели Schedule Hub.

    Иконка и все расшифровки — pre-computed билдером.
    Keyboard строит кнопки из полей, ничего не декодирует.
    """
    kind: str                   # "student" | "watch" (для callback_data)
    target_id: int              # для callback_data
    title: str                  # имя ребёнка / название класса
    class_name: str             # "10 А" (расшифрованный class_id)
    group_name: str             # "Весь класс" / "Английский"
    icon: str                   # "📱" / "🧒" / "🎓" (pre-computed)
    telegram_connected: bool    # для иконки (boolean-дубль)


@dataclass(frozen=True, slots=True)
class StudentTelegramSettingsViewModel:
    """
    Модель экрана личных Telegram-настроек ребёнка,
    открытого family admin.
    """
    student_id: int
    student_name: str
    class_name: str             # "10 А"
    group_name: str              # "Весь класс"
    telegram_status: str        # "📱 Telegram подключён"

    # --- Boolean-настройки ---
    is_notifications_enabled: bool
    receive_schedule_changes: bool
    receive_extra_class_reminders: bool
    can_manage_own_extra_classes: bool
    child_notification_settings_locked: bool

    # --- Для отображения (pre-formatted) ---
    morning_summary_time: str    # "07:00" или "ВЫКЛ"
    pre_lesson_offset_minutes: int
    pre_lesson_text: str         # "10 мин 🟢" или "ВЫКЛ 🔴"
    lock_text: str               # "ВКЛ 🔒" или "ВЫКЛ 🔓"


@dataclass(frozen=True, slots=True)
class ParentStudentNotificationSettingsViewModel:
    """
    Модель экрана личных подписок взрослого на ученика.
    """
    student_id: int
    student_name: str
    class_name: str             # "10 А"
    group_name: str              # "Весь класс"
    telegram_status: str        # "📱 Telegram подключён"
    telegram_connected: bool

    # --- Подписки ---
    receive_morning_summary: bool
    receive_pre_lesson_reminders: bool
    receive_schedule_changes: bool
    receive_extra_class_reminders: bool

    # --- Права ---
    can_manage_extra_classes: bool
    manage_status_text: str     # "✅ Можно управлять" / "👁 Только просмотр"


# ==========================================================
# Domain DTO (без изменений, оставлены для совместимости)
# ==========================================================


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
    short_code: Optional[str] = None
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
    created_at: datetime | None = None  # <-- ИСПРАВЛЕНО
    updated_at: datetime | None = None  # <-- ИСПРАВЛЕНО


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
    """ DTO для ответа на действие (например, создание семьи, обновление профиля и т.п.). """
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


# ==========================================================
# Lesson DTO (Этап 3: расширен для original_*, group_changed, permutation)
# ==========================================================


@dataclass
class LessonDTO:
    """
    DTO одного элемента расписания: школьный урок ИЛИ доп. занятие.

    Школьный урок: заполнено всё; при заменах original_* хранит «было ».
    Доп. занятие: is_extra=True, id="extra-N", lesson_num=None,
    display_num="•", все original_* остаются None.
    """
    # --- Ядро (заполняется всегда) ---
    lesson_num: Optional[int] = None
    start_time: str = ""
    end_time: str = ""
    subject_name: str = ""
    room_name: str = ""
    is_cancelled: bool = False
    is_exchange: bool = False

    # --- Идентификатор записи ---
    id: Optional[str] = None
    date_iso: Optional[str] = None
    
    # --- Принадлежность ---
    period_id: Optional[str] = None
    class_id: Optional[str] = None
    class_name: Optional[str] = None
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    teacher_id: Optional[str] = None
    teacher_name: Optional[str] = None

    # --- Состояния ---
    is_methodological: bool = False
    is_extra: bool = False

    # --- «Было → стало » (только школьные уроки с заменами) ---
    original_subject_id: Optional[str] = None
    original_subject_name: Optional[str] = None
    original_teacher_id: Optional[str] = None
    original_teacher_name: Optional[str] = None
    original_room_id: Optional[str] = None
    original_room_name: Optional[str] = None
    original_group_id: Optional[str] = None
    original_group_name: Optional[str] = None
    original_class_id: Optional[str] = None
    original_class_name: Optional[str] = None

    # --- Флаги UI ---
    group_changed: bool = False
    day_permutation: bool = False
    display_num: Optional[str] = None   # номер урока 2 смены ("2*"),
                                        # заполняется _enrich_display_numbers_dtos


# ==========================================================
# DayScheduleDTO (строго типизирован)
# ==========================================================


@dataclass
class DayScheduleDTO:
    """
    DTO для расписания на один день.

    lessons: List[LessonDTO] — школьные уроки и доп. занятия
    в едином формате (доп. занятия отличаются is_extra=True).
    """
    date_iso: str
    lessons: List['LessonDTO'] = field(default_factory=list)
    has_permutation: bool = False
    
    # === НОВЫЕ ПОЛЯ ДЛЯ КОНТЕКСТА РЕНДЕРА ===
    origin: Literal["class", "teacher", "student"] = "student"
    class_name: Optional[str] = None
    group_name: Optional[str] = None

# ==========================================================
# DayChangesDetailDTO (только LessonDTO)
# ==========================================================


@dataclass
class DayChangesDetailDTO:
    """
    Детализация изменений «было → стало」на день.

    lessons: List[LessonDTO] — только school lessons с
    is_exchange/is_cancelled (extra lessons не имеют замен).
    """
    date_iso: str
    origin: Literal["class", "teacher"]
    lessons: List[LessonDTO] = field(default_factory=list)


# ==========================================================
# Недельные DTO (без изменений, оставлены для совместимости)
# ==========================================================


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
    days: List[DayScheduleDTO]


# ==========================================================
# Notification DTO (Этап 3: расширен для original_*, group_changed)
# ==========================================================

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

    Этап 3: добавлены original_*, new_* для детализации
    «Математика → Ин.яз (204→318)」или «Группа 1 → Группа 2」.

    child_name задан только для взрослого получателя.
    Для ребёнка остаётся None.
    """
    change_id: str
    date: str
    lesson_num: int
    subject_name: str
    is_cancelled: bool

    # NEW Этап 3:
    display_num: Optional[str] = None
    original_subject_name: Optional[str] = None
    new_subject_name: Optional[str] = None
    original_room_name: Optional[str] = None
    new_room_name: Optional[str] = None
    original_group_name: Optional[str] = None
    new_group_name: Optional[str] = None
    group_changed: bool = False
    
    original_class_name: Optional[str] = None
    new_class_name: Optional[str] = None
    # --- УЧИТЕЛЯ ---
    original_teacher_name: Optional[str] = None
    new_teacher_name: Optional[str] = None
    
    child_name: Optional[str] = None
    watch_target_title: Optional[str] = None

@dataclass
class DailyChangeSummaryDTO:
    """DTO для склеенной дневной сводки изменений (используется только в рассылках)."""
    date: str
    recipient_kind: str
    changes: List[ChangeReminderDTO]
    child_name: Optional[str] = None
    watch_target_title: Optional[str] = None
    teacher_name: Optional[str] = None
    
@dataclass(frozen=True, slots=True)
class PendingChangeDTO:
    id: str
    date: str
    period_id: str
    class_id: str
    group_id: str
    group_name: str | None
    teacher_id: str | None
    lesson_num: int

    subject_id: str | None
    subject_name: str | None
    room_id: str | None
    room_name: str | None
    teacher_name: str | None

    original_subject_id: str | None
    original_subject_name: str | None
    original_room_id: str | None
    original_room_name: str | None
    original_teacher_id: str | None
    original_teacher_name: str | None
    original_group_id: str | None
    original_group_name: str | None
    original_class_id: str | None
    original_class_name: str | None

    is_exchange: bool
    is_cancelled: bool

    # Вычисляемое поле, не хранится в schedule_cache.
    display_num: str | None = None
    
@dataclass
class MorningLessonDTO:
    """
    Урок для утренней сводки.
    """
    lesson_num: Optional[int]
    start_time: str
    end_time: str
    subject_name: str
    room_name: str
    is_cancelled: bool
    is_exchange: bool
    is_extra: bool = False
    is_methodological: bool = False
    group_name: Optional[str] = None

    # Поля для зачеркиваний (было -> стало)
    original_subject_name: Optional[str] = None
    original_room_name: Optional[str] = None
    group_changed: bool = False
    day_permutation: bool = False
    class_name: Optional[str] = None
    teacher_name: Optional[str] = None
    display_num: Optional[str] = None
    group_id: Optional[str] = None

@dataclass
class MorningSummaryDTO:
    """
    Утренняя сводка (Всё сообщение целиком).

    Для ребёнка-получателя child_name остаётся None.
    Для взрослого получателя child_name содержит имя ребёнка.
    """
    date_iso: str
    lessons: list[MorningLessonDTO]
    
    # Данные для заголовка
    child_name: str | None = None
    class_id: str | None = None     # Технический ID основного класса ученика
    class_name: str | None = None   # Человекочитаемое название класса для заголовка
    group_name: str | None = None
    teacher_name: str | None = None
    
    has_permutation: bool = False
    origin: Literal["student", "teacher"] = "student"


# ==========================================================
# Доп. занятия (без изменений, оставлены для совместимости)
# ==========================================================


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
    created_at: datetime | None = None  # <-- ИСПРАВЛЕНО
    updated_at: datetime | None = None  # <-- ИСПРАВЛЕНО


@dataclass
class ExtraClassItemDTO:
    """ DTO для одного доп. занятия ребёнка. """
    id: int
    day_of_week: int
    time_start: str
    time_end: str
    title: str
    location: Optional[str]
    reminder_minutes: int


@dataclass
class ExtraClassListDTO:
    """ DTO для списка доп. занятий ребёнка. """
    items: List[ExtraClassItemDTO]


@dataclass
class FamilyMemberDTO:
    """ DTO для одного члена семьи. """
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
    
    
# ==========================================================    
# DTO для всех публичных выходов notification-слоя
# ==========================================================
@dataclass(frozen=True, slots=True)
class DebugBurstResultDTO:
    """Результат выполнения стресс-теста рассылки."""
    requested: int
    pending: int
    sent: int
    failed: int

@dataclass(frozen=True, slots=True)
class MorningSummaryTaskDTO:
    recipient_id: int
    target_student_id: int
    recipient_kind: RecipientKind
    child_name: Optional[str]
    class_id: Optional[str]
    group_id: Optional[str]

    def __post_init__(self):
        if self.recipient_id <= 0:
            raise ValueError("recipient_id must be strictly positive")
        if self.target_student_id <= 0:
            raise ValueError("target_student_id must be strictly positive")

@dataclass(frozen=True, slots=True)
class TeacherMorningTaskDTO:
    recipient_id: int
    teacher_id: str
    teacher_name: str | None

@dataclass(frozen=True, slots=True)
class PreLessonRecipientDTO:
    student_id: Optional[int]
    recipient_id: int
    offset_minutes: int
    recipient_kind: RecipientKind
    child_name: Optional[str]

    def __post_init__(self):
        if self.recipient_id <= 0:
            raise ValueError("recipient_id must be strictly positive")
        if self.offset_minutes < 0:
            raise ValueError("offset_minutes cannot be negative")
            
@dataclass(frozen=True, slots=True)
class TeacherPreLessonRecipientDTO:
    recipient_id: int
    teacher_id: Optional[int]
    offset_minutes: int

    def __post_init__(self):
        if self.recipient_id <= 0:
            raise ValueError("recipient_id must be strictly positive")
        if self.offset_minutes < 0:
            raise ValueError("offset_minutes cannot be negative")
        
@dataclass(frozen=True, slots=True)
class ScheduleChangeRecipientDTO:
    student_id: Optional[int]
    recipient_id: int
    changes_window_days: int
    recipient_kind: RecipientKind
    child_name: Optional[str]
    watch_target_title: Optional[str]

    def __post_init__(self):
        if self.recipient_id <= 0:
            raise ValueError("recipient_id must be strictly positive")
        if self.changes_window_days < 0:
            raise ValueError("changes_window_days cannot be negative")

@dataclass(frozen=True, slots=True)
class TeacherChangeRecipientDTO:
    recipient_id: int
    teacher_id: str
    changes_window_days: int

@dataclass(frozen=True, slots=True)
class ExtraClassReminderTaskDTO:
    extra_id: int
    student_id: Optional[int]
    time_start: str
    title: str
    location: str | None
    recipient_id: int
    offset_minutes: int
    recipient_kind: RecipientKind
    child_name: Optional[str]
    
    def __post_init__(self):
        if self.recipient_id <= 0:
            raise ValueError("recipient_id must be strictly positive")
        if self.offset_minutes < 0:
            raise ValueError("offset_minutes cannot be negative")
    
    
# ==========================================================
# Notification Service & Repository DTOs (DTO-first подход)
# ==========================================================

@dataclass(frozen=True, slots=True)
class DeliveredKeyDTO:
    """Единый формат ключа дедупликации доставки."""
    notification_date: str
    source_id: str
    recipient_id: int

    def __post_init__(self):
        if not self.notification_date or not self.source_id:
            raise ValueError("notification_date and source_id cannot be empty")
        if self.recipient_id <= 0:
            raise ValueError("recipient_id must be strictly positive")

@dataclass
class NotificationSendDTO:
    """Модель кандидата на отправку (полностью заменяет PendingSend)."""
    notification_type: str
    notification_date: str
    source_ids: list[str]
    recipient_id: int
    text: str
    context: str = ""
   # === НОВЫЙ БЛОК: Манифест действий вместо физической клавиатуры ===
    action_type: str | None = None      # Например: "day_changes"
    action_payload: dict | None = None  # Данные для кнопки: {"target_id": 123, ...}

    def __post_init__(self):
        if not self.notification_type or not str(self.notification_type).strip():
            raise ValueError("notification_type cannot be empty")
        if not self.source_ids:
            raise ValueError("source_id cannot be empty")
        if not self.text or not str(self.text).strip():
            raise ValueError("Notification text cannot be empty")
        if self.recipient_id <= 0:
            raise ValueError("recipient_id must be strictly positive")

@dataclass(frozen=True, slots=True)
class PreLessonSourceDTO:
    """DTO для урока, возвращаемого из репозитория для предурочных напоминаний (избавляемся от dict)."""
    id: str
    date: str
    class_id: str
    start_time: str
    group_id: str | None = None
    teacher_id: str | None = None
    subject_name: str | None = None
    room_name: str | None = None
    
    


@dataclass(frozen=True, slots=True)
class NikaSourceStateDTO:
    """
    Типизированное состояние NIKA-источника (таблица nika_source_state).

    Заменяет Dict[str, Any] из ScheduleRepository.get_nika_source_state().

    Поля *_at приходят из BaseRepository._process_row как aware UTC datetime.
    """
    js_filename: str
    raw_sha256: str
    semantic_sha256: str
    export_date: str | None = None
    export_time: str | None = None
    last_checked_at: datetime | None = None
    last_changed_at: datetime | None = None
    coverage_start_date: str | None = None
    coverage_end_date: str | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RawNikaCacheDTO:
    """
    Singleton-кеш сырого JS-файла NIKA (таблица raw_nika_cache).

    Заменяет Dict[str, Any] из ScheduleRepository.get_cached_raw_nika().
    """
    js_filename: str
    raw_sha256: str
    content: str
    fetched_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DisplayNumbersDTO:
    """
    Результат расчёта display_num (номера уроков 2 смены) для дня класса.

    Заменяет dict[int, str] из
    ScheduleService.get_display_numbers_for_class_day().

    by_lesson_num: lesson_num -> display_num ("2", "5*", "•").
    """
    date_iso: str
    class_id: str
    by_lesson_num: Dict[int, str]


@dataclass
class FreeRoomsStatusDTO:
    """ Поиск свободных кабинетов """
    current_time_str: str
    is_finished: bool
    is_break: bool
    target_num: Optional[int]
    start_time: Optional[str]
    end_time: Optional[str]
    
    
# ==========================================================
# Аудит
# ==========================================================


class AuditAction(str, Enum):
    # Профиль и семья
    USER_REGISTERED = "user_registered"
    FAMILY_CREATED = "family_created"
    INVITE_CREATED = "invite_created"
    INVITE_USED = "invite_used"
    FAMILY_ADMIN_TRANSFERRED = "family_admin_transferred"
    PROFILE_RESET = "profile_reset"
    
    # Ученики
    VIRTUAL_STUDENT_CREATED = "virtual_student_created"
    VIRTUAL_STUDENT_DELETED = "virtual_student_deleted"
    STUDENT_CLAIMED = "student_claimed"
    
    # Настройки
    SETTINGS_CHANGED = "settings_changed"
    SETTINGS_LOCKED = "settings_locked"
    EXTRA_CLASS_PERMISSION_CHANGED = "extra_class_permission_changed"
    
    # Доп. занятия и отслеживание
    EXTRA_CLASS_ADDED = "extra_class_added"
    EXTRA_CLASS_DELETED = "extra_class_deleted"
    WATCH_TARGET_ADDED = "watch_target_added"

@dataclass(frozen=True, slots=True)
class AuditLogDTO:
    actor_id: int
    actor_name: str
    target_id: int
    target_name: str
    action: str
    timestamp: str

@dataclass(frozen=True, slots=True)
class FamilyAuditDTO(AuditLogDTO):
    role: str | None = None
    code: str | None = None

@dataclass(frozen=True, slots=True)
class ExtraClassAuditDTO(AuditLogDTO):
    title: str
    student_name: str
    
@dataclass(frozen=True, slots=True)
class SettingsAuditDTO(AuditLogDTO):
    setting_name: str
    new_value: str