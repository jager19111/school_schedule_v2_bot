from typing import List, Dict, Any, Tuple, Optional
import datetime
import re
from core.models.domain import Class, Teacher, Room, Subject, Period, LessonInstance

class NikaNormalizer:
    def __init__(self, nika_data: Dict[str, Any]):
        self.data = nika_data
        
    def _clean_val(self, val: Any) -> Optional[str]:
        """Очистка пустых строк в массивах NIKA[cite: 1, 3]."""
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
        """Генерирует LessonInstance на основе CLASS_SCHEDULE и CLASS_EXCHANGE для заданных дат[cite: 2]."""
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

                    # Безопасный доступ к массивам при заменах (защита от "F")[cite: 11]
                    raw_s = _ensure_list(active_slot.get("s"))
                    raw_t = _ensure_list(active_slot.get("t"))
                    raw_r = _ensure_list(active_slot.get("r"))
                    raw_g = _ensure_list(active_slot.get("g"))
                    
                    # Проверка отмены ("F")[cite: 11]
                    is_cancelled = False
                    if raw_s and raw_s[0] == "F":
                        is_cancelled = True
                        raw_s, raw_t, raw_r, raw_g = [], [], [], []

                    start_time = lesson_times.get(l_str, ["00:00", "00:00"])[0]
                    end_time = lesson_times.get(l_str, ["00:00", "00:00"])[1]

                    # Определяем максимальную длину массивов, чтобы не потерять параллельные уроки
                    max_len = max(len(raw_s), len(raw_t), len(raw_r), len(raw_g))
                    
                    if max_len == 0 and not is_cancelled:
                        continue
                    elif max_len == 0 and is_cancelled:
                        max_len = 1  # Для отменённого урока нужна 1 итерация создания

                    for idx in range(max_len):
                        clean_s = self._clean_val(raw_s[idx]) if idx < len(raw_s) else None
                        clean_t = self._clean_val(raw_t[idx]) if idx < len(raw_t) else None
                        clean_r = self._clean_val(raw_r[idx]) if idx < len(raw_r) else None
                        
                        g_id = raw_g[idx] if idx < len(raw_g) else "ALL"
                        clean_g = self._clean_val(g_id)
                        
                        sub_name = subjects.get(clean_s).name if clean_s and clean_s in subjects else ("ОТМЕНА" if is_cancelled else None)
                        tea_name = teachers.get(clean_t).name if clean_t and clean_t in teachers else None
                        rom_name = rooms.get(clean_r).name if clean_r and clean_r in rooms else None
                        
                        safe_g_id = clean_g if clean_g and clean_g != "ALL" else "ALL"
                        grp_name = class_groups.get(safe_g_id, "Весь класс") if safe_g_id != "ALL" else "Весь класс"

                        # Формирование детерминированного ID с учетом индекса для параллельных уроков[cite: 11]
                        lesson_id = f"{period_id}_{class_id}_{iso_date}_{lesson_num}_{safe_g_id}_{idx}"

                        lessons.append(LessonInstance(
                            id=lesson_id,
                            period_id=period_id,
                            class_id=class_id,
                            date=iso_date,
                            weekday=weekday,
                            lesson_num=lesson_num,
                            start_time=start_time,
                            end_time=end_time,
                            subject_id=clean_s, subject_name=sub_name,
                            teacher_id=clean_t, teacher_name=tea_name,
                            room_id=clean_r, room_name=rom_name,
                            group_id=safe_g_id, group_name=grp_name,
                            is_exchange=is_exchange,
                            is_cancelled=is_cancelled,
                            groups_raw=raw_g, subjects_raw=raw_s, rooms_raw=raw_r
                        ))
        return lessons
    
