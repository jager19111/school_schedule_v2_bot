#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Симуляция типичных ошибок парсера расписания учителей
Показывает, где именно может ломаться твоя логика
(Адаптировано для автоматической загрузки данных с сайта)
"""

import json
import re
import urllib.request
import ssl
from collections import defaultdict

BASE_URL = "https://lyceum.nstu.ru/rasp"
_CACHED_NIKA = None  # Глобальный кэш, чтобы не качать дамп 5 раз подряд

def load_nika():
    """Самостоятельно находит и скачивает свежий дамп расписания с сайта."""
    global _CACHED_NIKA
    if _CACHED_NIKA is not None:
        return _CACHED_NIKA
        
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) SchoolParser/Test'}

    print(f"🌐 Запрашиваем {BASE_URL}/schedule.html...")
    req = urllib.request.Request(f"{BASE_URL}/schedule.html", headers=headers)
    with urllib.request.urlopen(req, context=ctx) as response:
        html = response.read().decode('utf-8')

    match = re.search(r'src=["\']([^"\']*nika_data_[^"\']+\.js)["\']', html)
    if not match:
        raise ValueError("Не удалось найти ссылку на nika_data_*.js на странице!")
    
    js_filename = match.group(1).split('/')[-1]
    js_url = f"{BASE_URL}/{js_filename}"
    print(f"🔗 Найден свежий дамп: {js_filename}")
    
    print(f"📥 Скачиваем данные ({js_url})...")
    req_js = urllib.request.Request(js_url, headers=headers)
    with urllib.request.urlopen(req_js, context=ctx) as response:
        content = response.read().decode('utf-8')

    json_match = re.search(r'var\s+NIKA\s*=\s*(\{.*\});', content, re.DOTALL)
    if not json_match:
        raise ValueError("Не удалось извлечь JSON из скачанного файла!")
        
    _CACHED_NIKA = json.loads(json_match.group(1))
    return _CACHED_NIKA

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
    print("🔬 СИМУЛЯЦИЯ ТИПИЧНЫХ ОШИБОК ПАРСЕРА (ОНЛАЙН)")
    print("="*70)
    
    try:
        # Вызываем загрузку данных перед стартами сценариев
        # Это закеширует NIKA в _CACHED_NIKA
        load_nika()
        print("\n✅ Данные успешно загружены и закешированы. Начинаем тесты...\n")
        
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
        
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")

if __name__ == '__main__':
    main()