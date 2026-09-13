#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Минимальный рабочий пример парсера расписания учителей из NIKA
Этот код точно работает — используй как референс
"""

import json
import re
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

# === КОНФИГ ===
NIKA_FILE = 'nika_data_01092026_105439.txt'

def load_nika(filepath):
    """Загружает NIKA из JS-файла"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    match = re.search(r'var\s+NIKA\s*=\s*(\{.*\});', content, re.DOTALL)
    if not match:
        raise ValueError("Не удалось найти var NIKA = {...}")
    
    return json.loads(match.group(1))

def parse_lesson_key(lesson_key):
    """
    Разбирает lesson_key (например, "101", "207") в (day_of_week, lesson_num)
    """
    day = int(lesson_key[0])
    lesson_num = int(lesson_key[1:])
    return day, lesson_num

def get_teacher_week_schedule(nika, teacher_id=None):
    """
    Строит расписание учителей на неделю из CLASS_SCHEDULE
    
    Возвращает:
    {
        teacher_id: {
            'name': str,
            'lessons': [
                {
                    'day': int (1-7),
                    'lesson_num': int,
                    'subject': str,
                    'class': str,
                    'room': str,
                    'group': str or None
                }
            ]
        }
    }
    """
    teachers = nika.get('TEACHERS', {})
    classes = nika.get('CLASSES', {})
    subjects = nika.get('SUBJECTS', {})
    rooms = nika.get('ROOMS', {})
    class_schedule = nika.get('CLASS_SCHEDULE', {})
    
    # Результат
    result = {}
    
    # Инициализируем всех учителей
    for tid, tname in teachers.items():
        if teacher_id and tid != teacher_id:
            continue
        result[tid] = {
            'name': tname,
            'lessons': []
        }
    
    # Проходим по всем периодам
    for period_id, period_data in class_schedule.items():
        # Проходим по всем классам
        for class_id, lessons in period_data.items():
            class_name = classes.get(class_id, f"???{class_id}")
            
            # Проходим по всем урокам
            for lesson_key, lesson_data in lessons.items():
                day, lesson_num = parse_lesson_key(lesson_key)
                
                # Извлекаем данные
                subject_ids = lesson_data.get('s', [])
                teacher_ids = lesson_data.get('t', [])
                room_ids = lesson_data.get('r', [])
                group_ids = lesson_data.get('g', None)
                
                # Пропускаем уроки без учителей
                if not teacher_ids:
                    continue
                
                # Обрабатываем группы
                if group_ids and len(group_ids) > 1:
                    for idx, group_id in enumerate(group_ids):
                        if idx >= len(teacher_ids):
                            break
                        
                        tid = teacher_ids[idx]
                        if tid not in result:
                            continue
                        
                        subject_id = subject_ids[idx] if idx < len(subject_ids) else (subject_ids[0] if subject_ids else '???')
                        room_id = room_ids[idx] if idx < len(room_ids) else (room_ids[0] if room_ids else '???')
                        
                        lesson = {
                            'day': day,
                            'lesson_num': lesson_num,
                            'subject': subjects.get(subject_id, subject_id),
                            'class': class_name,
                            'room': rooms.get(room_id, room_id),
                            'group': group_id
                        }
                        result[tid]['lessons'].append(lesson)
                else:
                    # Обычный урок
                    for idx, tid in enumerate(teacher_ids):
                        if tid not in result:
                            continue
                        
                        subject_id = subject_ids[idx] if idx < len(subject_ids) else (subject_ids[0] if subject_ids else '???')
                        room_id = room_ids[idx] if idx < len(room_ids) else (room_ids[0] if room_ids else '???')
                        
                        lesson = {
                            'day': day,
                            'lesson_num': lesson_num,
                            'subject': subjects.get(subject_id, subject_id),
                            'class': class_name,
                            'room': rooms.get(room_id, room_id),
                            'group': None
                        }
                        result[tid]['lessons'].append(lesson)
    
    # Сортируем уроки по дню и номеру
    for tid in result:
        result[tid]['lessons'].sort(key=lambda x: (x['day'], x['lesson_num']))
    
    return result

def print_teacher_schedule(schedule, teachers):
    """Выводит расписание в читаемом формате"""
    
    day_names = ["", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    
    for tid, data in schedule.items():
        tname = data['name']
        lessons = data['lessons']
        
        if not lessons:
            continue
        
        print(f"\n{'='*70}")
        print(f"👨‍🏫 {tname} ({tid}) — {len(lessons)} уроков")
        print(f"{'='*70}")
        
        # Группируем по дням
        by_day = defaultdict(list)
        for lesson in lessons:
            by_day[lesson['day']].append(lesson)
        
        for day in sorted(by_day.keys()):
            day_lessons = by_day[day]
            print(f"\n{day_names[day]}:")
            
            for lesson in day_lessons:
                group_info = f" ({lesson['group']})" if lesson.get('group') else ""
                print(f"  {lesson['lesson_num']:2d}. {lesson['subject']:<30} | {lesson['class']:<6} | {lesson['room']}{group_info}")

def main():
    print("="*70)
    print("📚 МИНИМАЛЬНЫЙ РАБОЧИЙ ПАРСЕР РАСПИСАНИЯ УЧИТЕЛЕЙ")
    print("="*70)
    
    # Проверяем файл
    nika_path = Path(NIKA_FILE)
    if not nika_path.exists():
        print(f"\n❌ Файл {NIKA_FILE} не найден в {Path.cwd()}")
        return
    
    # Загружаем
    print(f"\n📥 Загрузка {NIKA_FILE}...")
    nika = load_nika(NIKA_FILE)
    print(f"✅ NIKA загружен")
    
    # Получаем расписание
    print("\n⚙️  Построение расписания...")
    teachers = nika.get('TEACHERS', {})
    schedule = get_teacher_week_schedule(nika)
    
    # Статистика
    teachers_with_lessons = sum(1 for t in schedule.values() if t['lessons'])
    total_lessons = sum(len(t['lessons']) for t in schedule.values())
    
    print(f"\n📊 Статистика:")
    print(f"   Всего учителей: {len(teachers)}")
    print(f"   Учителей с уроками: {teachers_with_lessons}")
    print(f"   Всего уроков: {total_lessons}")
    
    # Выводим расписание для первых 5 учителей
    print_teacher_schedule(
        {k: v for k, v in list(schedule.items())[:5]},
        teachers
    )
    
    # Пример: расписание конкретного учителя
    print("\n\n" + "="*70)
    print("🔍 ПРИМЕР: Расписание первого учителя с уроками")
    print("="*70)
    
    for tid, data in schedule.items():
        if data['lessons']:
            print(f"\n👨‍🏫 {data['name']} ({tid}):")
            for lesson in data['lessons'][:10]:  # первые 10 уроков
                day_names = ["", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
                group_info = f" (группа {lesson['group']})" if lesson.get('group') else ""
                print(f"  {day_names[lesson['day']]}, урок {lesson['lesson_num']:2d}: "
                      f"{lesson['subject']} в {lesson['class']} ({lesson['room']}){group_info}")
            break
    
    print("\n" + "="*70)
    print("✅ ГОТОВО")
    print("="*70)

if __name__ == '__main__':
    main()