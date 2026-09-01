from typing import List, Dict, Any, Tuple
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

    def build_class_lessons(self, target_dates: List[datetime.date]) -> List[LessonInstance]:
        """Генерирует LessonInstance на основе CLASS_SCHEDULE и CLASS_EXCHANGE для заданных дат[cite: 1, 2]."""
        lessons = []
        classes, teachers, rooms, subjects = self.build_metadata()
        class_groups = self.data.get("CLASSGROUPS", {})
        lesson_times = self.data.get("LESSON_TIMES", {})
        
        for t_date in target_dates:
            date_str = t_date.strftime("%d.%m.%Y")
            iso_date = t_date.isoformat()
            weekday = t_date.isoweekday()
            
            # Поиск активного периода (упрощенно: считаем, что первый подошедший период наш)
            # В реальных данных PERIODS = {"109": {"b": "01.09.2025", "e": "31.12.2025", "name": "1 полугодие"}}
            period_id = list(self.data.get("PERIODS", {}).keys())[0] 
            
            for class_id in classes.keys():
                schedule_base = self.data.get("CLASS_SCHEDULE", {}).get(period_id, {}).get(class_id, {})
                exchanges = self.data.get("CLASS_EXCHANGE", {}).get(class_id, {}).get(date_str, {})
                
                # Обрабатываем 1-10 уроки
                for lesson_num in range(1, 15):
                    daylesson_key = f"{weekday}{lesson_num:02d}"
                    l_str = str(lesson_num)
                    
                    slot_base = schedule_base.get(daylesson_key)
                    slot_exchange = exchanges.get(l_str)
                    
                    if not slot_base and not slot_exchange:
                        continue
                        
                    is_exchange = bool(slot_exchange)
                    active_slot = slot_exchange if is_exchange else slot_base
                    
                    # Безопасный доступ к массивам при заменах (защита от "F")[cite: 1, 8]
                    raw_s = active_slot.get("s", [])
                    raw_t = active_slot.get("t", [])
                    raw_r = active_slot.get("r", [])
                    raw_g = active_slot.get("g", [])
                    
                    # Проверка отмены ("F")[cite: 1, 3]
                    is_cancelled = False
                    if isinstance(raw_s, str) and raw_s == "F":
                        is_cancelled = True
                        raw_s, raw_t, raw_r, raw_g = [], [], [], []
                    elif isinstance(raw_s, list) and len(raw_s) > 0 and raw_s[0] == "F":
                        is_cancelled = True
                        raw_s, raw_t, raw_r, raw_g = [], [], [], []

                    start_time = lesson_times.get(l_str, ["00:00", "00:00"])[0]
                    end_time = lesson_times.get(l_str, ["00:00", "00:00"])[1]

                    # Если групп нет, создаем дефолтную для всего класса ("ALL")[cite: 1, 5]
                    if not raw_g:
                        raw_g = ["ALL"]

                    for idx, g_id in enumerate(raw_g):
                        clean_s = self._clean_val(raw_s[idx]) if idx < len(raw_s) else None
                        clean_t = self._clean_val(raw_t[idx]) if idx < len(raw_t) else None
                        clean_r = self._clean_val(raw_r[idx]) if idx < len(raw_r) else None
                        clean_g = self._clean_val(g_id)
                        
                        sub_name = subjects.get(clean_s).name if clean_s and clean_s in subjects else ("ОТМЕНА" if is_cancelled else None)
                        tea_name = teachers.get(clean_t).name if clean_t and clean_t in teachers else None
                        rom_name = rooms.get(clean_r).name if clean_r and clean_r in rooms else None
                        grp_name = class_groups.get(clean_g, "Весь класс") if clean_g != "ALL" else "Весь класс"

                        # Формирование детерминированного ID: period_class_date_lesson_group[cite: 1, 7]
                        safe_g_id = clean_g if clean_g else "ALL"
                        lesson_id = f"{period_id}_{class_id}_{iso_date}_{lesson_num}_{safe_g_id}"

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