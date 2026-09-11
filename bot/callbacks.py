# bot/callbacks.py
#
# ЭТАП 7: ЧИСТЫЙ НАТИВНЫЙ CALLBACK PROTOCOL ДЛЯ AIOGRAM 3.
#
# Правила:
# - Параметризованные callback_data создаются только CallbackData.pack().
# - Хендлеры фильтруют только XxxCD.filter() и получают типизированный
#   callback_data: XxxCD через dependency injection aiogram.
# - Классы/группы/учителя NIKA — строго str: "016" не становится "16".
# - Простые действия без параметров — короткие строковые константы.
# - Здесь НЕТ build_* / parse_* / legacy-совместимости намеренно.
# - Максимальный размер callback_data Telegram — 64 байта; все текущие
#   комбинации prefix + полей находятся с большим запасом ниже лимита.
#
# ФОРМАТ: prefix:field1:field2
# `:` зарезервирован aiogram как разделитель и НИКОГДА не содержится
# внутри prefix.

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


# ==============================================================
# Простые callback без параметров
# ==============================================================

# Общие / справка
SETTINGS_MAIN = "sm"
HELP_MAIN = "hm"

# Регистрация / claim / семья
FAMILY_CREATE = "fc"
FAMILY_JOIN = "fj"
FAMILY_SKIP = "fs"
CLAIM_CONFIRM = "cc"
CLAIM_CANCEL = "cx"

# Настройки
SETTINGS_FAMILY = "sf"
SETTINGS_NOTIFICATIONS = "sn"
SETTINGS_CHILDREN_NOTIFICATIONS = "scn"
SETTINGS_MY_NOTIFICATIONS = "smn"
SETTINGS_MY_SUMMARY_TIME = "sms"
SETTINGS_CHANGE_CLASS = "scc"
SETTINGS_CHANGE_TEACHER = "sct"
SETTINGS_CANCEL_INPUT = "sci"
SET_NOTIF_CHANGES = "nc"
SET_NOTIF_PRELESSON = "np"
SET_NOTIF_EXTRA = "ne"
SET_TIME_OFF = "so"
AUTH_RESTART = "ar"
AUTH_RESTART_CONFIRM = "arc"

# Семья
FAMILY_STUDENTS = "fstu"
FAMILY_INVITE_MENU = "fim"
FAMILY_INVITES = "fia"
FAMILY_TRANSFER = "fta"

# Допзанятия
EXTRA_STUDENTS = "xs"
EXTRA_CANCEL = "xc"
EXTRA_BACK = "xb"
EXTRA_SKIP_LOCATION = "xsl"
EXTRA_SKIP_REMINDER = "xsr"

# Schedule Hub
SCHEDULE_TARGETS = "ht"
SCHEDULE_SMART_DAY = "hs"

# Watch targets
WATCH_MENU = "wm"
WATCH_ADD = "wa"

# Self-edit class/group
SELF_EDIT_BACK_TO_CLASS = "eb"
SELF_EDIT_CANCEL = "ex"

# Teacher schedule
TEACHER_SCHEDULE_SMART_DAY = "ts"

# School search
SEARCH_BACK = "qb"
SEARCH_CLASSES = "qc"
SEARCH_TEACHERS = "qt"

STUDENT_ADD = "sa"

# ==============================================================
# Registration / onboarding
# ==============================================================

class RoleCD(CallbackData, prefix="r"):
    role: str


class RegistrationClassCD(CallbackData, prefix="c"):
    class_id: str


class RegistrationGroupCD(CallbackData, prefix="g"):
    group_id: str


class TeacherRegistrationCD(CallbackData, prefix="tr"):
    teacher_id: str


# ==============================================================
# Help
# ==============================================================

class HelpCD(CallbackData, prefix="hp"):
    section: str


# ==============================================================
# Family invitations
# ==============================================================

class FamilyInviteRoleCD(CallbackData, prefix="fir"):
    role: str

class FamilyTransferTargetCD(CallbackData, prefix="ftt"):
    """Выбор получателя полномочий (user_id другого родителя семьи)."""
    user_id: int


class FamilyTransferConfirmCD(CallbackData, prefix="ftc"):
    """Подтверждение передачи полномочий пользователю user_id."""
    user_id: int
    
class FamilyInviteDetailsCD(CallbackData, prefix="fiv"):
    invite_id: int


class FamilyInviteRevokeCD(CallbackData, prefix="fr"):
    invite_id: int


class FamilyInviteRevokeConfirmCD(CallbackData, prefix="frc"):
    invite_id: int


# ==============================================================
# Student profiles / virtual students
# ==============================================================

class VirtualStudentClassCD(CallbackData, prefix="ssc"):
    class_id: str


class VirtualStudentGroupCD(CallbackData, prefix="ssg"):
    group_id: str


class StudentDetailsCD(CallbackData, prefix="ssh"):
    student_id: int


class StudentDeleteCD(CallbackData, prefix="sdd"):
    student_id: int


class StudentDeleteConfirmCD(CallbackData, prefix="sdc"):
    student_id: int


class StudentClaimCD(CallbackData, prefix="scl"):
    student_id: int


class StudentEditStartCD(CallbackData, prefix="sei"):
    student_id: int


class StudentEditClassCD(CallbackData, prefix="sec"):
    student_id: int
    class_id: str


class StudentEditGroupCD(CallbackData, prefix="seg"):
    student_id: int
    group_id: str


class StudentExtraPermissionsCD(CallbackData, prefix="sep"):
    student_id: int


class AdultExtraPermissionToggleCD(CallbackData, prefix="apt"):
    student_id: int
    adult_user_id: int


# ==============================================================
# Telegram settings of linked student
# ==============================================================

class StudentTelegramSettingsCD(CallbackData, prefix="tsh"):
    student_id: int


class StudentTelegramToggleCD(CallbackData, prefix="tst"):
    setting: str
    student_id: int


class StudentTelegramSummaryCD(CallbackData, prefix="tsm"):
    student_id: int


class StudentTelegramSummaryOffCD(CallbackData, prefix="tso"):
    student_id: int


class StudentTelegramPrelessonCD(CallbackData, prefix="tsp"):
    student_id: int


class StudentTelegramLockCD(CallbackData, prefix="tsl"):
    student_id: int


# ==============================================================
# Personal adult subscriptions to student profile
# ==============================================================

class ParentStudentSettingsCD(CallbackData, prefix="psh"):
    student_id: int


class ParentStudentToggleCD(CallbackData, prefix="pst"):
    setting: str
    student_id: int


# ==============================================================
# Extra classes
# ==============================================================

class ExtraMenuCD(CallbackData, prefix="xm"):
    student_id: int


class ExtraListCD(CallbackData, prefix="xl"):
    student_id: int


class ExtraAddCD(CallbackData, prefix="xa"):
    student_id: int


class ExtraEditCD(CallbackData, prefix="xe"):
    student_id: int


class ExtraDeleteCD(CallbackData, prefix="xd"):
    student_id: int


class ExtraDayCD(CallbackData, prefix="xy"):
    day_of_week: int


class ExtraEditFieldCD(CallbackData, prefix="xf"):
    field: str
    extra_id: int


# ==============================================================
# Schedule Hub
# ==============================================================

class ScheduleTargetCD(CallbackData, prefix="htr"):
    kind: str
    target_id: int


class ScheduleWatchCD(CallbackData, prefix="hw"):
    target_id: int


class ScheduleDayCD(CallbackData, prefix="hd"):
    date_iso: str


class ScheduleWeekCD(CallbackData, prefix="hk"):
    week_start_iso: str


class ScheduleFullWeekCD(CallbackData, prefix="hf"):
    week_start_iso: str


# ==============================================================
# Watch targets
# ==============================================================

class WatchClassCD(CallbackData, prefix="wc"):
    class_id: str


class WatchGroupCD(CallbackData, prefix="wg"):
    group_id: str


class WatchDetailsCD(CallbackData, prefix="wh"):
    target_id: int


class WatchToggleCD(CallbackData, prefix="wt"):
    target_id: int


class WatchChangesCD(CallbackData, prefix="wn"):
    target_id: int


class WatchDeleteCD(CallbackData, prefix="wd"):
    target_id: int


class WatchDeleteConfirmCD(CallbackData, prefix="wx"):
    target_id: int


# ==============================================================
# Child self-edit
# ==============================================================

class SelfEditClassCD(CallbackData, prefix="ec"):
    class_id: str


class SelfEditGroupCD(CallbackData, prefix="eg"):
    group_id: str


# ==============================================================
# Personal teacher schedule / teacher profile
# ==============================================================

class TeacherScheduleDayCD(CallbackData, prefix="td"):
    date_iso: str


class TeacherScheduleWeekCD(CallbackData, prefix="tw"):
    week_start_iso: str


class TeacherScheduleFullWeekCD(CallbackData, prefix="tf"):
    week_start_iso: str


class TeacherChangeCD(CallbackData, prefix="tc"):
    teacher_id: str


# ==============================================================
# School search
# ==============================================================

class SearchClassCD(CallbackData, prefix="qcl"):
    class_id: str


class SearchTeacherCD(CallbackData, prefix="qte"):
    teacher_id: str


class SearchClassDayCD(CallbackData, prefix="qcd"):
    class_id: str
    date_iso: str


class SearchTeacherDayCD(CallbackData, prefix="qtd"):
    teacher_id: str
    date_iso: str


class SearchClassWeekCD(CallbackData, prefix="qcw"):
    class_id: str
    week_start_iso: str


class SearchTeacherWeekCD(CallbackData, prefix="qtw"):
    teacher_id: str
    week_start_iso: str


class SearchClassFullWeekCD(CallbackData, prefix="qcf"):
    class_id: str
    week_start_iso: str


class SearchTeacherFullWeekCD(CallbackData, prefix="qtf"):
    teacher_id: str
    week_start_iso: str
