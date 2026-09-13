# bot/core/normalizers/normalizer.py
from typing import List, Dict, Any, Tuple, Optional
import datetime
import re
from core.models.domain import Class, Teacher, Room, Subject, Period, LessonInstance


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
        
    def _clean_val(self, val: Any) -> Optional[str]:
        """Очистка пустых строк в массивах NIKA."""
        if not val or str(val).strip() == "":
            return None
        return str(val).strip()


    def build_metadata(self) -> Tuple[Dict[str, Class], Dict[str, Teacher], Dict[str, Room], Dict[str, Subject]]:
        """Построение справочников из метаданных NIKA."""
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


    def _get_active_period(self, target_date: datetime.date, periods: dict) -> str | None:
        """Поиск активного учебного периода для заданной даты."""
        for p_id, p_data in periods.items():
            try:
                # В NIKA даты в формате "DD.MM.YYYY"
                b_date = datetime.datetime.strptime(p_data["b"], "%d.%m.%Y").date()
                e_date = datetime.datetime.strptime(p_data["e"], "%d.%m.%Y").date()
                if b_date <= target_date <= e_date:
                    return p_id
            except (ValueError, KeyError):
                continue
        
        # Если период не найден (например, каникулы), отдаем первый доступный как fallback
        return list(periods.keys())[0] if periods else None
    

    def build_class_lessons(self, target_dates: List[datetime.date]) -> List[LessonInstance]:
        """
        Генерирует LessonInstance на основе CLASS_SCHEDULE и CLASS_EXCHANGE для заданных дат.
        
        Заполняет:
        - class_name (имя класса)
        - original_* (было → стало)
        - original_group_* (если группа изменилась при замене)
        - groups_raw, subjects_raw, rooms_raw (для агрегации в рендерере)
        """
        lessons = []
        classes, teachers, rooms, subjects = self.build_metadata()
        class_groups = self.data.get("CLASSGROUPS", {})
        lesson_times = self.data.get("LESSON_TIMES", {})
        periods = self.data.get("PERIODS", {})
        
        for t_date in target_dates:
            date_str = t_date.strftime("%d.%m.%Y")
            iso_date = t_date.isoformat()
            weekday = t_date.isoweekday()
            
            # Поиск активного периода по дате
            period_id = self._get_active_period(t_date, periods)
            if not period_id:
                continue
            
            for class_id in classes.keys():
                cls_name = classes[class_id].name  # ← ДОБАВЛЕНО: имя класса
                schedule_base = self.data.get("CLASS_SCHEDULE", {}).get(period_id, {}).get(class_id, {})
                exchanges = self.data.get("CLASS_EXCHANGE", {}).get(class_id, {}).get(date_str, {})
                
                # Обрабатываем 1-14 уроки
                for lesson_num in range(1, 15):
                    daylesson_key = f"{weekday}{lesson_num:02d}"
                    l_str = str(lesson_num)
                    
                    slot_base = schedule_base.get(daylesson_key)
                    slot_exchange = exchanges.get(l_str)
                    
                    if not slot_base and not slot_exchange:
                        continue
                        
                    is_exchange = bool(slot_exchange)
                    active_slot = slot_exchange if is_exchange else slot_base
                    
                    # Вспомогательная функция для приведения значений к списку
                    def _ensure_list(val):
                        if not val: return []
                        return val if isinstance(val, list) else [val]


                    # 1. Извлекаем АКТИВНЫЕ массивы
                    raw_s = _ensure_list(active_slot.get("s"))
                    raw_t = _ensure_list(active_slot.get("t"))
                    raw_r = _ensure_list(active_slot.get("r"))
                    raw_g = _ensure_list(active_slot.get("g"))
                    
                    # 2. Извлекаем ОРИГИНАЛЬНЫЕ массивы (что было ДО замены/отмены)
                    orig_s = _ensure_list(slot_base.get("s")) if slot_base else []
                    orig_t = _ensure_list(slot_base.get("t")) if slot_base else []
                    orig_r = _ensure_list(slot_base.get("r")) if slot_base else []
                    orig_g = _ensure_list(slot_base.get("g")) if slot_base else []
                    
                    is_cancelled = False
                    if raw_s and raw_s[0] == "F":
                        is_cancelled = True
                        raw_s, raw_t, raw_r, raw_g = [], [], [], []


                    start_time = lesson_times.get(l_str, ["00:00", "00:00"])[0]
                    end_time = lesson_times.get(l_str, ["00:00", "00:00"])[1]


                    # Если урок отменен, цикл должен опираться на оригинальное количество групп!
                    if is_cancelled:
                        max_len = max(1, len(orig_s), len(orig_g))
                    else:
                        max_len = max(len(raw_s), len(raw_t), len(raw_r), len(raw_g))
                        
                    if max_len == 0:
                        continue


                    for idx in range(max_len):
                        # Текущие данные
                        clean_s = self._clean_val(raw_s[idx]) if idx < len(raw_s) else None
                        clean_t = self._clean_val(raw_t[idx]) if idx < len(raw_t) else None
                        clean_r = self._clean_val(raw_r[idx]) if idx < len(raw_r) else None
                        clean_g = self._clean_val(raw_g[idx] if idx < len(raw_g) else "ALL")
                        
                        # Оригинальные данные
                        o_clean_s = self._clean_val(orig_s[idx]) if idx < len(orig_s) else None
                        o_clean_t = self._clean_val(orig_t[idx]) if idx < len(orig_t) else None
                        o_clean_r = self._clean_val(orig_r[idx]) if idx < len(orig_r) else None
                        o_clean_g = self._clean_val(orig_g[idx]) if idx < len(orig_g) else None
                        
                        # Маппинг названий
                        sub_name = subjects.get(clean_s).name if clean_s and clean_s in subjects else ("ОТМЕНА" if is_cancelled else None)
                        tea_name = teachers.get(clean_t).name if clean_t and clean_t in teachers else None
                        rom_name = rooms.get(clean_r).name if clean_r and clean_r in rooms else None
                        
                        orig_sub_name = subjects.get(o_clean_s).name if o_clean_s and o_clean_s in subjects else None
                        orig_tea_name = teachers.get(o_clean_t).name if o_clean_t and o_clean_t in teachers else None
                        orig_rom_name = rooms.get(o_clean_r).name if o_clean_r and o_clean_r in rooms else None
                        
                        # Оригинальная группа (если изменилась)
                        orig_grp_name = class_groups.get(o_clean_g) if o_clean_g and o_clean_g != "ALL" else None


                        safe_g_id = clean_g if clean_g and clean_g != "ALL" else "ALL"
                        grp_name = class_groups.get(safe_g_id, "Весь класс") if safe_g_id != "ALL" else "Весь класс"

                        # Формирование детерминированного ID с учетом индекса для параллельных уроков[cite: 11]
                        lesson_id = f"{period_id}_{class_id}_{iso_date}_{lesson_num}_{safe_g_id}_{idx}"


                        lessons.append(LessonInstance(
                            id=lesson_id, 
                            period_id=period_id, 
                            class_id=class_id, 
                            class_name=cls_name,  # ← ДОБАВЛЕНО
                            date=iso_date,
                            weekday=weekday, 
                            lesson_num=lesson_num, 
                            start_time=start_time, 
                            end_time=end_time,
                            subject_id=clean_s, 
                            subject_name=sub_name, 
                            teacher_id=clean_t, 
                            teacher_name=tea_name,
                            room_id=clean_r, 
                            room_name=rom_name,
                            original_subject_id=o_clean_s, 
                            original_subject_name=orig_sub_name,
                            original_teacher_id=o_clean_t, 
                            original_teacher_name=orig_tea_name,
                            original_room_id=o_clean_r, 
                            original_room_name=orig_rom_name,
                            original_class_id=None,  # для классов не применимо
                            original_class_name=None,
                            original_group_id=o_clean_g,  # ← ДОБАВЛЕНО
                            original_group_name=orig_grp_name,  # ← ДОБАВЛЕНО
                            group_id=safe_g_id, 
                            group_name=grp_name,
                            is_exchange=is_exchange, 
                            is_cancelled=is_cancelled,
                            is_methodological=False,
                            groups_raw=raw_g,  # ← сохранено
                            subjects_raw=raw_s,  # ← сохранено
                            rooms_raw=raw_r  # ← сохранено
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
        classes, teachers, rooms, subjects = self.build_metadata()
        class_groups = self.data.get("CLASSGROUPS", {})
        lesson_times = self.data.get("LESSON_TIMES", {})
        periods = self.data.get("PERIODS", {})
        
        for t_date in target_dates:
            date_str = t_date.strftime("%d.%m.%Y")
            iso_date = t_date.isoformat()
            weekday = t_date.isoweekday()
            
            period_id = self._get_active_period(t_date, periods)
            if not period_id:
                continue
            
            for teacher_id, teacher_obj in teachers.items():
                schedule_base = self.data.get("TEACH_SCHEDULE", {}).get(period_id, {}).get(teacher_id, {})
                exchanges = self.data.get("TEACH_EXCHANGE", {}).get(teacher_id, {}).get(date_str, {})
                
                for lesson_num in range(1, 15):
                    daylesson_key = f"{weekday}{lesson_num:02d}"
                    l_str = str(lesson_num)
                    
                    slot_base = schedule_base.get(daylesson_key)
                    slot_exchange = exchanges.get(l_str)
                    
                    if not slot_base and not slot_exchange:
                        continue
                            
                    is_exchange = bool(slot_exchange)
                    active_slot = slot_exchange if is_exchange else slot_base
                    
                    def _ensure_list(val):
                        if not val: return []
                        return val if isinstance(val, list) else [val]


                    # 1. Извлекаем АКТИВНЫЕ массивы. У учителей ключ 'c' (классы) вместо 't'
                    raw_s = _ensure_list(active_slot.get("s"))
                    raw_c = _ensure_list(active_slot.get("c"))
                    raw_r = _ensure_list(active_slot.get("r"))
                    raw_g = _ensure_list(active_slot.get("g"))
                    
                    # 2. ОРИГИНАЛЬНЫЕ массивы (базовое расписание)
                    orig_s = _ensure_list(slot_base.get("s")) if slot_base else []
                    orig_c = _ensure_list(slot_base.get("c")) if slot_base else []
                    orig_r = _ensure_list(slot_base.get("r")) if slot_base else []
                    orig_g = _ensure_list(slot_base.get("g")) if slot_base else []
                    
                    is_cancelled = False
                    is_methodological = False
                    
                    # Обработка отмен и методических часов
                    if raw_s and raw_s[0] == "F":
                        is_cancelled = True
                        raw_s, raw_c, raw_r, raw_g = [], [], [], []
                    elif raw_s and raw_s[0] == "M":
                        is_methodological = True
                        raw_s = ["M"]  # Фиктивный ID для итерации
                        raw_c, raw_r, raw_g = [], [], []


                    start_time = lesson_times.get(l_str, ["00:00", "00:00"])[0]
                    end_time = lesson_times.get(l_str, ["00:00", "00:00"])[1]


                    if is_cancelled:
                        max_len = max(1, len(orig_s), len(orig_c), len(orig_g))
                    else:
                        max_len = max(len(raw_s), len(raw_c), len(raw_r), len(raw_g))
                        
                    if max_len == 0:
                        continue


                    for idx in range(max_len):
                        clean_s = self._clean_val(raw_s[idx]) if idx < len(raw_s) else None
                        clean_c = self._clean_val(raw_c[idx]) if idx < len(raw_c) else None
                        clean_r = self._clean_val(raw_r[idx]) if idx < len(raw_r) else None
                        clean_g = self._clean_val(raw_g[idx] if idx < len(raw_g) else "ALL")
                        
                        o_clean_s = self._clean_val(orig_s[idx]) if idx < len(orig_s) else None
                        o_clean_c = self._clean_val(orig_c[idx]) if idx < len(orig_c) else None
                        o_clean_r = self._clean_val(orig_r[idx]) if idx < len(orig_r) else None
                        o_clean_g = self._clean_val(orig_g[idx]) if idx < len(orig_g) else None
                        
                        if is_methodological:
                            sub_name = "Методический час/день"
                        else:
                            sub_name = subjects.get(clean_s).name if clean_s and clean_s in subjects else ("ОТМЕНА" if is_cancelled else None)
                        
                        orig_sub_name = subjects.get(o_clean_s).name if o_clean_s and o_clean_s in subjects else None
                        tea_name = getattr(teacher_obj, 'name', None)
                        
                        rom_name = rooms.get(clean_r).name if clean_r and clean_r in rooms else None
                        orig_rom_name = rooms.get(o_clean_r).name if o_clean_r and o_clean_r in rooms else None
                        
                        cls_name = classes.get(clean_c).name if clean_c and clean_c in classes else None
                        orig_cls_name = classes.get(o_clean_c).name if o_clean_c and o_clean_c in classes else None
                        
                        # Оригинальная группа
                        orig_grp_name = class_groups.get(o_clean_g) if o_clean_g and o_clean_g != "ALL" else None


                        safe_g_id = clean_g if clean_g and clean_g != "ALL" else "ALL"
                        grp_name = class_groups.get(safe_g_id, "Весь класс") if safe_g_id != "ALL" else "Весь класс"


                        # Детерминированный ID: если класса нет (метод. день), используем маркер TEACHER_[id]
                        effective_class_id = clean_c if clean_c else f"TEACHER_{teacher_id}"
                        lesson_id = f"T{teacher_id}_{period_id}_{effective_class_id}_{iso_date}_{lesson_num}_{safe_g_id}_{idx}"

                        # Поля Teacher в массивах raw_c, raw_s, raw_r сохраняются как fallback
                        lessons.append(LessonInstance(
                            id=lesson_id, 
                            period_id=period_id, 
                            class_id=effective_class_id, 
                            class_name=cls_name,
                            date=iso_date, 
                            weekday=weekday, 
                            lesson_num=lesson_num, 
                            start_time=start_time, 
                            end_time=end_time,
                            subject_id=clean_s, 
                            subject_name=sub_name, 
                            teacher_id=teacher_id, 
                            teacher_name=tea_name,
                            room_id=clean_r, 
                            room_name=rom_name,
                            original_subject_id=o_clean_s, 
                            original_subject_name=orig_sub_name,
                            original_teacher_id=None,  # для учителей не применимо (это сам учитель)
                            original_teacher_name=None,
                            original_room_id=o_clean_r, 
                            original_room_name=orig_rom_name,
                            original_class_id=o_clean_c,  # ← оригинальный класс
                            original_class_name=orig_cls_name,  # ← оригинальный класс (имя)
                            original_group_id=o_clean_g,  # ← ДОБАВЛЕНО
                            original_group_name=orig_grp_name,  # ← ДОБАВЛЕНО
                            group_id=safe_g_id, 
                            group_name=grp_name,
                            is_exchange=is_exchange, 
                            is_cancelled=is_cancelled,
                            is_methodological=is_methodological,
                            groups_raw=raw_g,  # ← ДОБАВЛЕНО (ранее отсутствовало!)
                            subjects_raw=raw_s,  # ← ДОБАВЛЕНО (ранее отсутствовало!)
                            rooms_raw=raw_r  # ← ДОБАВЛЕНО (ранее отсутствовало!)
                        ))
        return lessons