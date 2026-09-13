#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Быстрая отладка: проверка структуры NIKA и извлечение расписания учителей
Запускать в той же директории, где лежит nika_data_*.txt
"""

import json
import re
from collections import defaultdict
from pathlib import Path

NIKA_FILE = 'nika_data_01092026_105439.txt'

def quick_debug():
    print("=" * 70)
    print("🔬 БЫСТРАЯ ОТЛАДКА NIKA - Расписание учителей")
    print("=" * 70)
    
    # 1. Проверяем файл
    nika_path = Path(NIKA_FILE)
    if not nika_path.exists():
        print(f"\n❌ Файл {NIKA_FILE} не найден в {Path.cwd()}")
        print("   Положите файл рядом со скриптом!")
        return
    
    print(f"\n✅ Файл найден: {NIKA_FILE}")
    
    # 2. Загружаем
    with open(nika_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    match = re.search(r'var\s+NIKA\s*=\s*(\{.*\});', content, re.DOTALL)
    if not match:
        print("❌ Не удалось извлечь JSON из var NIKA")
        return
    
    nika = json.loads(match.group(1))
    print(f"✅ JSON распарсен, размер: {len(match.group(1))} символов")
    
    # 3. Проверяем ключевые словари
    print("\n" + "=" * 70)
    print("📊 СТРУКТУРА NIKA")
    print("=" * 70)
    
    teachers = nika.get('TEACHERS', {})
    classes = nika.get('CLASSES', {})
    subjects = nika.get('SUBJECTS', {})
    rooms = nika.get('ROOMS', {})
    class_schedule = nika.get('CLASS_SCHEDULE', {})
    periods = nika.get('PERIODS', {})
    lesson_times = nika.get('LESSON_TIMES', {})
    
    print(f"TEACHERS: {len(teachers)} записей")
    print(f"CLASSES: {len(classes)} записей")
    print(f"SUBJECTS: {len(subjects)} записей")
    print(f"ROOMS: {len(rooms)} записей")
    print(f"PERIODS: {len(periods)} записей")
    print(f"LESSON_TIMES: {len(lesson_times)} записей")
    print(f"CLASS_SCHEDULE: {len(class_schedule)} периодов")
    
    # 4. Анализируем CLASS_SCHEDULE
    print("\n" + "=" * 70)
    print("📚 АНАЛИЗ CLASS_SCHEDULE")
    print("=" * 70)
    
    total_lessons = 0
    teacher_lessons = defaultdict(int)
    
    for period_id, period_data in class_schedule.items():
        print(f"\nПериод {period_id}:")
        print(f"  Классов: {len(period_data)}")
        
        for class_id, lessons in period_data.items():
            class_name = classes.get(class_id, f"???{class_id}")
            
            for lesson_key, lesson_data in lessons.items():
                total_lessons += 1
                
                teacher_ids = lesson_data.get('t', [])
                for tid in teacher_ids:
                    teacher_lessons[tid] += 1
    
    print(f"\nВсего уроков в расписании: {total_lessons}")
    print(f"Учителей с уроками: {len(teacher_lessons)}")
    
    # 5. Топ-10 самых загруженных учителей
    print("\n" + "=" * 70)
    print("🏆 ТОП-10 УЧИТЕЛЕЙ ПО КОЛИЧЕСТВУ УРОКОВ")
    print("=" * 70)
    
    sorted_teachers = sorted(teacher_lessons.items(), key=lambda x: x[1], reverse=True)[:10]
    for rank, (tid, count) in enumerate(sorted_teachers, 1):
        tname = teachers.get(tid, f"???{tid}")
        print(f"{rank}. {tname} ({tid}): {count} уроков")
    
    # 6. Проверяем конкретные lesson_key
    print("\n" + "=" * 70)
    print("🔍 ПРИМЕРЫ УРОКОВ")
    print("=" * 70)
    
    examples_shown = 0
    for period_id, period_data in list(class_schedule.items())[:1]:
        for class_id, lessons in list(period_data.items())[:3]:
            class_name = classes.get(class_id, f"???{class_id}")
            
            for lesson_key, lesson_data in list(lessons.items())[:5]:
                examples_shown += 1
                
                teacher_ids = lesson_data.get('t', [])
                subject_ids = lesson_data.get('s', [])
                room_ids = lesson_data.get('r', [])
                group_ids = lesson_data.get('g', None)
                
                teachers_str = ', '.join([teachers.get(t, t) for t in teacher_ids])
                subjects_str = ', '.join([subjects.get(s, s) for s in subject_ids])
                rooms_str = ', '.join([rooms.get(r, r) for r in room_ids])
                groups_str = ', '.join(group_ids) if group_ids else 'ALL'
                
                print(f"\n{class_name} | Урок {lesson_key}:")
                print(f"  👨‍🏫 Учителя: {teachers_str}")
                print(f"  📚 Предметы: {subjects_str}")
                print(f"  🚪 Кабинеты: {rooms_str}")
                print(f"  👥 Группы: {groups_str}")
                
                if examples_shown >= 10:
                    break
            if examples_shown >= 10:
                break
        if examples_shown >= 10:
            break
    
    # 7. Возможные проблемы
    print("\n" + "=" * 70)
    print("⚠️  ВОЗМОЖНЫЕ ПРОБЛЕМЫ")
    print("=" * 70)
    
    # Проверка на пустые teacher_ids
    empty_teachers = 0
    empty_subjects = 0
    empty_rooms = 0
    
    for period_id, period_data in class_schedule.items():
        for class_id, lessons in period_data.items():
            for lesson_key, lesson_data in lessons.items():
                if not lesson_data.get('t', []):
                    empty_teachers += 1
                if not lesson_data.get('s', []):
                    empty_subjects += 1
                if not lesson_data.get('r', []):
                    empty_rooms += 1
    
    print(f"Уроков без учителей: {empty_teachers}")
    print(f"Уроков без предметов: {empty_subjects}")
    print(f"Уроков без кабинетов: {empty_rooms}")
    
    # Проверка на несоответствие длин массивов
    mismatch_count = 0
    for period_id, period_data in class_schedule.items():
        for class_id, lessons in period_data.items():
            for lesson_key, lesson_data in lessons.items():
                t_len = len(lesson_data.get('t', []))
                s_len = len(lesson_data.get('s', []))
                r_len = len(lesson_data.get('r', []))
                g_len = len(lesson_data.get('g', [])) if lesson_data.get('g') else 0
                
                if g_len > 0 and not (t_len == g_len and s_len == g_len):
                    mismatch_count += 1
    
    print(f"Уроков с несоответствием длин массивов (при наличии групп): {mismatch_count}")
    
    print("\n" + "=" * 70)
    print("✅ ОТЛАДКА ЗАВЕРШЕНА")
    print("=" * 70)

if __name__ == '__main__':
    quick_debug()