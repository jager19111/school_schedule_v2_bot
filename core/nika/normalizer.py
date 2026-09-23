# core/nika/normalizer.py — ФИНАЛЬНАЯ ВЕРСИЯ v2
# (прогнана на nika_data_18/19.09.2026: юнит-тесты бомб 1-2 + 15/15 E2E PASS
#  вместе с патчем _lesson_to_row v3 в репозитории)

# ИСПРАВЛЕНИЯ P0:
# 1. Merge частичных exchange-слотов (предмет/учитель/кабинет/группа).
# 2. Пустой предмет → is_cancelled=True (по ТЗ).
# 3. Методический час = 1 запись, а не по числу групп.
# 4. Стабильные детерминированные lesson_id.
# 5. Логирование отсутствия активного периода.
# 6. Обработка отсутствующего LESSON_TIMES с логированием, а не исключением.
#
# ИСПРАВЛЕНИЯ P1:
# 7. Out-of-bounds Broadcasting: массивы длины >1 без g не схлопываются в один
#    «весь класс» — генерируются параллельные потоки (учитель с двумя классами
#    в слоте: c=["031","033"], класс — синтетические группы I0/I1).
# 8. Broadcast одиночных элементов: g=["0","1"] + s/t/r длины 1 → предмет
#    транслируется на ВСЕ группы, а не «ОТМЕНЕНО» для второй.
# 9. Полная отмена (F) проверяется ПЕРВЫМ; группы отмены — из g замены,
#    иначе из g базы, иначе весь класс.
# 10. При слиянии групп original_group_id обнуляется.
# 11. Отменённый урок подтягивает исходного учителя/кабинет из базы.
# 12. Поэлементная замена без g при совпадении длин с базовыми группами
#     сохраняет выравнивание.
#
# ИСПРАВЛЕНИЯ P2 (аудит «трёх бомб», 19.09.2026):
# 13. БОМБА 1 «Немая отмена»: полная отмена (F) у учителя с НЕСКОЛЬКИМИ
#     классами в слоте (c=["031","033"] и даже c=["035","036","037"] — такие
#     слоты реально есть в базе, 4 шт.) теперь порождает по отменённой
#     записи на КАЖДЫЙ класс. Раньше max_len=1 → второй класс молча
#     исчезал после DELETE/INSERT в репозитории («дыра» вместо «ОТМЕНЫ»).
#     Симметрично для class-режима: отмена параллельных потоков без групп.
# 14. БОМБА 2 «Дырявые группы»: g=["0",""] — пустой элемент массива групп
#     больше не превращает подгруппу в «Весь класс»: группа подтягивается
#     из базового расписания по тому же индексу. Заодно убран бродкаст
#     g длины 1 (устранял бы дубли lesson_id при g=1 + массивах длины 2).

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

    Поддерживает:
    - CLASS_SCHEDULE / CLASS_EXCHANGE (расписание классов)
    - TEACH_SCHEDULE / TEACH_EXCHANGE (расписание учителей)
    - Отмены ("F" — полная, "" / "F" внутри массива — по подгруппам)
    - Методические часы ("M") — всегда одна запись на слот
    - Замены с сохранением «было → стало», включая группы
    - Слияние групп (2 группы → общий урок) и обратное разделение
    - Параллельные потоки без массива g (несколько классов у учителя в слоте)
    - Полную отмену слотов с несколькими классами у учителя
    """

    def __init__(self, nika_data: Dict[str, Any]):
        self.data = nika_data
        self.classes, self.teachers, self.rooms, self.subjects = self.build_metadata()
        
        # Словарь автосокращений для групп (экономим место в UI)
        GROUP_CORRECTIONS = {
            "Группа 1": "гр. 1",
            "Группа 2": "гр. 2",
            "Группа 3": "гр. 3",
            "1 группа": "1 гр.",
            "2 группа": "2 гр."
        }
        
        # Перехватываем и форматируем названия групп
        raw_groups = self.data.get("CLASSGROUPS", {})
        self.class_groups: Dict[str, str] = {}
        for g_id, g_name in raw_groups.items():
            clean_name = str(g_name).strip()
            if clean_name in GROUP_CORRECTIONS:
                clean_name = GROUP_CORRECTIONS[clean_name]
            self.class_groups[g_id] = clean_name
            
        self.lesson_times: Dict[str, List[str]] = self.data.get("LESSON_TIMES", {})

    def _clean_val(self, val: Any) -> Optional[str]:
        """Очистка пустых строк без потери числового нуля."""
        if val is None or str(val).strip() == "":
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
        # Словарь автоисправлений для "опечаток" администрации
        SUBJECT_CORRECTIONS = {
            "Литературное чтениечтение": "Литературное чтение",
            "сложныезадачи ЕГЭ": "Сложные задачи ЕГЭ",
            "Ин.яз": "Англ. язык",
            "математика плюс": "Математика плюс",
            "финансовая грамотность": "Фин. грамотность",
            "Прогрммирование на Python": "Программирование на Python",
            "Основы 3Д модедирования": "Основы 3Д моделирования",
            "основы естественно-научных исследований": "Основы ест.-науч. исследований",
            "Алгоритмы решения экономических задач": "Алгоритмы решения эконом. задач",
            "Методы решения физических задач": "Методы решения физ. задач",
            "Основы финансовой грамотности": "Основы фин. грамотности"
        }

        subjects = {}
        for s_id, raw_name in self.data.get("SUBJECTS", {}).items():
            clean_name = str(raw_name).strip()
            # На лету заменяем кривое название на нормальное
            if clean_name in SUBJECT_CORRECTIONS:
                clean_name = SUBJECT_CORRECTIONS[clean_name]
            subjects[s_id] = Subject(id=s_id, name=clean_name)

        return classes, teachers, rooms, subjects

    def _get_active_period(self, target_date: datetime.date) -> str | None:
        """
        Поиск активного учебного периода.
        Если дата находится в будущем (дальше всех заведенных в NIKA периодов),
        экстраполируем на неё базовое расписание из последнего известного периода.
        """
        latest_period_id = None
        latest_end_date = datetime.date.min

        for p_id, p_data in self.data.get("PERIODS", {}).items():
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

        # 2. Предиктивная экстраполяция в будущее.
        # На даты из прошлого не экстраполируем, чтобы не портить историю.
        if latest_end_date != datetime.date.min and target_date > latest_end_date:
            return latest_period_id

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
            logger.warning("Missing or invalid LESSON_TIMES[%s]", lesson_num)
            return None
        return value[0].strip(), value[1].strip()

    @staticmethod
    def _is_valid_grouping(raw_g: list) -> bool:
        """
        Признак того, что слот реально разделён на подгруппы.
        Номинальные [""] и ["ALL"] группировкой не считаются.
        """
        cleaned = [str(g).strip() for g in raw_g]
        if not cleaned:
            return False
        if len(cleaned) == 1 and cleaned[0] in ("", "ALL"):
            return False
        return True

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
            if not val:
                return []
            return val if isinstance(val, list) else [val]

        def _get_val(arr: list, idx: int):
            """Доступ к элементу с бродкастом одиночных значений
            (семантика NIKA: массив длины 1 = «для всех»)."""
            if not arr:
                return None
            if idx < len(arr):
                return arr[idx]
            if len(arr) == 1:
                return arr[0]
            return None

        target_key = "c" if is_teacher_mode else "t"

        # ── 0. ПОЛНАЯ ОТМЕНА: проверяется ПЕРВОЙ, до любых решений о группах ──
        raw_s_from_exchange = _ensure_list(slot_exchange.get("s")) if slot_exchange else []
        is_full_cancel = (raw_s_from_exchange == ["F"])

        # ── 1. Умное слияние (Merge) текущих массивов ──
        if is_exchange and slot_exchange:
            raw_s = _ensure_list(slot_exchange.get("s")) if "s" in slot_exchange else _ensure_list(slot_base.get("s"))
            raw_t_or_c = _ensure_list(slot_exchange.get(target_key)) if target_key in slot_exchange else _ensure_list(slot_base.get(target_key))
            raw_r = _ensure_list(slot_exchange.get("r")) if "r" in slot_exchange else _ensure_list(slot_base.get("r"))
            old_g = _ensure_list(slot_base.get("g"))

            if "g" in slot_exchange:
                raw_g = _ensure_list(slot_exchange.get("g"))
            else:
                # ЖЕЛЕЗОБЕТОННАЯ ЗАЩИТА СЛИЯНИЯ ГРУПП:
                # g в замене нет — судим о структуре по длинам массивов замены.
                exch_lens = [
                    len(_ensure_list(slot_exchange.get(k)))
                    for k in ("s", target_key, "r")
                    if k in slot_exchange
                ]
                max_exch_len = max(exch_lens) if exch_lens else 0

                if max_exch_len == 1 and len(old_g) > 1:
                    # Замена сжала слот до одного урока → класс объединили,
                    # старые группы недействительны.
                    raw_g = []
                elif max_exch_len > 1 and len(old_g) == max_exch_len:
                    # Поэлементная замена без g: длины совпали с базовыми
                    # группами — сохраняем выравнивание по группам.
                    raw_g = old_g
                elif max_exch_len > 1:
                    # Параллельные потоки без групп (напр., несколько классов
                    # у учителя в одном слоте).
                    raw_g = []
                    if not is_teacher_mode:
                        logger.warning(
                            "Exchange slot without 'g' has %d parallel streams (class=%s, date=%s, lesson=%s)",
                            max_exch_len, context_id, iso_date, lesson_num,
                        )
                else:
                    raw_g = old_g
        else:
            active_slot = slot_base
            raw_s = _ensure_list(active_slot.get("s"))
            raw_t_or_c = _ensure_list(active_slot.get(target_key))
            raw_r = _ensure_list(active_slot.get("r"))
            raw_g = _ensure_list(active_slot.get("g"))

        # ── 2. Методический час: принадлежит учителю, а не группе → 1 запись ──
        if is_teacher_mode and raw_s and str(raw_s[0]).strip() == "M":
            is_methodological = True
            raw_s = ["M"]
            raw_t_or_c, raw_r, raw_g = [], [], []

        # ── 3. Оригинальное (было) состояние — всегда из базового расписания ──
        orig_s = _ensure_list(slot_base.get("s")) if slot_base else []
        orig_target_key = "c" if is_teacher_mode else "t"
        orig_t_or_c = _ensure_list(slot_base.get(orig_target_key)) if slot_base else []
        orig_r = _ensure_list(slot_base.get("r")) if slot_base else []
        orig_g = _ensure_list(slot_base.get("g")) if slot_base else []

        lesson_time = self._get_lesson_time(lesson_num)
        if lesson_time is None:
            return lessons

        start_time, end_time = lesson_time

        # ── 4. Определение структуры слота (после полной отмены!) ──
        has_grouping = self._is_valid_grouping(raw_g)
        max_stream_len = max(len(raw_s), len(raw_t_or_c), len(raw_r))

        if has_grouping or is_full_cancel:
            is_whole_class = False
            is_parallel_streams = False
        else:
            is_whole_class = max_stream_len <= 1
            is_parallel_streams = max_stream_len > 1

        cancel_streams = False
        if is_full_cancel:
            # Группы отмены: из g замены (если школа указала), иначе из базы.
            cancel_exch_g = _ensure_list(slot_exchange.get("g")) if slot_exchange else []
            if self._is_valid_grouping(cancel_exch_g):
                cancel_groups = [str(g).strip() for g in cancel_exch_g if str(g).strip()]
            elif self._is_valid_grouping(orig_g):
                cancel_groups = [str(g).strip() for g in orig_g if str(g).strip()]
            else:
                cancel_groups = []

            if is_teacher_mode:
                # БОМБА 1: учитель может вести НЕСКОЛЬКО классов в одном слоте
                # (c=["031","033"] и даже c=["035","036","037"]). Полная отмена
                # обязана породить по записи на каждый класс, иначе после
                # DELETE/INSERT в репозитории второй класс молча исчезнет.
                max_len = max(len(cancel_groups), len(raw_t_or_c), 1)
            else:
                # Класс без групп: отменяем каждый параллельный поток отдельно.
                max_len = len(cancel_groups) if cancel_groups else max(len(raw_t_or_c), len(raw_r), 1)

            # Полная отмена без групп по нескольким потокам/классам
            cancel_streams = is_full_cancel and not cancel_groups and max(len(raw_t_or_c), len(raw_r)) > 1
        elif is_methodological or is_whole_class:
            max_len = 1
        elif is_parallel_streams:
            max_len = max_stream_len
        else:
            max_len = max(len(raw_g), len(raw_s), len(raw_t_or_c), len(raw_r))

        if max_len == 0:
            return lessons

        # При слиянии групп у объединённого урока нет «одной» исходной группы
        groups_were_merged = (not has_grouping) and self._is_valid_grouping(orig_g) and not is_full_cancel

        for idx in range(max_len):
            current_raw_s = _get_val(raw_s, idx)
            clean_s_temp = self._clean_val(current_raw_s)
            
            o_clean_s = self._clean_val(_get_val(orig_s, idx))
            
            is_full_cancel_pointwise = (clean_s_temp is None or clean_s_temp == "F")

            # --- ИСПРАВЛЕНИЕ: Детектирование окон (NO_LESSONS) ---
            # Если предмет пустой, И в оригинальном расписании он тоже был пустой,
            # значит урока здесь никогда и не было. Это окно, а не отмена.
            if clean_s_temp is None and o_clean_s is None and not is_full_cancel:
                is_window = True
                is_cancelled = False
            else:
                is_window = False
                is_cancelled = is_full_cancel or is_full_cancel_pointwise
            # -----------------------------------------------------

            clean_s = clean_s_temp if not is_cancelled and not is_window else None
            clean_t_c = self._clean_val(_get_val(raw_t_or_c, idx))
            clean_r = self._clean_val(_get_val(raw_r, idx))

            # ── 5. Идентификатор группы ──
            if is_full_cancel:
                if idx < len(cancel_groups):
                    g_id = cancel_groups[idx]
                elif cancel_streams:
                    # Отмена нескольких классов/потоков: у учителя строки
                    # различаются классом, у класса — индексом потока.
                    g_id = "ALL" if is_teacher_mode else f"I{idx}"
                else:
                    g_id = "ALL"
            elif is_methodological or is_whole_class:
                g_id = "ALL"
            elif is_parallel_streams:
                g_id = "ALL" if is_teacher_mode else f"I{idx}"
            else:
                # БОМБА 2: защита от «дырявых» групп g=["0",""]: пустой элемент
                # не должен превращать подгруппу в «Весь класс» — подтягиваем
                # группу из базового расписания по тому же индексу.
                # (Бродкаст g не используем: g длины 1 при массивах длины 2
                # дал бы дубли lesson_id.)
                g_raw = raw_g[idx] if idx < len(raw_g) else None
                if g_raw is None or str(g_raw).strip() == "":
                    g_raw = orig_g[idx] if idx < len(orig_g) else None
                g_id = g_raw if (g_raw is not None and str(g_raw).strip() != "") else "ALL"

            clean_g = self._clean_val(g_id)

            o_clean_s = self._clean_val(_get_val(orig_s, idx))
            o_clean_t_c = self._clean_val(_get_val(orig_t_or_c, idx))
            o_clean_r = self._clean_val(_get_val(orig_r, idx))
            o_clean_g = self._clean_val(_get_val(orig_g, idx)) if not groups_were_merged else None

            if is_methodological:
                sub_name = "Методический час"
            elif is_window:
                sub_name = "нет занятий" # Маркер окна для БД
            else:
                sub_name = (
                    self.subjects.get(clean_s).name
                    if clean_s and clean_s in self.subjects
                    else ("ОТМЕНА" if is_cancelled else None)
                )

            if o_clean_s == "M":
                orig_sub_name = "Методический час"
            elif o_clean_s is None:
                # Если в оригинальном расписании было пусто, то это всегда было окном, 
                # независимо от того, пришла ли сейчас отмена "F" на весь слот.
                orig_sub_name = "нет занятий" 
            else:
                orig_sub_name = (
                    self.subjects.get(o_clean_s).name
                    if o_clean_s and o_clean_s in self.subjects
                    else None
                )

            rom_name = self.rooms.get(clean_r).name if clean_r and clean_r in self.rooms else None
            orig_rom_name = self.rooms.get(o_clean_r).name if o_clean_r and o_clean_r in self.rooms else None
            orig_grp_name = self.class_groups.get(o_clean_g) if o_clean_g and o_clean_g != "ALL" else None

            # ── 6. Амнезия при отмене: подтягиваем «было» из базы ──
            if is_cancelled:
                if not clean_t_c:
                    clean_t_c = o_clean_t_c
                if not clean_r:
                    clean_r = o_clean_r
                safe_g_id = o_clean_g if o_clean_g else "ALL"
                rom_name = self.rooms.get(clean_r).name if clean_r and clean_r in self.rooms else None
            else:
                safe_g_id = clean_g if clean_g and clean_g != "ALL" else "ALL"

            grp_name = self.class_groups.get(safe_g_id, "Весь класс") if safe_g_id != "ALL" else "Весь класс"
            if (is_parallel_streams or cancel_streams) and not is_teacher_mode and str(safe_g_id).startswith("I"):
                grp_name = f"Поток {idx + 1}"

            if is_teacher_mode:
                active_t_c = clean_t_c if clean_t_c else (o_clean_t_c if is_cancelled else None)

                effective_class_id = active_t_c if active_t_c else f"TEACHER_{context_id}"
                lesson_id = f"T{context_id}_{period_id}_{effective_class_id}_{iso_date}_{lesson_num}_{safe_g_id}"

                cls_name = self.classes.get(active_t_c).name if active_t_c and active_t_c in self.classes else None
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
        - Поддержка "M" (методический час/день) — одна запись на слот
        - Поддержка нескольких классов в одном слоте (c=["a","b"])
        - Заполняется class_name (какой класс ведёт учитель)
        """
        lessons = []
        for t_date in target_dates:
            iso_date, date_str, weekday = t_date.isoformat(), t_date.strftime("%d.%m.%Y"), t_date.isoweekday()
            period_id = self._get_active_period(t_date)
            if not period_id:
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
