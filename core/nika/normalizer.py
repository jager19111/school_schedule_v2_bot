# core/nika/normalizer.py
#
# ИСПРАВЛЕНИЯ P0:
# 1. Merge частичных exchange-слотов (предмет/учитель/кабинет/группа).
# 2. Пустой предмет → is_cancelled=True (по ТЗ).
# 3. Методический час = 1 запись, а не по числу групп.
# 4. Стабильные lesson_id без idx (детерминированные).
# 5. Логирование отсутствия активного периода.
# 6. Обработка отсутствующего LESSON_TIMES с логированием, а не исключением.

from typing import List, Dict, Any, Tuple, Optional
import datetime
import re
import logging
from core.models.domain import Class, Teacher, Room, Subject, Period, LessonInstance
from core.nika.exceptions import ScheduleDataError


logger = logging.getLogger(__name__)


class NikaNormalizer:
    """
    Нормализатор данных NIKA-Soft.
    
    Преобразует сырой JS/JSON из nika_data_*.js в типизированные LessonInstance.
    Поддерживает:
    - CLASS_SCHEDULE / CLASS_EXCHANGE (расписание классов)
    - TEACH_SCHEDULE / TEACH_EXCHANGE (расписание учителей)
    - Отмены ("F"), методические часы ("M")
    - Замены с сохранением «было → стало」включая группы
    """
    
    def __init__(self, nika_data: Dict[str, Any]):
        self.data = nika_data
        self.classes, self.teachers, self.rooms, self.subjects = self.build_metadata()
# Явно указываем типы, чтобы VS Code понимал, что это словари
        self.class_groups: Dict[str, str] = self.data.get("CLASSGROUPS", {})
        self.lesson_times: Dict[str, List[str]] = self.data.get("LESSON_TIMES", {})
        self.periods: Dict[str, Dict[str, str]] = self.data.get("PERIODS", {})
        
    def _clean_val(self, val: Any) -> Optional[str]:
        """Очистка пустых строк в массивах NIKA."""
        if not val or str(val).strip() == "":
            return None
        return str(val).strip()


    def build_metadata(self) -> Tuple[Dict[str, Class], Dict[str, Teacher], Dict[str, Room], Dict[str, Subject]]:
        classes = {}
        for c_id, c_name in self.data.get("CLASSES", {}).items():
            course_str = self.data.get("CLASS_COURSES", {}).get(c_id)
            if course_str:
                course = int(course_str)
            else:
                match = re.search(r'^(\d+)', c_name)
                course = int(match.group(1)) if match else 0
            classes[c_id] = Class(id=c_id, name=c_name, course=course)


        teachers = {t_id: Teacher(id=t_id, name=name) for t_id, name in self.data.get("TEACHERS", {}).items()}
        rooms = {r_id: Room(id=r_id, name=name) for r_id, name in self.data.get("ROOMS", {}).items()}
        subjects = {s_id: Subject(id=s_id, name=name) for s_id, name in self.data.get("SUBJECTS", {}).items()}
        
        return classes, teachers, rooms, subjects


    def _get_active_period(self, target_date: datetime.date) -> str | None:
        """
        Поиск активного учебного периода.
        Если дата находится в будущем (дальше всех заведенных в NIKA периодов),
        экстраполируем на неё базовое расписание из последнего известного периода.
        """
        latest_period_id = None
        latest_end_date = datetime.date.min

        for p_id, p_data in self.periods.items():
            try:
                # В NIKA даты в формате "DD.MM.YYYY"
                b_date = datetime.datetime.strptime(p_data["b"], "%d.%m.%Y").date()
                e_date = datetime.datetime.strptime(p_data["e"], "%d.%m.%Y").date()
                
                # 1. Точное попадание в официально заданный период
                if b_date <= target_date <= e_date:
                    return p_id
                
                # Запоминаем самый поздний период из всех существующих
                if e_date > latest_end_date:
                    latest_end_date = e_date
                    latest_period_id = p_id
            except (ValueError, KeyError):
                continue

        # 2. Предиктивная экстраполяция в будущее
        # Если запрашиваемая дата больше конца последнего периода (школа еще не продлила даты),
        # мы предполагаем, что базовая сетка уроков продолжится.
        # На даты из прошлого не экстраполируем, чтобы не портить историю.
        if latest_end_date != datetime.date.min and target_date > latest_end_date:
            return latest_period_id

        return None
    
    if False: # старый метод где расписание строго соответствует расписанию нан сайте. Оставить для возможного отката
        def _get_active_period(self, target_date: datetime.date) -> str | None:
            """Поиск активного учебного периода для заданной даты."""
            for p_id, p_data in self.periods.items():
                try:
                    # В NIKA даты в формате "DD.MM.YYYY"
                    b_date = datetime.datetime.strptime(p_data["b"], "%d.%m.%Y").date()
                    e_date = datetime.datetime.strptime(p_data["e"], "%d.%m.%Y").date()
                    if b_date <= target_date <= e_date:
                        return p_id
                except (ValueError, KeyError):
                    continue
            return None



    def _lesson_numbers_for_day(self, base_schedule: dict, exchanges: dict, weekday: int) -> list[int]:
        prefix = str(weekday)
        numbers = set()
        for key in base_schedule:
            key = str(key)
            if key.startswith(prefix) and key[1:].isdigit():
                numbers.add(int(key[1:]))
        for key in exchanges:
            key = str(key)
            if key.isdigit():
                numbers.add(int(key))
        return sorted(numbers)


    def _get_lesson_time(self, lesson_num: int) -> tuple[str, str] | None:
        """
        Возвращает (start, end) или None при отсутствии LESSON_TIMES.
        Не поднимает исключение — ошибка логируется и урок пропускается.
        """
        value = self.lesson_times.get(str(lesson_num))
        if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, str) and item.strip() for item in value):
            import logging
            logging.getLogger(__name__).warning("Missing or invalid LESSON_TIMES[%s]", lesson_num)
            return None
        return value[0].strip(), value[1].strip()

    @staticmethod
    def _is_whole_class_lesson(raw_s: list, raw_g: list, is_teacher_mode: bool) -> bool:
        """
        Определяет, весь ли это класс или урок с группами.
        """
        if not raw_g:
            return True  # Нет массива групп -> точно весь класс
            
        if is_teacher_mode:
            return False # Учителя ведут свою группу, если g есть - это подгруппа
            
        # ИСПРАВЛЕНИЕ: Убрана багованная логика (non_empty_subjects <= 1).
        # Если NIKA прислала массив групп (например ["0", "1"]), это урок с подгруппами,
        # даже если 1-я подгруппа отменена ("") и активна только вторая.
        # Исключение: NIKA прислала номинальный пустой массив [""] или ["ALL"]
        if len(raw_g) == 1 and str(raw_g[0]).strip() in ("", "ALL"):
            return True
            
        return False

    def _process_slot(
        self,
        slot_base: dict,
        slot_exchange: dict,
        lesson_num: int,
        iso_date: str,
        weekday: int,
        period_id: str,
        context_id: str,
        is_teacher_mode: bool,
    ) -> List[LessonInstance]:
        lessons = []
        is_exchange = bool(slot_exchange)
        is_methodological = False

        def _ensure_list(val):
            if not val: return []
            return val if isinstance(val, list) else [val]

        # Определяем ПОЛНУЮ отмену (когда прислали просто "F" для всех)
        raw_s_from_exchange = _ensure_list(slot_exchange.get("s")) if slot_exchange else []
        is_full_cancel = (raw_s_from_exchange == ["F"])
        
        # 1. Сначала делаем Умное слияние (Merge) частичных замен и базового расписания
        if is_exchange and slot_exchange:
            raw_s = _ensure_list(slot_exchange.get("s")) if "s" in slot_exchange else _ensure_list(slot_base.get("s"))
            target_key = "c" if is_teacher_mode else "t"
            raw_t_or_c = _ensure_list(slot_exchange.get(target_key)) if target_key in slot_exchange else _ensure_list(slot_base.get(target_key))
            raw_r = _ensure_list(slot_exchange.get("r")) if "r" in slot_exchange else _ensure_list(slot_base.get("r"))
            raw_g = _ensure_list(slot_exchange.get("g")) if "g" in slot_exchange else _ensure_list(slot_base.get("g"))
        else:
            active_slot = slot_base
            target_key = "c" if is_teacher_mode else "t"
            raw_s = _ensure_list(active_slot.get("s")) if not is_full_cancel else []
            raw_t_or_c = _ensure_list(active_slot.get(target_key)) if not is_full_cancel else []
            raw_r = _ensure_list(active_slot.get("r")) if not is_full_cancel else []
            raw_g = _ensure_list(active_slot.get("g")) if not is_full_cancel else []

        # 2. ТЕПЕРЬ проверяем метод. час: он может быть как в базовом расписании, так и в замене!
        if is_teacher_mode and raw_s and raw_s[0] == "M":
            is_methodological = True
            raw_s = ["M"]
            raw_t_or_c, raw_r, raw_g = [], [], []

        orig_s = _ensure_list(slot_base.get("s")) if slot_base else []
        orig_target_key = "c" if is_teacher_mode else "t"
        orig_t_or_c = _ensure_list(slot_base.get(orig_target_key)) if slot_base else []
        orig_r = _ensure_list(slot_base.get("r")) if slot_base else []
        orig_g = _ensure_list(slot_base.get("g")) if slot_base else []

        lesson_time = self._get_lesson_time(lesson_num)
        if lesson_time is None:
            return lessons
        
        start_time, end_time = lesson_time


        # P2 (финальная версия): ИСПРАВЛЕНО — логика max_len
        #
        # Определяем, весь ли это класс или урок с группами
        # Было: is_whole_class = self._is_whole_class_lesson(raw_s, raw_g)
        # Стало:
        is_whole_class = self._is_whole_class_lesson(raw_s, raw_g, is_teacher_mode)
        
        if is_whole_class:
            # Урок для всего класса → 1 LessonInstance
            max_len = 1
        elif is_full_cancel or is_methodological:
            # Для отмен и методических часов используем оригинальные группы
            max_len = max(len(orig_g), 1) if orig_g else 1
        else:
            # Урок с группами → разворачиваем по g
            max_len = max(len(raw_g), len(raw_s), len(raw_t_or_c), len(raw_r))


        if max_len == 0:
            return lessons


        for idx in range(max_len):
            current_raw_s = raw_s[idx] if idx < len(raw_s) else None
            
            # --- ИСПРАВЛЕНИЕ: Обработка отмен подгрупп ("" или "F") ---
            # В NIKA пустая строка в массиве (например, s=["", "012"]) означает отмену 
            # конкретной подгруппы. Если мы сделаем continue, подгруппа исчезнет из базы!
            clean_s_temp = self._clean_val(current_raw_s)
            is_full_cancel_pointwise = (clean_s_temp is None or clean_s_temp == "F")
            
            is_cancelled = is_full_cancel or is_full_cancel_pointwise

            clean_s = clean_s_temp if not is_cancelled else None
            clean_t_c = self._clean_val(raw_t_or_c[idx]) if idx < len(raw_t_or_c) else None
            clean_r = self._clean_val(raw_r[idx]) if idx < len(raw_r) else None
            
            # При полной отмене восстанавливаем оригинальную группу
            if is_full_cancel:
                g_id = orig_g[idx] if idx < len(orig_g) else "ALL"
            else:
                # P2: Если весь класс → "ALL", иначе → из массива g
                if is_whole_class:
                    g_id = "ALL"
                else:
                    g_id = raw_g[idx] if idx < len(raw_g) else "ALL"
                
            clean_g = self._clean_val(g_id)

            o_clean_s = self._clean_val(orig_s[idx]) if idx < len(orig_s) else None
            o_clean_t_c = self._clean_val(orig_t_or_c[idx]) if idx < len(orig_t_or_c) else None
            o_clean_r = self._clean_val(orig_r[idx]) if idx < len(orig_r) else None
            o_clean_g = self._clean_val(orig_g[idx]) if idx < len(orig_g) else None

            if is_methodological:
                sub_name = "Методический час/день"
            else:
                sub_name = self.subjects.get(clean_s).name if clean_s and clean_s in self.subjects else ("ОТМЕНА" if is_cancelled else None)
            
            if o_clean_s == "M":
                orig_sub_name = "Методический час/день"
            else:
                orig_sub_name = self.subjects.get(o_clean_s).name if o_clean_s and o_clean_s in self.subjects else None
            rom_name = self.rooms.get(clean_r).name if clean_r and clean_r in self.rooms else None
            orig_rom_name = self.rooms.get(o_clean_r).name if o_clean_r and o_clean_r in self.rooms else None
            orig_grp_name = self.class_groups.get(o_clean_g) if o_clean_g and o_clean_g != "ALL" else None

            if is_cancelled:
                safe_g_id = o_clean_g if o_clean_g else "ALL"
            else:
                safe_g_id = clean_g if clean_g and clean_g != "ALL" else "ALL"
            
            grp_name = self.class_groups.get(safe_g_id, "Весь класс") if safe_g_id != "ALL" else "Весь класс"

            if is_teacher_mode:
                effective_class_id = clean_t_c if clean_t_c else f"TEACHER_{context_id}"
                lesson_id = f"T{context_id}_{period_id}_{effective_class_id}_{iso_date}_{lesson_num}_{safe_g_id}"
                cls_name = self.classes.get(clean_t_c).name if clean_t_c and clean_t_c in self.classes else None
                orig_cls_name = self.classes.get(o_clean_t_c).name if o_clean_t_c and o_clean_t_c in self.classes else None
                
                lessons.append(LessonInstance(
                    id=lesson_id, period_id=period_id, class_id=effective_class_id, class_name=cls_name,
                    date=iso_date, weekday=weekday, lesson_num=lesson_num, start_time=start_time, end_time=end_time,
                    subject_id=clean_s, subject_name=sub_name, 
                    teacher_id=context_id, teacher_name=self.teachers.get(context_id).name if context_id in self.teachers else None,
                    room_id=clean_r, room_name=rom_name,
                    original_subject_id=o_clean_s, original_subject_name=orig_sub_name,
                    original_teacher_id=None, original_teacher_name=None,
                    original_room_id=o_clean_r, original_room_name=orig_rom_name,
                    original_class_id=o_clean_t_c, original_class_name=orig_cls_name,
                    original_group_id=o_clean_g, original_group_name=orig_grp_name,
                    group_id=safe_g_id, group_name=grp_name,
                    is_exchange=is_exchange, is_cancelled=is_cancelled, is_methodological=is_methodological
                ))
            else:
                lesson_id = f"{period_id}_{context_id}_{iso_date}_{lesson_num}_{safe_g_id}"
                tea_name = self.teachers.get(clean_t_c).name if clean_t_c and clean_t_c in self.teachers else None
                orig_tea_name = self.teachers.get(o_clean_t_c).name if o_clean_t_c and o_clean_t_c in self.teachers else None
                
                lessons.append(LessonInstance(
                    id=lesson_id, period_id=period_id, class_id=context_id, 
                    class_name=self.classes.get(context_id).name if context_id in self.classes else None,
                    date=iso_date, weekday=weekday, lesson_num=lesson_num, start_time=start_time, end_time=end_time,
                    subject_id=clean_s, subject_name=sub_name, 
                    teacher_id=clean_t_c, teacher_name=tea_name,
                    room_id=clean_r, room_name=rom_name,
                    original_subject_id=o_clean_s, original_subject_name=orig_sub_name,
                    original_teacher_id=o_clean_t_c, original_teacher_name=orig_tea_name,
                    original_room_id=o_clean_r, original_room_name=orig_rom_name,
                    original_class_id=None, original_class_name=None,
                    original_group_id=o_clean_g, original_group_name=orig_grp_name,
                    group_id=safe_g_id, group_name=grp_name,
                    is_exchange=is_exchange, is_cancelled=is_cancelled, is_methodological=False
                ))
        return lessons

    def build_class_lessons(self, target_dates: List[datetime.date]) -> List[LessonInstance]:
        lessons = []
        for t_date in target_dates:
            iso_date, date_str, weekday = t_date.isoformat(), t_date.strftime("%d.%m.%Y"), t_date.isoweekday()
            period_id = self._get_active_period(t_date)
            if not period_id:
                # ИСПРАВЛЕНО P0: логирование вместо молчаливого пропуска
                logger.warning("No active NIKA period for date %s; skipping class schedule", t_date)
                continue
            
            for class_id in self.classes.keys():
                schedule_base = self.data.get("CLASS_SCHEDULE", {}).get(period_id, {}).get(class_id, {})
                exchanges = self.data.get("CLASS_EXCHANGE", {}).get(class_id, {}).get(date_str, {})
                
                for lesson_num in self._lesson_numbers_for_day(schedule_base, exchanges, weekday):
                    slot_base = schedule_base.get(f"{weekday}{lesson_num:02d}", {})
                    slot_exchange = exchanges.get(str(lesson_num), {})
                    if slot_base or slot_exchange:
                        lessons.extend(self._process_slot(
                            slot_base, slot_exchange, lesson_num, iso_date, weekday, period_id, class_id, False
                        ))
        return lessons


    def build_teacher_lessons(self, target_dates: List[datetime.date]) -> List[LessonInstance]:
        """
        Генерирует LessonInstance на основе TEACH_SCHEDULE и TEACH_EXCHANGE.
        
        Ключевые отличия от class_lessons:
        - Ключ 'c' (классы) вместо 't' (учителя)
        - Поддержка "M" (методический час/день)
        - Заполняется class_name (какой класс ведёт учитель)
        - groups_raw, subjects_raw, rooms_raw сохранены для агрегации
        """
        lessons = []
        for t_date in target_dates:
            iso_date, date_str, weekday = t_date.isoformat(), t_date.strftime("%d.%m.%Y"), t_date.isoweekday()
            period_id = self._get_active_period(t_date)
            if not period_id:
                # ИСПРАВЛЕНО P0: логирование вместо молчаливого пропуска
                logger.warning("No active NIKA period for date %s; skipping teacher schedule", t_date)
                continue
            
            for teacher_id in self.teachers.keys():
                schedule_base = self.data.get("TEACH_SCHEDULE", {}).get(period_id, {}).get(teacher_id, {})
                exchanges = self.data.get("TEACH_EXCHANGE", {}).get(teacher_id, {}).get(date_str, {})
                
                for lesson_num in self._lesson_numbers_for_day(schedule_base, exchanges, weekday):
                    slot_base = schedule_base.get(f"{weekday}{lesson_num:02d}", {})
                    slot_exchange = exchanges.get(str(lesson_num), {})
                    if slot_base or slot_exchange:
                        lessons.extend(self._process_slot(
                            slot_base, slot_exchange, lesson_num, iso_date, weekday, period_id, teacher_id, True
                        ))
        return lessons