"""Сборка PosterRequest из DayScheduleDTO и версионированные ключи кэша.

Ключи (ТЗ v2.2, раздел 3.3, с правками из обсуждения):
- глобальный (поиск по школе): 25 учеников класса = 1 рендер;
- персональный: принадлежит профилю РЕБЁНКА, а не смотрящему —
  мама, папа и сам ребёнок шарят один постер с доп. занятиями.

Версия расписания — semantic-хэш NIKA (см. services/image_render/version.py):
новая версия = новый ключ, инвалидация не нужна.
"""

from __future__ import annotations
import hashlib
from collections import defaultdict
from typing import Iterable

from core.models.dto import DayScheduleDTO, ExtraClassItemDTO
from services.image_render.models import (
    LessonStatus, PosterLessonCard, PosterRequest, PosterItem
)

def build_global_request_id(schedule_version: str | int, class_id: str, group_id: str, date_iso: str) -> str:
    return f"img_v{schedule_version}_{class_id}_{group_id or 'ALL'}_{date_iso}"

def build_personal_request_id(schedule_version: str | int, student_profile_id: int, date_iso: str, extra_hash: str) -> str:
    return f"imgp_v{schedule_version}_{student_profile_id}_{date_iso}_{extra_hash}"

def extra_classes_hash(items: Iterable[ExtraClassItemDTO]) -> str:
    payload = "|".join(f"{item.day_of_week}:{item.time_start}-{item.time_end}:{item.title}" for item in sorted(items, key=lambda i: (i.day_of_week, i.time_start or "", i.title or "")))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12] if payload else "noextra"

def build_poster_request(
    *, request_id: str, dto: DayScheduleDTO, title: str, date_text: str,
    subtitle: str | None = None, is_teacher: bool = False, width: int = 1080,
) -> PosterRequest:
    cards: list[PosterLessonCard] = []
    changes_count = 0
    
    # Смарт-агрегация: группируем уроки по времени
    grouped_lessons = defaultdict(list)
    for lesson in dto.lessons:
        key = (lesson.display_num or lesson.lesson_num, lesson.start_time, lesson.end_time)
        grouped_lessons[key].append(lesson)

    for key, group in grouped_lessons.items():
        first = group[0]
        
        # Определяем статус всей карточки
        # Определяем статус всей карточки
        is_all_cancelled = all(l.is_cancelled for l in group)
        has_changes = any(l.is_exchange or l.is_cancelled for l in group)

        if is_all_cancelled: status = LessonStatus.CANCELLED
        elif first.is_extra: status = LessonStatus.EXTRA
        elif has_changes: status = LessonStatus.EXCHANGE
        elif first.is_methodological: status = LessonStatus.METHODICAL
        else: status = LessonStatus.NORMAL

        num = "Доп." if first.is_extra else str(first.display_num or first.lesson_num or "•")
        items = []

        # ==========================================
        # ЛОГИКА УЧИТЕЛЯ
        # ==========================================
        if is_teacher:
            if first.is_methodological:
                items.append(PosterItem(primary_text="Методический час", secondary_text=None, room=None))
            else:
                # --- ИСПРАВЛЕНИЕ: Смарт-агрегация классов для Учителя ---
                teacher_subgroups = defaultdict(list)
                for l in group:
                    # Группируем по Предмету, Статусу отмены и Кабинету
                    subj = l.subject_name or l.original_subject_name or "Урок"
                    key = (subj, l.is_cancelled, l.room_name)
                    teacher_subgroups[key].append(l)

                for (subj, is_cancelled, room_name), sub_group in teacher_subgroups.items():
                    classes = []
                    groups = []
                    
                    for l in sub_group:
                        if l.class_name and l.class_name not in classes: 
                            classes.append(l.class_name)
                        gn = str(l.group_name).strip() if l.group_name else ""
                        if gn and gn not in ("Весь класс", "ALL", "None", "", "—") and gn not in groups:
                            groups.append(gn)
                            
                    meta_parts = []
                    if classes: 
                        meta_parts.append(", ".join(classes)) # Склеиваем классы через запятую
                    if groups: 
                        meta_parts.append(", ".join(groups))
                        
                    primary = " · ".join(meta_parts) if meta_parts else "Урок"
                    
                    # Для зачеркивания берем старый предмет из первого элемента подгруппы
                    orig_subj = sub_group[0].original_subject_name or subj
                    orig_primary = f"{primary} · {orig_subj}" if is_cancelled else None
                    sec = None if is_cancelled else subj

                    items.append(PosterItem(
                        primary_text=primary,
                        secondary_text=sec,
                        room=room_name if room_name != "—" else None,
                        is_cancelled=is_cancelled,
                        original_primary=orig_primary
                    ))
        # ==========================================
        # ЛОГИКА УЧЕНИКА / РОДИТЕЛЯ
        # ==========================================
        else:
            # Вычисляем реальные предметы в слоте, исключая окна и отмены
            real_subjs = set()
            for l in group:
                s_name = l.original_subject_name if l.is_cancelled and l.original_subject_name != "ОТМЕНА" else l.subject_name
                if s_name and s_name.lower() not in ("отмена", "нет занятий", ""):
                    real_subjs.add(s_name.lower())
            
            # Агрегируем Труд ТОЛЬКО если это ЕДИНСТВЕННЫЙ реальный предмет в слоте
            is_trud_only = len(group) > 1 and len(real_subjs) == 1 and any("труд" in s or "технологи" in s for s in real_subjs)

            if is_trud_only:
                # Агрегация Труда: оставляем только активные группы (дети идут к оставшимся учителям)
                active_trud = [l for l in group if not l.is_cancelled]
                trud_to_render = active_trud if active_trud else group

                for idx, l in enumerate(trud_to_render):
                    is_window = (l.subject_name == "нет занятий") or (l.is_cancelled and l.original_subject_name == "нет занятий")
                    items.append(PosterItem(
                        primary_text="нет занятий" if is_window else ("Труд (технология)" if idx == 0 else ""),
                        secondary_text=l.teacher_name if not is_window else None,
                        room=(l.room_name if l.room_name != "—" else None) if not is_window else None,
                        is_cancelled=l.is_cancelled and not is_window, # Окно не зачеркиваем
                        original_primary="Труд (технология)" if idx == 0 and l.is_cancelled and not is_window else None
                    ))
            else:
                for l in group:
                    # --- ОБРАБОТКА ОКОН И РАЗНЫХ ПРЕДМЕТОВ ---
                    is_window = (l.subject_name == "нет занятий") or (l.is_cancelled and l.original_subject_name == "нет занятий")
                    
                    if is_window:
                        items.append(PosterItem(
                            primary_text="нет занятий",
                            # Выводим номер группы, чтобы родитель точно знал, у кого окно
                            secondary_text=l.group_name if l.group_name and l.group_name not in ("ALL", "Весь класс", "—") else None,
                            room=None,
                            is_cancelled=False, # Снимаем отмену, чтобы не было красного зачеркивания
                            original_primary=None
                        ))
                    else:
                        subj = l.subject_name or l.original_subject_name or "Урок"
                        orig = l.original_subject_name if l.original_subject_name and l.original_subject_name != "ОТМЕНА" else subj

                        items.append(PosterItem(
                            primary_text=subj,
                            secondary_text=l.teacher_name, # Всегда выводим преподавателя
                            room=l.room_name if l.room_name != "—" else None,
                            is_cancelled=l.is_cancelled,
                            original_primary=orig if l.is_cancelled else None
                        ))

        cards.append(PosterLessonCard(
            num=num, time_start=first.start_time or "—", time_end=first.end_time or "—",
            status=status, items=tuple(items), is_extra=first.is_extra
        ))
        
        if status in (LessonStatus.EXCHANGE, LessonStatus.CANCELLED) and not first.is_extra:
            changes_count += 1

    # === НОВАЯ ЛОГИКА: Достраиваем сетку 1-12 для учителя ===
    if is_teacher and cards:
        teacher_cards_map = {}
        extra_cards = []
        for c in cards:
            if c.is_extra:
                extra_cards.append(c)
            else:
                try:
                    # Извлекаем чистое число урока
                    n = int(str(c.num).replace('*', ''))
                    teacher_cards_map[n] = c
                except ValueError:
                    extra_cards.append(c)
        
        full_cards = []
        # Если вдруг уроков больше 12 (вечерняя смена), сетка расширится
        max_num = max(teacher_cards_map.keys()) if teacher_cards_map else 12
        grid_end = max(12, max_num)
        
        for i in range(1, grid_end + 1):
            if i in teacher_cards_map:
                full_cards.append(teacher_cards_map[i])
            else:
                # Генерируем компактное "окно"
                full_cards.append(PosterLessonCard(
                    num=str(i),
                    time_start="—",
                    time_end="—",
                    status=LessonStatus.NORMAL,
                    items=(PosterItem(
                        primary_text="Окно", 
                        secondary_text=None, room=None, 
                        is_cancelled=False, original_primary=None
                    ),),
                    is_extra=False
                ))
        cards = full_cards + extra_cards
    # =========================================================

    return PosterRequest(
        request_id=request_id, date_text=date_text, title=title,
        lessons=tuple(cards), subtitle=subtitle, changes_count=changes_count, width=width,
    )