# bot/callbacks.py
#
# ЭТАП 4: центральный протокол callback_data.
#
# Единственное место в проекте, где известен формат callback-строк:
# - билдеры (build_*) будут использоваться keyboard.py;
# - парсеры (parse_*) используются хендлерами;
# - константы префиксов — в magic-filter декораторах
#   (F.data == callbacks.XXX / F.data.startswith(callbacks.YYY_PREFIX)).
#
# КРИТИЧНОЕ ПРАВИЛО СОВМЕСТИМОСТИ: формат строк на проводе НЕ меняется
# (байт-в-байт с текущим keyboard.py) — кнопки, уже лежащие в чатах
# пользователей, продолжают работать. Изменение формата — осознанное
# решение, принимаемое ТОЛЬКО здесь и только с планом миграции.
#
# Конвенции:
# - разделитель частей: ':';
# - парсер возвращает None при любом несоответствии вместо исключения:
#   хендлер отвечает пользователю стандартным "некорректные данные";
# - парсер проверяет СТРУКТУРУ строки, но не семантику значений:
#   валидация class_id / дат остаётся в сервисах;
# - parse-методы строже старых split()-паттернов: лишние части
#   отклоняются (старый код мог молча взять [2] из более длинной
#   строки). Стандартные кнопки такие строки не порождают.
# bot/callbacks.py — v2 (полный инвентарь протокола)
#
# ЭТАП 4: центральный протокол callback_data.
#
# v2: добавлены все префиксы settings/search/teacher-домена.
# Источник истины для форматов — bot/keyboards/keyboard.py (сторона
# сборки): каждый билдер/парсер здесь сверён с фактически собираемыми
# строками. Формат на проводе НЕ изменён — старые кнопки работают.
#
# Конвенции:
# - разделитель ':';
# - парсер возвращает None при любом несоответствии (хендлер
#   отвечает alert'ом), исключений не бросает;
# - парсер проверяет структуру, но не семантику (валидация
#   class_id/дат — в сервисах);
# - parse-методы строже старых split()-паттернов: лишние части
#   отклоняются.

from __future__ import annotations

from typing import Optional

# ==============================================================
# HELP
# ==============================================================

HELP_PREFIX = "help:"

HELP_SECTIONS = frozenset({
    "main",
    "child",
    "parent",
    "observer",
    "teacher",
    "family",
    "notifications",
    "extras",
    "privacy",
    "support",
})


def build_help(section: str) -> str:
    return f"help:{section}"


def parse_help(data: str) -> Optional[str]:
    if not data.startswith(HELP_PREFIX):
        return None
    section = data[len(HELP_PREFIX):]
    if section not in HELP_SECTIONS:
        return None
    return section


# ==============================================================
# REGISTRATION
# ==============================================================

ROLE_PREFIX = "role:"

REGISTRATION_ROLES = frozenset({
    "child",
    "parent",
    "observer",
    "teacher",
})


def build_role(role: str) -> str:
    return f"role:{role}"


def parse_role(data: str) -> Optional[str]:
    if not data.startswith(ROLE_PREFIX):
        return None
    role = data[len(ROLE_PREFIX):]
    if role not in REGISTRATION_ROLES:
        return None
    return role


FAMILY_CREATE = "family:create"
FAMILY_JOIN = "family:join"
FAMILY_SKIP = "family:skip"

CLAIM_CONFIRM = "claim:confirm"
CLAIM_CANCEL = "claim:cancel"

CLASS_PREFIX = "class:"


def build_class_selection(class_id: str) -> str:
    return f"class:{class_id}"


def parse_class_selection(data: str) -> Optional[str]:
    if not data.startswith(CLASS_PREFIX):
        return None
    class_id = data[len(CLASS_PREFIX):]
    if not class_id:
        return None
    return class_id


GROUP_PREFIX = "group:"


def build_group_selection(group_id: str) -> str:
    return f"group:{group_id}"


def parse_group_selection(data: str) -> Optional[str]:
    # Семантика старого кода: split(":", 1)[1] — весь хвост.
    if not data.startswith(GROUP_PREFIX):
        return None
    group_id = data[len(GROUP_PREFIX):]
    if not group_id:
        return None
    return group_id


TEACHER_REG_PREFIX = "reg_teacher:"


def build_teacher_registration(teacher_id: str) -> str:
    return f"reg_teacher:{teacher_id}"


def parse_teacher_registration(data: str) -> Optional[str]:
    if not data.startswith(TEACHER_REG_PREFIX):
        return None
    teacher_id = data[len(TEACHER_REG_PREFIX):]
    if not teacher_id:
        return None
    return teacher_id


# ==============================================================
# EXTRA CLASSES
# ==============================================================

EXTRA_STUDENTS = "extra:students"
EXTRA_CANCEL = "extra:cancel"
EXTRA_BACK = "extra:back"

# Историческая особенность: skip-кнопки без префикса extra:.
SKIP_LOCATION = "skip_location"
SKIP_REMINDER = "skip_reminder"

EXTRA_MENU_PREFIX = "extra:menu:"
EXTRA_LIST_PREFIX = "extra:list:"
EXTRA_DELETE_PREFIX = "extra:delete:"
EXTRA_ADD_PREFIX = "extra:add:"
EXTRA_EDIT_PREFIX = "extra:edit:"


def _build_student_scoped(prefix: str, student_id: int) -> str:
    return f"{prefix}{student_id}"


def _parse_student_scoped(data: str, prefix: str) -> Optional[int]:
    if not data.startswith(prefix):
        return None
    raw = data[len(prefix):]
    if not raw.isdigit():
        return None
    return int(raw)


def build_extra_menu(student_id: int) -> str:
    return _build_student_scoped(EXTRA_MENU_PREFIX, student_id)


def parse_extra_menu(data: str) -> Optional[int]:
    return _parse_student_scoped(data, EXTRA_MENU_PREFIX)


def build_extra_list(student_id: int) -> str:
    return _build_student_scoped(EXTRA_LIST_PREFIX, student_id)


def parse_extra_list(data: str) -> Optional[int]:
    return _parse_student_scoped(data, EXTRA_LIST_PREFIX)


def build_extra_delete(student_id: int) -> str:
    return _build_student_scoped(EXTRA_DELETE_PREFIX, student_id)


def parse_extra_delete(data: str) -> Optional[int]:
    return _parse_student_scoped(data, EXTRA_DELETE_PREFIX)


def build_extra_add(student_id: int) -> str:
    return _build_student_scoped(EXTRA_ADD_PREFIX, student_id)


def parse_extra_add(data: str) -> Optional[int]:
    return _parse_student_scoped(data, EXTRA_ADD_PREFIX)


def build_extra_edit(student_id: int) -> str:
    return _build_student_scoped(EXTRA_EDIT_PREFIX, student_id)


def parse_extra_edit(data: str) -> Optional[int]:
    return _parse_student_scoped(data, EXTRA_EDIT_PREFIX)


EXTRA_DAY_PREFIX = "extraday:"


def build_extra_day(day_of_week: int) -> str:
    return f"extraday:{day_of_week}"


def parse_extra_day(data: str) -> Optional[int]:
    if not data.startswith(EXTRA_DAY_PREFIX):
        return None
    raw = data[len(EXTRA_DAY_PREFIX):]
    if not raw.isdigit():
        return None
    return int(raw)


EDIT_EXT_PREFIX = "edit_ext:"


def build_edit_field(field: str, extra_id: int) -> str:
    return f"edit_ext:{field}:{extra_id}"


def parse_edit_field(data: str) -> Optional[tuple[str, int]]:
    """
    Возвращает (field, extra_id) или None.

    Поле field не содержит ':' (title / time / loc / rem / day).
    """
    if not data.startswith(EDIT_EXT_PREFIX):
        return None
    parts = data.split(":")
    if len(parts) != 3:
        return None
    _, field, raw_extra_id = parts
    if not field or not raw_extra_id.isdigit():
        return None
    return field, int(raw_extra_id)


# ==============================================================
# SCHEDULE HUB (sched:*)
# ==============================================================

SCHED_TARGETS = "sched:targets"
SCHED_SMART_DAY = "sched:smart_day"

SCHEDULE_TARGET_KINDS = frozenset({
    "student",
    "watch",
})

SCHED_TARGET_PREFIX = "sched:target:"


def build_sched_target(kind: str, target_id: int) -> str:
    return f"sched:target:{kind}:{target_id}"


def parse_sched_target(data: str) -> Optional[tuple[str, int]]:
    if not data.startswith(SCHED_TARGET_PREFIX):
        return None
    parts = data.split(":")
    if len(parts) != 4:
        return None
    kind = parts[2]
    raw_id = parts[3]
    if kind not in SCHEDULE_TARGET_KINDS or not raw_id.isdigit():
        return None
    return kind, int(raw_id)


SCHED_WATCH_PREFIX = "sched:watch:"


def build_sched_watch(target_id: int) -> str:
    return f"sched:watch:{target_id}"


def parse_sched_watch(data: str) -> Optional[int]:
    if not data.startswith(SCHED_WATCH_PREFIX):
        return None
    raw = data[len(SCHED_WATCH_PREFIX):]
    if not raw.isdigit():
        return None
    return int(raw)


def _build_date_tail(prefix: str, date_iso: str) -> str:
    return f"{prefix}{date_iso}"


def _parse_date_tail(data: str, prefix: str) -> Optional[str]:
    if not data.startswith(prefix):
        return None
    date_iso = data[len(prefix):]
    if not date_iso:
        return None
    return date_iso


SCHED_DAY_PREFIX = "sched:day:"


def build_sched_day(date_iso: str) -> str:
    return _build_date_tail(SCHED_DAY_PREFIX, date_iso)


def parse_sched_day(data: str) -> Optional[str]:
    return _parse_date_tail(data, SCHED_DAY_PREFIX)


SCHED_WEEK_PREFIX = "sched:week:"


def build_sched_week(week_start_iso: str) -> str:
    return _build_date_tail(SCHED_WEEK_PREFIX, week_start_iso)


def parse_sched_week(data: str) -> Optional[str]:
    return _parse_date_tail(data, SCHED_WEEK_PREFIX)


SCHED_FULL_WEEK_PREFIX = "sched:full_week:"


def build_sched_full_week(week_start_iso: str) -> str:
    return _build_date_tail(SCHED_FULL_WEEK_PREFIX, week_start_iso)


def parse_sched_full_week(data: str) -> Optional[str]:
    return _parse_date_tail(data, SCHED_FULL_WEEK_PREFIX)


# ==============================================================
# SETTINGS: главное меню, уведомления, перерегистрация
# ==============================================================

SETTINGS_MAIN = "settings:main"
SETTINGS_FAMILY = "settings:family"
SETTINGS_NOTIFICATIONS = "settings:notifications"
SETTINGS_CHILDREN_NOTIFICATIONS = "settings:children_notifications"
SETTINGS_MY_NOTIFICATIONS = "settings:my_notifications"
SETTINGS_MY_SUMMARY_TIME = "settings:my_summary_time"
SETTINGS_CHANGE_CLASS = "settings:change_class"
SETTINGS_CHANGE_TEACHER = "settings:change_teacher"
SETTINGS_CANCEL_INPUT = "settings:cancel_input"

SET_NOTIF_CHANGES = "set_notif:changes"
SET_NOTIF_PRELESSON = "set_notif:prelesson"
SET_NOTIF_EXTRA = "set_notif:extra"
SET_TIME_OFF = "set_time:off"

AUTH_RESTART = "auth:restart"
AUTH_RESTART_CONFIRM = "auth:restart_confirm"


# ==============================================================
# FAMILY: ученики и приглашения
# ==============================================================

FAMILY_STUDENTS = "family:students"
FAMILY_INVITE_MENU = "family:invite_menu"
FAMILY_INVITES = "family:invites"

INVITE_ROLES = frozenset({
    "child",
    "parent",
    "observer",
})

FAMILY_INVITE_ROLE_PREFIX = "family:invite_role:"


def build_family_invite_role(role: str) -> str:
    return f"family:invite_role:{role}"


def parse_family_invite_role(data: str) -> Optional[str]:
    if not data.startswith(FAMILY_INVITE_ROLE_PREFIX):
        return None
    role = data[len(FAMILY_INVITE_ROLE_PREFIX):]
    if role not in INVITE_ROLES:
        return None
    return role


def _parse_invite_id(data: str, prefix: str) -> Optional[int]:
    if not data.startswith(prefix):
        return None
    raw = data[len(prefix):]
    if not raw.isdigit():
        return None
    return int(raw)


FAMILY_INVITE_PREFIX = "family:invite:"
FAMILY_INVITE_REVOKE_PREFIX = "family:invite_revoke:"
FAMILY_INVITE_REVOKE_CONFIRM_PREFIX = "family:invite_revoke_confirm:"


def build_family_invite(invite_id: int) -> str:
    return f"family:invite:{invite_id}"


def parse_family_invite(data: str) -> Optional[int]:
    return _parse_invite_id(data, FAMILY_INVITE_PREFIX)


def build_family_invite_revoke(invite_id: int) -> str:
    return f"family:invite_revoke:{invite_id}"


def parse_family_invite_revoke(data: str) -> Optional[int]:
    return _parse_invite_id(data, FAMILY_INVITE_REVOKE_PREFIX)


def build_family_invite_revoke_confirm(invite_id: int) -> str:
    return f"family:invite_revoke_confirm:{invite_id}"


def parse_family_invite_revoke_confirm(data: str) -> Optional[int]:
    return _parse_invite_id(data, FAMILY_INVITE_REVOKE_CONFIRM_PREFIX)


# ==============================================================
# STUDENT: профили семьи
# ==============================================================

STUDENT_ADD = "student:add"

STUDENT_CLASS_PREFIX = "student:class:"
STUDENT_GROUP_PREFIX = "student:group:"
STUDENT_SHOW_PREFIX = "student:show:"
STUDENT_DELETE_PREFIX = "student:delete:"
STUDENT_DELETE_CONFIRM_PREFIX = "student:delete_confirm:"
STUDENT_CLAIM_PREFIX = "student:claim:"
STUDENT_EDIT_CLASS_PREFIX = "student:edit_class:"
STUDENT_EDIT_CLASS_SELECT_PREFIX = "student:edit_class_select:"
STUDENT_EDIT_GROUP_SELECT_PREFIX = "student:edit_group_select:"
STUDENT_EXTRA_PERMISSIONS_PREFIX = "student:extra_permissions:"


def _parse_str_tail(data: str, prefix: str) -> Optional[str]:
    if not data.startswith(prefix):
        return None
    value = data[len(prefix):]
    if not value:
        return None
    return value


def build_student_class(class_id: str) -> str:
    return f"student:class:{class_id}"


def parse_student_class(data: str) -> Optional[str]:
    return _parse_str_tail(data, STUDENT_CLASS_PREFIX)


def build_student_group(group_id: str) -> str:
    return f"student:group:{group_id}"


def parse_student_group(data: str) -> Optional[str]:
    return _parse_str_tail(data, STUDENT_GROUP_PREFIX)


def _parse_int_tail(data: str, prefix: str) -> Optional[int]:
    return _parse_invite_id(data, prefix)


def build_student_show(student_id: int) -> str:
    return f"student:show:{student_id}"


def parse_student_show(data: str) -> Optional[int]:
    return _parse_int_tail(data, STUDENT_SHOW_PREFIX)


def build_student_delete(student_id: int) -> str:
    return f"student:delete:{student_id}"


def parse_student_delete(data: str) -> Optional[int]:
    return _parse_int_tail(data, STUDENT_DELETE_PREFIX)


def build_student_delete_confirm(student_id: int) -> str:
    return f"student:delete_confirm:{student_id}"


def parse_student_delete_confirm(data: str) -> Optional[int]:
    return _parse_int_tail(data, STUDENT_DELETE_CONFIRM_PREFIX)


def build_student_claim(student_id: int) -> str:
    return f"student:claim:{student_id}"


def parse_student_claim(data: str) -> Optional[int]:
    return _parse_int_tail(data, STUDENT_CLAIM_PREFIX)


def build_student_edit_class(student_id: int) -> str:
    return f"student:edit_class:{student_id}"


def parse_student_edit_class(data: str) -> Optional[int]:
    return _parse_int_tail(data, STUDENT_EDIT_CLASS_PREFIX)


def build_student_extra_permissions(student_id: int) -> str:
    return f"student:extra_permissions:{student_id}"


def parse_student_extra_permissions(data: str) -> Optional[int]:
    return _parse_int_tail(data, STUDENT_EXTRA_PERMISSIONS_PREFIX)


def build_student_edit_class_select(student_id: int, class_id: str) -> str:
    return f"student:edit_class_select:{student_id}:{class_id}"


def parse_student_edit_class_select(
    data: str,
) -> Optional[tuple[int, str]]:
    if not data.startswith(STUDENT_EDIT_CLASS_SELECT_PREFIX):
        return None
    parts = data.split(":")
    if len(parts) != 4 or not parts[2].isdigit() or not parts[3]:
        return None
    return int(parts[2]), parts[3]


def build_student_edit_group_select(student_id: int, group_id: str) -> str:
    return f"student:edit_group_select:{student_id}:{group_id}"


def parse_student_edit_group_select(
    data: str,
) -> Optional[tuple[int, str]]:
    if not data.startswith(STUDENT_EDIT_GROUP_SELECT_PREFIX):
        return None
    parts = data.split(":")
    if len(parts) != 4 or not parts[2].isdigit() or not parts[3]:
        return None
    return int(parts[2]), parts[3]


# ==============================================================
# PSN / STUDENT_TG / STUDENT_PERM
# ==============================================================

PSN_STUDENT_PREFIX = "psn:student:"
PSN_TOGGLE_PREFIX = "psn:toggle:"

PSN_TOGGLE_TOKENS = frozenset({
    "morning",
    "prelesson",
    "changes",
    "extra",
})


def build_psn_student(student_id: int) -> str:
    return f"psn:student:{student_id}"


def parse_psn_student(data: str) -> Optional[int]:
    return _parse_int_tail(data, PSN_STUDENT_PREFIX)


def build_psn_toggle(setting_token: str, student_id: int) -> str:
    return f"psn:toggle:{setting_token}:{student_id}"


def parse_psn_toggle(data: str) -> Optional[tuple[str, int]]:
    if not data.startswith(PSN_TOGGLE_PREFIX):
        return None
    parts = data.split(":")
    if len(parts) != 4 or parts[2] not in PSN_TOGGLE_TOKENS:
        return None
    if not parts[3].isdigit():
        return None
    return parts[2], int(parts[3])


STUDENT_TG_SHOW_PREFIX = "student_tg:show:"
STUDENT_TG_SUMMARY_PREFIX = "student_tg:summary:"
STUDENT_TG_SUMMARY_OFF_PREFIX = "student_tg:summary_off:"
STUDENT_TG_PRELESSON_PREFIX = "student_tg:prelesson:"
STUDENT_TG_LOCK_PREFIX = "student_tg:lock:"
STUDENT_TG_TOGGLE_PREFIX = "student_tg:toggle:"

STUDENT_TG_TOGGLE_TOKENS = frozenset({
    "notif",
    "changes",
    "extra",
    "own_extra",
})


def build_student_tg_show(student_id: int) -> str:
    return f"student_tg:show:{student_id}"


def parse_student_tg_show(data: str) -> Optional[int]:
    return _parse_int_tail(data, STUDENT_TG_SHOW_PREFIX)


def build_student_tg_summary(student_id: int) -> str:
    return f"student_tg:summary:{student_id}"


def parse_student_tg_summary(data: str) -> Optional[int]:
    return _parse_int_tail(data, STUDENT_TG_SUMMARY_PREFIX)


def build_student_tg_summary_off(student_id: int) -> str:
    return f"student_tg:summary_off:{student_id}"


def parse_student_tg_summary_off(data: str) -> Optional[int]:
    return _parse_int_tail(data, STUDENT_TG_SUMMARY_OFF_PREFIX)


def build_student_tg_prelesson(student_id: int) -> str:
    return f"student_tg:prelesson:{student_id}"


def parse_student_tg_prelesson(data: str) -> Optional[int]:
    return _parse_int_tail(data, STUDENT_TG_PRELESSON_PREFIX)


def build_student_tg_lock(student_id: int) -> str:
    return f"student_tg:lock:{student_id}"


def parse_student_tg_lock(data: str) -> Optional[int]:
    return _parse_int_tail(data, STUDENT_TG_LOCK_PREFIX)


def build_student_tg_toggle(setting_token: str, student_id: int) -> str:
    return f"student_tg:toggle:{setting_token}:{student_id}"


def parse_student_tg_toggle(data: str) -> Optional[tuple[str, int]]:
    if not data.startswith(STUDENT_TG_TOGGLE_PREFIX):
        return None
    parts = data.split(":")
    if len(parts) != 4 or parts[2] not in STUDENT_TG_TOGGLE_TOKENS:
        return None
    if not parts[3].isdigit():
        return None
    return parts[2], int(parts[3])


STUDENT_PERM_TOGGLE_PREFIX = "student_perm:toggle:"


def build_student_perm_toggle(
    student_id: int,
    adult_user_id: int,
) -> str:
    return f"student_perm:toggle:{student_id}:{adult_user_id}"


def parse_student_perm_toggle(
    data: str,
) -> Optional[tuple[int, int]]:
    if not data.startswith(STUDENT_PERM_TOGGLE_PREFIX):
        return None
    parts = data.split(":")
    if (
        len(parts) != 4
        or not parts[2].isdigit()
        or not parts[3].isdigit()
    ):
        return None
    return int(parts[2]), int(parts[3])


# ==============================================================
# WATCH TARGETS
# ==============================================================

WATCH_MENU = "watch:menu"
WATCH_ADD = "watch:add"

WATCH_CLASS_PREFIX = "watch:class:"
WATCH_GROUP_PREFIX = "watch:group:"
WATCH_TARGET_PREFIX = "watch:target:"
WATCH_TOGGLE_PREFIX = "watch:toggle:"
WATCH_CHANGES_PREFIX = "watch:changes:"
WATCH_DELETE_PREFIX = "watch:delete:"
WATCH_DELETE_CONFIRM_PREFIX = "watch:delete_confirm:"


def build_watch_class(class_id: str) -> str:
    return f"watch:class:{class_id}"


def parse_watch_class(data: str) -> Optional[str]:
    return _parse_str_tail(data, WATCH_CLASS_PREFIX)


def build_watch_group(group_id: str) -> str:
    return f"watch:group:{group_id}"


def parse_watch_group(data: str) -> Optional[str]:
    return _parse_str_tail(data, WATCH_GROUP_PREFIX)


def _parse_watch_target_id(data: str, prefix: str) -> Optional[int]:
    return _parse_int_tail(data, prefix)


def build_watch_target(target_id: int) -> str:
    return f"watch:target:{target_id}"


def parse_watch_target(data: str) -> Optional[int]:
    return _parse_watch_target_id(data, WATCH_TARGET_PREFIX)


def build_watch_toggle(target_id: int) -> str:
    return f"watch:toggle:{target_id}"


def parse_watch_toggle(data: str) -> Optional[int]:
    return _parse_watch_target_id(data, WATCH_TOGGLE_PREFIX)


def build_watch_changes(target_id: int) -> str:
    return f"watch:changes:{target_id}"


def parse_watch_changes(data: str) -> Optional[int]:
    return _parse_watch_target_id(data, WATCH_CHANGES_PREFIX)


def build_watch_delete(target_id: int) -> str:
    return f"watch:delete:{target_id}"


def parse_watch_delete(data: str) -> Optional[int]:
    return _parse_watch_target_id(data, WATCH_DELETE_PREFIX)


def build_watch_delete_confirm(target_id: int) -> str:
    return f"watch:delete_confirm:{target_id}"


def parse_watch_delete_confirm(data: str) -> Optional[int]:
    return _parse_watch_target_id(data, WATCH_DELETE_CONFIRM_PREFIX)


# ==============================================================
# SELF-EDIT (child меняет свой класс/группу)
# ==============================================================

SELF_EDIT_CLASS_PREFIX = "self_edit:class:"
SELF_EDIT_GROUP_PREFIX = "self_edit:group:"
SELF_EDIT_BACK_TO_CLASS = "self_edit:back_to_class"
SELF_EDIT_CANCEL = "self_edit:cancel"


def build_self_edit_class(class_id: str) -> str:
    return f"self_edit:class:{class_id}"


def parse_self_edit_class(data: str) -> Optional[str]:
    return _parse_str_tail(data, SELF_EDIT_CLASS_PREFIX)


def build_self_edit_group(group_id: str) -> str:
    return f"self_edit:group:{group_id}"


def parse_self_edit_group(data: str) -> Optional[str]:
    return _parse_str_tail(data, SELF_EDIT_GROUP_PREFIX)


# ==============================================================
# TEACHER SCHEDULE / TEACHER CHANGE
# ==============================================================

TEACHER_SCHED_SMART_DAY = "teacher_sched:smart_day"

TEACHER_SCHED_DAY_PREFIX = "teacher_sched:day:"
TEACHER_SCHED_WEEK_PREFIX = "teacher_sched:week:"
TEACHER_SCHED_FULL_WEEK_PREFIX = "teacher_sched:full_week:"
TEACHER_CHANGE_PREFIX = "teacher_change:"


def build_teacher_sched_day(date_iso: str) -> str:
    return _build_date_tail(TEACHER_SCHED_DAY_PREFIX, date_iso)


def parse_teacher_sched_day(data: str) -> Optional[str]:
    return _parse_date_tail(data, TEACHER_SCHED_DAY_PREFIX)


def build_teacher_sched_week(week_start_iso: str) -> str:
    return _build_date_tail(TEACHER_SCHED_WEEK_PREFIX, week_start_iso)


def parse_teacher_sched_week(data: str) -> Optional[str]:
    return _parse_date_tail(data, TEACHER_SCHED_WEEK_PREFIX)


def build_teacher_sched_full_week(week_start_iso: str) -> str:
    return _build_date_tail(
        TEACHER_SCHED_FULL_WEEK_PREFIX,
        week_start_iso,
    )


def parse_teacher_sched_full_week(data: str) -> Optional[str]:
    return _parse_date_tail(data, TEACHER_SCHED_FULL_WEEK_PREFIX)


def build_teacher_change(teacher_id: str) -> str:
    return f"teacher_change:{teacher_id}"


def parse_teacher_change(data: str) -> Optional[str]:
    return _parse_str_tail(data, TEACHER_CHANGE_PREFIX)


# ==============================================================
# SEARCH (поиск по школе)
# ==============================================================

SEARCH_BACK = "search:back"
SEARCH_CLASSES = "search:classes"
SEARCH_TEACHERS = "search:teachers"

SEARCH_CLASS_PREFIX = "srch_cls:"
SEARCH_TEACHER_PREFIX = "srch_tch:"

SEARCH_CLASS_DAY_PREFIX = "sch_c:"
SEARCH_TEACHER_DAY_PREFIX = "sch_t:"
SEARCH_CLASS_WEEK_PREFIX = "sch_c_w:"
SEARCH_TEACHER_WEEK_PREFIX = "sch_t_w:"
SEARCH_CLASS_FULL_WEEK_PREFIX = "sch_c_fw:"
SEARCH_TEACHER_FULL_WEEK_PREFIX = "sch_t_fw:"


def build_search_class(class_id: str) -> str:
    return f"srch_cls:{class_id}"


def parse_search_class(data: str) -> Optional[str]:
    return _parse_str_tail(data, SEARCH_CLASS_PREFIX)


def build_search_teacher(teacher_id: str) -> str:
    return f"srch_tch:{teacher_id}"


def parse_search_teacher(data: str) -> Optional[str]:
    return _parse_str_tail(data, SEARCH_TEACHER_PREFIX)


def _build_search_target_date(
    prefix: str,
    target_id: str,
    date_iso: str,
) -> str:
    return f"{prefix}{target_id}:{date_iso}"


def _parse_search_target_date(
    data: str,
    prefix: str,
) -> Optional[tuple[str, str]]:
    """
    Возвращает (target_id, date_iso) или None.

    Формат: prefix + target_id + ':' + ISO-дата (без ':').
    Старая семантика: split(":") ровно на 3 части.
    """
    if not data.startswith(prefix):
        return None
    parts = data.split(":")
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def build_search_class_day(class_id: str, date_iso: str) -> str:
    return _build_search_target_date(
        SEARCH_CLASS_DAY_PREFIX,
        class_id,
        date_iso,
    )


def parse_search_class_day(data: str) -> Optional[tuple[str, str]]:
    return _parse_search_target_date(data, SEARCH_CLASS_DAY_PREFIX)


def build_search_teacher_day(teacher_id: str, date_iso: str) -> str:
    return _build_search_target_date(
        SEARCH_TEACHER_DAY_PREFIX,
        teacher_id,
        date_iso,
    )


def parse_search_teacher_day(data: str) -> Optional[tuple[str, str]]:
    return _parse_search_target_date(data, SEARCH_TEACHER_DAY_PREFIX)


def build_search_class_week(class_id: str, week_start_iso: str) -> str:
    return _build_search_target_date(
        SEARCH_CLASS_WEEK_PREFIX,
        class_id,
        week_start_iso,
    )


def parse_search_class_week(data: str) -> Optional[tuple[str, str]]:
    return _parse_search_target_date(data, SEARCH_CLASS_WEEK_PREFIX)


def build_search_teacher_week(
    teacher_id: str,
    week_start_iso: str,
) -> str:
    return _build_search_target_date(
        SEARCH_TEACHER_WEEK_PREFIX,
        teacher_id,
        week_start_iso,
    )


def parse_search_teacher_week(data: str) -> Optional[tuple[str, str]]:
    return _parse_search_target_date(data, SEARCH_TEACHER_WEEK_PREFIX)


def build_search_class_full_week(
    class_id: str,
    week_start_iso: str,
) -> str:
    return _build_search_target_date(
        SEARCH_CLASS_FULL_WEEK_PREFIX,
        class_id,
        week_start_iso,
    )


def parse_search_class_full_week(
    data: str,
) -> Optional[tuple[str, str]]:
    return _parse_search_target_date(
        data,
        SEARCH_CLASS_FULL_WEEK_PREFIX,
    )


def build_search_teacher_full_week(
    teacher_id: str,
    week_start_iso: str,
) -> str:
    return _build_search_target_date(
        SEARCH_TEACHER_FULL_WEEK_PREFIX,
        teacher_id,
        week_start_iso,
    )


def parse_search_teacher_full_week(
    data: str,
) -> Optional[tuple[str, str]]:
    return _parse_search_target_date(
        data,
        SEARCH_TEACHER_FULL_WEEK_PREFIX,
    )
