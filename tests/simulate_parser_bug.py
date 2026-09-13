#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Симуляция типичных ошибок парсера расписания учителей
Показывает, где именно может ломаться твоя логика
"""

import json
import re
from collections import defaultdict
from pathlib import Path

NIKA_FILE = 'nika_data_01092026_105439.txt'

def load_nika():
    with open(NIKA_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    match = re.search(r'var\s+NIKA\s*=\s*(\{.*\});', content, re.DOTALL)
    return json.loads(match.group(1)) if match else None

def test_scenario_1_wrong_key():
    """Сценарий 1: Ожидание TEACH_SCHEDULE вместо CLASS_SCHEDULE"""
    print("\n" + "="*70)
    print("❌ СЦЕНАРИЙ 1: Поиск несуществующего TEACH_SCHEDULE")
    print("="*70)
    
    nika = load_nika()
    
    # ❌ Типичная ошибка
    teach_schedule = nika.get('TEACH_SCHEDULE', {})
    print(f"TEACH_SCHEDULE найден: {bool(teach_schedule)}")
    print(f"Количество записей: {len(teach_schedule)}")
    
    if not teach_schedule:
        print("\n💡 Проблема: Ключ 'TEACH_SCHEDULE' не существует в NIKA!")
        print("   Решение: Использовать CLASS_SCHEDULE и группировать по teacher_id")
    
    # ✅ Правильно
    class_schedule = nika.get('CLASS_SCHEDULE', {})
    print(f"\n✅ CLASS_SCHEDULE найден: {bool(class_schedule)}")
    print(f"   Периодов: {len(class_schedule)}")

def test_scenario_2_empty_teacher_arrays():
    """Сценарий 2: Пустые массивы учителей"""
    print("\n" + "="*70)
    print("❌ СЦЕНАРИЙ 2: Уроки без учителей")
    print("="*70)
    
    nika = load_nika()
    class_schedule = nika.get('CLASS_SCHEDULE', {})
    
    empty_count = 0
    total_count = 0
    
    for period_id, period_data in class_schedule.items():
        for class_id, lessons in period_data.items():
            for lesson_key, lesson_data in lessons.items():
                total_count += 1
                teacher_ids = lesson_data.get('t', [])
                
                if not teacher_ids:
                    empty_count += 1
                    if empty_count <= 5:
                        print(f"\n⚠️  Урок без учителей:")
                        print(f"   Класс: {class_id}, Урок: {lesson_key}")
                        print(f"   Данные: {lesson_data}")
    
    print(f"\n📊 Статистика:")
    print(f"   Всего уроков: {total_count}")
    print(f"   Уроков без учителей: {empty_count} ({empty_count/total_count*100:.1f}%)")

def test_scenario_3_groups_handling():
    """Сценарий 3: Неправильная обработка групп"""
    print("\n" + "="*70)
    print("❌ СЦЕНАРИЙ 3: Уроки с группами (split lessons)")
    print("="*70)
    
    nika = load_nika()
    class_schedule = nika.get('CLASS_SCHEDULE', {})
    teachers = nika.get('TEACHERS', {})
    subjects = nika.get('SUBJECTS', {})
    
    group_lessons = 0
    
    for period_id, period_data in class_schedule.items():
        for class_id, lessons in period_data.items():
            for lesson_key, lesson_data in lessons.items():
                group_ids = lesson_data.get('g', None)
                
                if group_ids and len(group_ids) > 1:
                    group_lessons += 1
                    
                    if group_lessons <= 3:
                        print(f"\n👥 Урок с группами:")
                        print(f"   Класс: {class_id}, Урок: {lesson_key}")
                        print(f"   Группы: {group_ids}")
                        print(f"   Учителя: {lesson_data.get('t', [])}")
                        print(f"   Предметы: {lesson_data.get('s', [])}")
                        print(f"   Кабинеты: {lesson_data.get('r', [])}")
                        
                        # ❌ Неправильно: берём только первый элемент
                        print(f"\n   ❌ Если взять только [0]:")
                        print(f"      Учитель: {teachers.get(lesson_data['t'][0], '???')}")
                        print(f"      Предмет: {subjects.get(lesson_data['s'][0], '???')}")
                        
                        # ✅ Правильно: обрабатываем каждую группу
                        print(f"\n   ✅ Если обработать все группы:")
                        for idx, gid in enumerate(group_ids):
                            tid = lesson_data['t'][idx] if idx < len(lesson_data['t']) else lesson_data['t'][0]
                            sid = lesson_data['s'][idx] if idx < len(lesson_data['s']) else lesson_data['s'][0]
                            print(f"      Группа {gid}: Учитель={teachers.get(tid, '???')}, Предмет={subjects.get(sid, '???')}")
    
    print(f"\n📊 Найдено уроков с группами: {group_lessons}")

def test_scenario_4_lesson_key_parsing():
    """Сценарий 4: Неправильный парсинг lesson_key"""
    print("\n" + "="*70)
    print("❌ СЦЕНАРИЙ 4: Парсинг lesson_key")
    print("="*70)
    
    test_keys = ["101", "102", "207", "310", "411", "509", "605", "711"]
    
    print("\nФормат lesson_key: первая цифра=день, остальные=номер урока")
    print("-" * 70)
    print(f"{'lesson_key':<12} | {'❌ Ошибка':<25} | {'✅ Правильно':<25}")
    print("-" * 70)
    
    for key in test_keys:
        # ❌ Неправильно
        try:
            day_wrong = int(key) // 100
            lesson_wrong = int(key) % 100
            wrong_str = f"День={day_wrong}, Урок={lesson_wrong}"
        except:
            wrong_str = "ERROR"
        
        # ✅ Правильно
        day_correct = int(key[0])
        lesson_correct = int(key[1:])
        correct_str = f"День={day_correct}, Урок={lesson_correct}"
        
        print(f"{key:<12} | {wrong_str:<25} | {correct_str:<25}")

def test_scenario_5_period_selection():
    """Сценарий 5: Выбор неправильного периода"""
    print("\n" + "="*70)
    print("❌ СЦЕНАРИЙ 5: Выбор периода расписания")
    print("="*70)
    
    nika = load_nika()
    periods = nika.get('PERIODS', {})
    class_schedule = nika.get('CLASS_SCHEDULE', {})
    
    print(f"\n📅 Доступные периоды:")
    for pid, pdata in periods.items():
        print(f"   {pid}: {pdata.get('name', 'N/A')}")
    
    print(f"\n📚 Периоды в CLASS_SCHEDULE:")
    for pid in class_schedule.keys():
        lessons_count = sum(len(lessons) for lessons in class_schedule[pid].values())
        print(f"   {pid}: {len(class_schedule[pid])} классов, {lessons_count} уроков")
    
    # ❌ Ошибка: берём первый попавшийся период
    first_period = list(class_schedule.keys())[0]
    print(f"\n❌ Первый период: {first_period}")
    
    # ✅ Правильно: проверяем PERIODS и выбираем активный
    from datetime import datetime
    today = datetime.now()
    print(f"\n✅ Сегодня: {today.strftime('%d.%m.%Y')}")
    
    for pid, pdata in periods.items():
        if 'b' in pdata and 'e' in pdata:
            from datetime import datetime
            start = datetime.strptime(pdata['b'], '%d.%m.%Y')
            end = datetime.strptime(pdata['e'], '%d.%m.%Y')
            is_active = start <= today <= end
            print(f"   {pid}: {pdata['b']} - {pdata['e']} | Активен: {is_active}")

def main():
    print("="*70)
    print("🔬 СИМУЛЯЦИЯ ТИПИЧНЫХ ОШИБОК ПАРСЕРА")
    print("="*70)
    
    if not Path(NIKA_FILE).exists():
        print(f"\n❌ Файл {NIKA_FILE} не найден!")
        return
    
    test_scenario_1_wrong_key()
    test_scenario_2_empty_teacher_arrays()
    test_scenario_3_groups_handling()
    test_scenario_4_lesson_key_parsing()
    test_scenario_5_period_selection()
    
    print("\n" + "="*70)
    print("✅ СИМУЛЯЦИЯ ЗАВЕРШЕНА")
    print("="*70)
    print("\n📋 Следующие шаги:")
    print("   1. Запусти debug_nika_teachers.py для общей диагностики")
    print("   2. Запусти test_teacher_schedule.py для построения расписания")
    print("   3. Сравни вывод с тем, что ожидает твой парсер")
    print("   4. Проверь PARSER_CHECKLIST.md")

if __name__ == '__main__':
    main()