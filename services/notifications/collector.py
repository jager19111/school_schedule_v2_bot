# services/notification/collector.py

import datetime
import logging
import re
from collections import defaultdict

from bot.utils.ui_renderer import UIRenderer

from core.repository.notification_repository import NotificationRepository
from core.repository.schedule_repository import ScheduleRepository
from services.extra_classes_service import ExtraClassesService
from services.schedule_service import ScheduleService
from services.time_service import TimeService

from core.models.dto import (
    NotificationSendDTO,
    MorningSummaryTaskDTO,
    MorningSummaryDTO,
    MorningLessonDTO,
    LessonReminderDTO,
    ChangeReminderDTO,
    DailyChangeSummaryDTO,
    PendingChangeDTO,
    ScheduleChangeRecipientDTO,
    TeacherChangeRecipientDTO,
    DeliveredKeyDTO, PreLessonRecipientDTO
)
from core.mappers.notification_mapper import NotificationMapper
from .context import NotificationTickContext

logger = logging.getLogger(__name__)
MAX_CHANGES_WINDOW_DAYS = 31


class DailyChangesAggregator:
    """Хелпер для агрегации подготовленных DTO."""

    @staticmethod
    def aggregate_student_changes(student_records: list) -> list['NotificationSendDTO']:
        from collections import defaultdict
        groups = defaultdict(list)
        
        # ДОБАВЛЕН class_id в распаковку и ключ словаря
        for rec_id, date, rec, class_id, dto, source_ids in student_records:
            groups[(rec_id, date, rec, class_id)].append((dto, source_ids))

        candidates = []
        for (rec_id, date, rec, class_id), items in groups.items():
            dtos = [item[0] for item in items]
            all_source_ids = [s for item in items for s in item[1]]
                
            summary = DailyChangeSummaryDTO(
                date=date, recipient_kind=rec.recipient_kind, changes=dtos,
                child_name=rec.child_name, watch_target_title=rec.watch_target_title
            )
            
            try:
                text = UIRenderer.render_daily_changes_summary(summary)
            except Exception as e:
                logger.error("Render error for aggregated schedule changes: %s", e)
                continue

            candidates.append(NotificationSendDTO(
                notification_type="schedule_change", notification_date=date,
                source_ids=list(set(all_source_ids)), recipient_id=rec_id, text=text,
                context=f"aggregated_changes={len(dtos)}"
            ))
        return candidates

    @staticmethod
    def aggregate_teacher_changes(teacher_records: list) -> list['NotificationSendDTO']:
        from collections import defaultdict
        groups = defaultdict(list)
        
        # ДОБАВЛЕН teacher_id в распаковку и ключ словаря
        for rec_id, date, rec, teacher_id, dto, teacher_name, source_ids in teacher_records:
            groups[(rec_id, date, rec, teacher_id, teacher_name)].append((dto, source_ids))

        candidates = []
        for (rec_id, date, rec, teacher_id, teacher_name), items in groups.items():
            dtos = [item[0] for item in items]
            all_source_ids = [s for item in items for s in item[1]]

            summary = DailyChangeSummaryDTO(
                date=date, recipient_kind="teacher", changes=dtos, teacher_name=teacher_name
            )
            
            try:
                text = UIRenderer.render_daily_changes_summary(summary)
            except Exception as e:
                logger.error("Render error for aggregated teacher changes: %s", e)
                continue

            candidates.append(NotificationSendDTO(
                notification_type="teacher_change", notification_date=date,
                source_ids=list(set(all_source_ids)), recipient_id=rec_id, text=text,
                context=f"aggregated_changes={len(dtos)}"
            ))
        return candidates
    
class NotificationCollector:
    """Сборщик кандидатов. Превращает данные базы в готовые NotificationSendDTO."""

    def __init__(
        self, notification_repo: NotificationRepository, time_service: TimeService,
        schedule_repo: ScheduleRepository, extra_classes_service: ExtraClassesService,
        schedule_service: ScheduleService,
    ) -> None:
        self.repo = notification_repo
        self.time_service = time_service
        self.schedule_repo = schedule_repo
        self.extra_classes_service = extra_classes_service
        self.schedule_service = schedule_service

    async def _get_metadata(self, ctx: NotificationTickContext):
        """Ленивая загрузка справочников: 1 запрос к БД на весь тик рассылки."""
        if ctx.metadata_cache is None:
            ctx.metadata_cache = await self.schedule_repo.get_metadata()
            ctx.queries += 1  # Считаем только реальный запрос!
        return ctx.metadata_cache
    
    async def collect_morning_summaries(self, ctx: NotificationTickContext) -> list[NotificationSendDTO]:
        now = self.time_service.get_now_base()
        current_time_str = now.strftime("%H:%M")
        today_iso = now.date().isoformat()
        weekday = now.isoweekday()

        try:
            tasks = await self.repo.get_morning_summary_tasks(time_str=current_time_str)
            ctx.queries += 1
        except Exception as e:
            logger.exception("Infrastructure error: Failed to fetch morning summary tasks: %s", e)
            return []

        if not tasks: return []
        ctx.processed_entities += len(tasks)

        # Безопасная загрузка метадаты (без лишних переопределений)
        try:
            metadata = await self._get_metadata(ctx)
            classes = metadata.classes
            groups = metadata.groups
        except Exception as e:
            logger.error("Infrastructure error: Failed to load schedule metadata: %s", e)
            classes, groups = {}, {}

        summaries_by_recipient = {}

        for task in tasks:
            try:
                recipient_id = task.recipient_id
                target_student_id = task.target_student_id
                child_class_id = task.class_id
                child_group_id = task.group_id or "ALL"

                lessons_dtos: list[MorningLessonDTO] = []
                day_permutation = False  # ПАТЧ 3: Инициализация по умолчанию

                if child_class_id:
                    # ПАТЧ 4: Решение проблемы N+1 через кэширование уроков класса в контексте тика
                    cache_key = (child_class_id, today_iso)
                    if cache_key not in ctx.lessons_cache:
                        ctx.lessons_cache[cache_key] = await self.schedule_repo.get_lessons_for_class(class_id=child_class_id, date_iso=today_iso)
                        ctx.queries += 1
                    
                    lessons = ctx.lessons_cache[cache_key]
                    day_permutation = self.schedule_service.detect_day_permutation(lessons)
                    
                    display_key = (child_class_id, today_iso)
                    if display_key not in ctx.display_numbers_cache:
                        ctx.display_numbers_cache[display_key] = await self.schedule_service.get_display_numbers_for_class_day(class_id=child_class_id, date_iso=today_iso)
                    
                    display_numbers = ctx.display_numbers_cache[display_key]
                    user_groups = [str(g).strip() for g in child_group_id.split(",")] if child_group_id != "ALL" else ["ALL"]
                    
                    user_equivs = set()
                    for ug in user_groups:
                        user_equivs.update(self.schedule_service.get_equivalent_groups(ug, groups))

                    for lesson in lessons:
                        lesson_group_id = str(lesson.group_id).strip() if lesson.group_id else "ALL"
                        
                        # --- ЛОГИРОВАНИЕ ДЛЯ ОТЛАДКИ --- оставить для отладки
                        # logger.warning выведет это в консоль желтым цветом, чтобы ты точно заметил!
                        # logger.warning(
                        #     f"STUDENT FILTER CHECK | Recipient: {recipient_id} | "
                        #     f"User wants: {user_groups} | Lesson has ID: '{lesson_group_id}', Name: '{lesson_group_id}' | "
                        #     f"Subject: {lesson.subject_name}"
                        # )
                        
                        
                        # === УМНЫЙ ФИЛЬТР ПО АЛИАСАМ ===
                        if "ALL" not in user_groups and lesson_group_id != "ALL":
                            lesson_equivs = self.schedule_service.get_equivalent_groups(lesson_group_id, groups)
                            if not (user_equivs & lesson_equivs):
                                continue

                        group_name = groups.get(lesson_group_id, f"Группа {lesson_group_id}") if lesson_group_id != "ALL" and (child_group_id == "ALL" or len(user_groups) > 1) else None

                        # ПАТЧ 1: Используем .by_lesson_num.get() для DisplayNumbersDTO
                        lesson_display_num = display_numbers.by_lesson_num.get(
                            lesson.lesson_num,
                            (str(lesson.lesson_num) if lesson.lesson_num is not None else "•")
                        )

                        lessons_dtos.append(
                            NotificationMapper.map_school_lesson_to_morning_dto(
                                lesson, display_num=lesson_display_num, group_name=group_name, day_permutation=day_permutation,
                            )
                        )

                if target_student_id is not None:
                    extra_items = await self.extra_classes_service.get_extra_classes_for_student(student_id=target_student_id, day_of_week=weekday)
                    ctx.queries += 1
                    lessons_dtos.extend(NotificationMapper.map_extra_to_morning_dto(extra) for extra in extra_items)

                if not lessons_dtos: continue

                lessons_dtos.sort(key=lambda item: (item.start_time.zfill(5) if item.start_time and item.start_time != "—" else "99:99", item.lesson_num if item.lesson_num is not None else 99))
                
                class_obj = classes.get(child_class_id) if child_class_id else None
                class_name = class_obj.name if class_obj else child_class_id
                human_group_name = groups.get(child_group_id, f"Группа {child_group_id}") if child_group_id and child_group_id != "ALL" else None
                    
                summary_dto = MorningSummaryDTO(
                    date_iso=today_iso, lessons=lessons_dtos, child_name=(task.child_name if task.recipient_kind == "adult" else None),
                    class_id=child_class_id, class_name=class_name, group_name=human_group_name,
                    has_permutation=day_permutation, origin="student",
                )
                summaries_by_recipient.setdefault(recipient_id, []).append((task, summary_dto))

            except (KeyError, ValueError, TypeError) as e:
                logger.error("Data prep error: Morning summary assembly failed for recipient=%s: %s", task.recipient_id, e)
            except Exception as e:
                logger.exception("Infrastructure error during morning summary assembly: %s", e)

        # Словарь вместо простого списка
        candidates_map = {}
        
        for recipient_id, entries in summaries_by_recipient.items():
            for task, summary_dto in entries:
                
                # Уникальный ключ: Получатель + Ребенок + Класс
                dedup_key = (recipient_id, task.target_student_id, task.class_id)
                if dedup_key in candidates_map:
                    continue
                    
                try:
                    text = UIRenderer.render_morning_summary(summary_dto)
                except Exception as e:
                    logger.error("Render error: Failed to render morning summary for recipient=%s: %s", recipient_id, e)
                    continue
                    
                has_changes = any((lesson.is_exchange or lesson.is_cancelled) for lesson in summary_dto.lessons if not lesson.is_extra)
                action_type, action_payload = None, None

                if has_changes:
                    action_type = "day_changes"
                    action_payload = {"target_kind": "student", "target_id": task.target_student_id, "class_id": str(task.class_id), "group_id": str(task.group_id or "ALL"), "date_iso": today_iso, "origin": "class", "return_to": "morning"}

                candidates_map[dedup_key] = NotificationSendDTO(
                    notification_type="morning_summary", notification_date=today_iso, source_ids=[f"morning_summary:{task.target_student_id}"],
                    recipient_id=recipient_id, text=text, action_type=action_type, action_payload=action_payload, context=f"student_id={task.target_student_id}"
                )

        candidates = list(candidates_map.values())
        ctx.candidates += len(candidates)
        return candidates

    async def collect_teacher_morning_summaries(self, ctx: NotificationTickContext) -> list[NotificationSendDTO]:
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()

        try:
            tasks = await self.repo.get_teacher_morning_summary_tasks(time_str=now.strftime("%H:%M"))
            ctx.queries += 1
        except Exception as e:
            logger.exception("Infrastructure error: Failed to fetch tasks/lessons: %s", e)
            return []
        if not tasks: return []
            
        ctx.processed_entities += len(tasks)

        try:
            metadata = await self._get_metadata(ctx)
            classes = metadata.classes
            groups = metadata.groups
        except Exception as e:
            logger.error("Infrastructure error: Failed to load schedule metadata: %s", e)
            classes, groups = {}, {}
        
        candidates_map = {}

        for task in tasks:
            try:
                recipient_id = task.recipient_id
                teacher_id = task.teacher_id
                teacher_name = task.teacher_name or "Учитель"
                # Уникальный ключ: Получатель + Учитель
                dedup_key = (recipient_id, teacher_id)
                if dedup_key in candidates_map:
                    continue

                lessons = await self.schedule_repo.get_lessons_for_teacher(teacher_id=teacher_id, date_iso=today_iso)
                ctx.queries += 1
                lessons_dtos: list[MorningLessonDTO] = []

                for lesson in lessons:
                    class_obj = classes.get(lesson.class_id) if lesson.class_id else None
                    class_name = lesson.class_name or (class_obj.name if class_obj else lesson.class_id)

                    lesson_group_id = str(lesson.group_id).strip() if lesson.group_id else "ALL"
                    
                    # --- ЛОГИРОВАНИЕ ДЛЯ УЧИТЕЛЯ --- Оставить для отладки 
                    # logger.warning(
                    #     f"TEACHER GROUP CHECK | Teacher: {teacher_id} | "
                    #     f"Subject: {lesson.subject_name} | Class: {class_name} | "
                    #     f"NIKA group_id: '{lesson.group_id}' -> parsed as '{lesson_group_id}'"
                    # )

                    group_name = groups.get(lesson_group_id, f"Группа {lesson_group_id}") if lesson_group_id != "ALL" else None

                    lessons_dtos.append(
                        NotificationMapper.map_school_lesson_to_morning_dto(
                            lesson, display_num=(str(lesson.lesson_num) if lesson.lesson_num is not None else "•"),
                            class_name=class_name, group_name=group_name, day_permutation=False,
                        )
                    )

                if not lessons_dtos: continue
                lessons_dtos.sort(key=lambda item: (item.start_time.zfill(5) if item.start_time and item.start_time != "—" else "99:99", item.lesson_num if item.lesson_num is not None else 99))
                
                summary_dto = MorningSummaryDTO(                    
                    date_iso=today_iso, lessons=lessons_dtos, child_name=None, class_id=None,
                    class_name=None, teacher_name=teacher_name, has_permutation=False, origin="teacher",
                )

                try: text = UIRenderer.render_morning_summary(summary_dto)
                except Exception as e:
                    logger.error("Render error: Failed to render teacher morning summary for %s: %s", teacher_id, e)
                    continue

                has_changes = any((lesson.is_exchange or lesson.is_cancelled) for lesson in summary_dto.lessons if not lesson.is_extra)
                action_type, action_payload = None, None

                if has_changes:
                    action_type = "day_changes"
                    action_payload = {"target_kind": "teacher", "target_id": teacher_id, "class_id": "ALL", "group_id": "ALL", "date_iso": today_iso, "origin": "teacher", "return_to": "morning"}

                candidates_map[dedup_key] = NotificationSendDTO(
                    notification_type="teacher_morning", notification_date=today_iso, source_ids=[f"teacher_morning:{teacher_id}"],
                    recipient_id=recipient_id, text=text, action_type=action_type, action_payload=action_payload, context=f"teacher_id={teacher_id}"
                )

            except (KeyError, ValueError, TypeError) as e:
                logger.error("Data prep error: Teacher morning summary failed for %s: %s", getattr(task, 'teacher_id', 'unknown'), e)
            except Exception as e:
                logger.exception("Infrastructure error during teacher morning summary: %s", e)

        candidates = list(candidates_map.values())
        ctx.candidates += len(candidates)
        return candidates

    async def collect_upcoming_changes(self, ctx: NotificationTickContext) -> list[NotificationSendDTO]:
        now = self.time_service.get_now_base()
        today = now.date()
        today_iso = today.isoformat()
        window_end_iso = (today + datetime.timedelta(days=MAX_CHANGES_WINDOW_DAYS)).isoformat()

        try:
            changes = await self.repo.get_pending_changes(start_date_iso=today_iso, end_date_iso=window_end_iso)
            ctx.queries += 1
        except Exception as e:
            logger.exception("Infrastructure error: Failed to fetch pending changes: %s", e)
            return []
            
        ctx.processed_entities += len(changes)

        try:
            metadata = await self._get_metadata(ctx)
            classes, groups = metadata.classes, metadata.groups
        except Exception as e:
            logger.error("Infrastructure error: Failed to load schedule metadata: %s", e)
            classes, groups = {}, {}
        
        # 1. Формируем списки всех потенциальных получателей
        raw_student_candidates = []
        raw_teacher_candidates = []
        student_candidate_keys = []
        teacher_candidate_keys = []

        for change in changes:
            try:
                change_date = self.time_service.date_from_iso(change.date)

                display_key = (change.class_id, change.date)
                if display_key not in ctx.display_numbers_cache:
                    ctx.display_numbers_cache[display_key] = await self.schedule_service.get_display_numbers_for_class_day(class_id=change.class_id, date_iso=change.date)
                
                display_numbers = ctx.display_numbers_cache[display_key]
                # ПАТЧ 1: Используем .by_lesson_num.get()
                class_display_num = display_numbers.by_lesson_num.get(change.lesson_num, str(change.lesson_num))

                class_obj = classes.get(change.class_id)
                human_class_name = class_obj.name if class_obj is not None else change.class_id
                
                human_group_name = change.group_name
                if not human_group_name and change.group_id and change.group_id != "ALL":
                    human_group_name = groups.get(change.group_id, f"Группа {change.group_id}")

                # === ГЕНЕРАЦИЯ АЛИАСОВ ДЛЯ ЗАПРОСА В БД ===
                lesson_group_id = str(change.group_id).strip() if change.group_id else "ALL"
                possible_groups = self.schedule_service.get_equivalent_groups(lesson_group_id, groups)

                all_recipients = []
                for pg in possible_groups:
                    cache_key = (change.class_id, pg)
                    if cache_key not in ctx.change_recipients_cache:
                        ctx.change_recipients_cache[cache_key] = await self.repo.get_recipients_for_schedule_change(class_id=change.class_id, group_id=pg)
                        ctx.queries += 1
                    all_recipients.extend(ctx.change_recipients_cache[cache_key])
                
                seen_recipients = set()
                unique_recipients = []
                for r in all_recipients:
                    if r.recipient_id not in seen_recipients:
                        seen_recipients.add(r.recipient_id)
                        unique_recipients.append(r)

                for recipient in unique_recipients:
                    window_days = recipient.changes_window_days
                    if window_days > 0 and (today <= change_date <= (today + datetime.timedelta(days=window_days))):
                        del_key = DeliveredKeyDTO(change.date, change.id, recipient.recipient_id)
                        student_candidate_keys.append(del_key)
                        # Передаем расшифрованные имена
                        raw_student_candidates.append((del_key, change, recipient, class_display_num, human_class_name, human_group_name))

                teacher_id = change.teacher_id
                if not teacher_id: continue

                if teacher_id not in ctx.teacher_change_cache:
                    ctx.teacher_change_cache[teacher_id] = await self.repo.get_teacher_recipients_for_schedule_change(teacher_id=teacher_id)
                    ctx.queries += 1

                for recipient in ctx.teacher_change_cache[teacher_id]:
                    window_days = recipient.changes_window_days
                    if window_days > 0 and (today <= change_date <= (today + datetime.timedelta(days=window_days))):
                        del_key = DeliveredKeyDTO(change.date, change.id, recipient.recipient_id)
                        teacher_candidate_keys.append(del_key)
                        teacher_name = change.teacher_name or "Учитель"
                        raw_teacher_candidates.append((del_key, change, recipient, teacher_name, human_class_name, human_group_name))

            except Exception as e:
                logger.error("Data prep error for schedule change=%s: %s", getattr(change, 'id', 'unknown'), e)

        try:
            student_delivered = await self.repo.get_delivered_keys(notification_type="schedule_change", candidate_keys=student_candidate_keys)
            teacher_delivered = await self.repo.get_delivered_keys(notification_type="teacher_change", candidate_keys=teacher_candidate_keys)
            ctx.queries += 2
        except Exception as e:
            logger.error("Infrastructure error: Failed to fetch delivered keys for delta filter: %s", e)
            student_delivered, teacher_delivered = set(), set()

        def get_change_score(c: PendingChangeDTO) -> int:
            return 3 if c.is_exchange and c.original_subject_name else (2 if c.is_exchange else 1)

        def resolve_cascades(lesson_group_items):
            """БИЗНЕС-ЛОГИКА: Разрешает конфликты подгрупп внутри одного номера урока."""
            all_group_changes = [it for it in lesson_group_items if str(it[1].group_id).strip() in ("ALL", "Весь класс")]
            if all_group_changes:
                best_item = max(all_group_changes, key=lambda it: get_change_score(it[1]))
                discarded_ids = [it[1].id for it in lesson_group_items]
                return [best_item], discarded_ids
            else:
                subgroup_map = {}
                for it in lesson_group_items:
                    grp = str(it[1].group_id).strip()
                    score = get_change_score(it[1])
                    if grp not in subgroup_map or score >= subgroup_map[grp]["score"]:
                        subgroup_map[grp] = {"item": it, "score": score}
                final_items = [v["item"] for v in subgroup_map.values()]
                discarded_ids = [it[1].id for it in lesson_group_items]
                return final_items, discarded_ids

        # Семантическая группировка (ОБРАТИ ВНИМАНИЕ: change.class_id добавлен в ключ!)
        student_lesson_groups = defaultdict(list)
        for item in raw_student_candidates:
            del_key, change, recipient, class_display_num, h_class, h_group = item
            if del_key in student_delivered: continue 
            slot_key = (recipient.recipient_id, change.class_id, recipient.child_name, change.date, change.lesson_num)
            student_lesson_groups[slot_key].append(item)

        teacher_lesson_groups = defaultdict(list)
        for item in raw_teacher_candidates:
            del_key, change, recipient, teacher_name, h_class, h_group = item
            if del_key in teacher_delivered: continue 
            slot_key = (recipient.recipient_id, change.class_id, change.date, change.lesson_num)
            teacher_lesson_groups[slot_key].append(item)

        student_candidates_map = {}
        for slot_key, items in student_lesson_groups.items():
            final_items, all_slot_ids = resolve_cascades(items)
            for i, item in enumerate(final_items):
                del_key, change, recipient, class_display_num, h_class, h_group = item
                dto = NotificationMapper.to_change_reminder_dto(
                    change, display_num=class_display_num, child_name=(recipient.child_name if recipient.recipient_kind == "adult" else None),
                    watch_target_title=(recipient.watch_target_title if recipient.recipient_kind == "watch" else None), class_name=h_class, group_name=h_group
                )
                map_key = (*slot_key, change.group_id)
                # ПРОКИНУТ change.class_id пятым аргументом в кортеж
                student_candidates_map[map_key] = (recipient.recipient_id, change.date, recipient, change.class_id, dto, all_slot_ids if i == 0 else [])
                
        teacher_candidates_map = {}
        for slot_key, items in teacher_lesson_groups.items():
            final_items, all_slot_ids = resolve_cascades(items)
            for i, item in enumerate(final_items):
                del_key, change, recipient, teacher_name, h_class, h_group = item
                dto = NotificationMapper.to_change_reminder_dto(change, display_num=str(change.lesson_num), class_name=h_class, group_name=h_group)
                map_key = (*slot_key, change.group_id)
                # ПРОКИНУТ change.teacher_id пятым аргументом в кортеж
                teacher_candidates_map[map_key] = (recipient.recipient_id, change.date, recipient, change.teacher_id, dto, teacher_name, all_slot_ids if i == 0 else [])
        # Выгружаем значения из словарей (они теперь содержат class_id/teacher_id внутри кортежей)
        student_records = list(student_candidates_map.values())
        teacher_records = list(teacher_candidates_map.values())

        candidates = []
        candidates.extend(DailyChangesAggregator.aggregate_student_changes(student_records))
        candidates.extend(DailyChangesAggregator.aggregate_teacher_changes(teacher_records))
        ctx.candidates += len(candidates)
        return candidates
    
    async def collect_pre_lesson_reminders(self, ctx: NotificationTickContext) -> list[NotificationSendDTO]:
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()

        try:
            lessons = await self.repo.get_todays_lessons_for_pre_reminders(date_iso=today_iso)
            ctx.queries += 1
        except Exception as e:
            logger.exception("Infrastructure error: Failed to fetch todays lessons: %s", e)
            return []
            
        ctx.processed_entities += len(lessons)
        
        try:
            metadata = await self._get_metadata(ctx)
            groups = metadata.groups
        except Exception: groups = {}
        
        # 1. Словари для семантической дедупликации
        student_candidates_map: dict[tuple[int, str], NotificationSendDTO] = {}
        teacher_candidates_map: dict[tuple[int, str], NotificationSendDTO] = {}

        for lesson in lessons:
            try:
                lesson_start_at = datetime.datetime.strptime(f"{today_iso} {lesson.start_time}", "%Y-%m-%d %H:%M").replace(tzinfo=self.time_service.base_tz)
                delta_minutes = (lesson_start_at - now).total_seconds() / 60.0
                if delta_minutes <= 0: continue

                lesson_group_id = str(lesson.group_id).strip() if lesson.group_id else "ALL"
                possible_groups = self.schedule_service.get_equivalent_groups(lesson_group_id, groups)

                all_recipients: list[PreLessonRecipientDTO] = []
                for pg in possible_groups:
                    cache_key = (lesson.class_id, pg)
                    if cache_key not in ctx.pre_lesson_recipients_cache:
                        ctx.pre_lesson_recipients_cache[cache_key] = await self.repo.get_recipients_for_pre_lesson_reminder(class_id=lesson.class_id, group_id=pg)
                        ctx.queries += 1
                    all_recipients.extend(ctx.pre_lesson_recipients_cache[cache_key])

                seen_recipients = set()
                unique_recipients: list[PreLessonRecipientDTO] = []
                for r in all_recipients:
                    if r.recipient_id not in seen_recipients:
                        seen_recipients.add(r.recipient_id)
                        unique_recipients.append(r)

                for recipient in unique_recipients:
                    offset_minutes = recipient.offset_minutes
                    if offset_minutes <= 0 or delta_minutes > offset_minutes: continue

                    # Дедупликация для учеников и родителей
                    # Добавлен child_name и class_id для изоляции детей в одной семье
                    dedup_key = (recipient.recipient_id, recipient.child_name, lesson.class_id, lesson.start_time)
                    
                    if dedup_key not in student_candidates_map:
                        dto = LessonReminderDTO(
                            subject_name=lesson.subject_name or "—", start_time=lesson.start_time or "—",
                            room_name=lesson.room_name or "—", is_extra=False, child_name=(recipient.child_name if recipient.recipient_kind == "adult" else None),
                        )
                        try: 
                            text = UIRenderer.render_lesson_reminder(dto)
                            student_candidates_map[dedup_key] = NotificationSendDTO(
                                notification_type="pre_lesson", notification_date=today_iso, 
                                source_ids=[lesson.id], # Начинаем копить ID
                                recipient_id=recipient.recipient_id, text=text, context=f"lesson_id={lesson.id}, kind={recipient.recipient_kind}",
                            )
                        except Exception as e:
                            logger.error("Render error for lesson reminder %s: %s", lesson.id, e)
                    else:
                        # Схлопываем фантомный дубль, добавляя его ID
                        student_candidates_map[dedup_key].source_ids.append(lesson.id)

                teacher_id = lesson.teacher_id
                if not teacher_id: continue

                if teacher_id not in ctx.teacher_pre_lesson_cache:
                    ctx.teacher_pre_lesson_cache[teacher_id] = await self.repo.get_teacher_recipients_for_pre_lesson_reminder(teacher_id=teacher_id)
                    ctx.queries += 1

                for recipient in ctx.teacher_pre_lesson_cache[teacher_id]:
                    offset_minutes = recipient.offset_minutes
                    if offset_minutes <= 0 or delta_minutes > offset_minutes: continue

                    # Дедупликация для учителей
                    # Добавлен teacher_id для изоляции подписок
                    dedup_key = (recipient.recipient_id, teacher_id, lesson.start_time)
                    
                    if dedup_key not in teacher_candidates_map:
                        dto = LessonReminderDTO(
                            subject_name=lesson.subject_name or "—", start_time=lesson.start_time or "—",
                            room_name=lesson.room_name or "—", is_extra=False, child_name=None,
                        )
                        try:
                            text = UIRenderer.render_lesson_reminder(dto)
                            teacher_candidates_map[dedup_key] = NotificationSendDTO(
                                notification_type="teacher_pre_lesson", notification_date=today_iso, 
                                source_ids=[lesson.id], # Начинаем копить ID
                                recipient_id=recipient.recipient_id, text=text, context=f"teacher_id={teacher_id}, lesson_id={lesson.id}",
                            )
                        except Exception as e:
                            logger.error("Render error for teacher lesson reminder %s: %s", lesson.id, e)
                    else:
                        # Схлопываем фантомный дубль учителя
                        teacher_candidates_map[dedup_key].source_ids.append(lesson.id)

            except (KeyError, ValueError, TypeError) as e:
                logger.error("Data prep error for pre-lesson reminder lesson=%s: %s", getattr(lesson, 'id', 'unknown'), e)
            except Exception as e:
                logger.exception("Infrastructure error during pre-lesson collection: %s", e)

        # 2. Выгружаем очищенные списки
        candidates = list(student_candidates_map.values()) + list(teacher_candidates_map.values())
        ctx.candidates += len(candidates)
        return candidates

    async def collect_extra_class_reminders(self, ctx: NotificationTickContext) -> list[NotificationSendDTO]:
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()
        weekday = now.isoweekday()

        try:
            extras = await self.repo.get_todays_extra_classes_for_reminders(day_of_week=weekday)
            ctx.queries += 1
        except Exception as e:
            logger.exception("Infrastructure error: Failed to fetch extra classes: %s", e)
            return []
            
        ctx.processed_entities += len(extras)
        # Внедрен словарь для In-Memory дедупликации
        candidates_map: dict[tuple[int, int], NotificationSendDTO] = {}

        for extra in extras:
            try:
                offset_minutes = extra.offset_minutes
                if offset_minutes <= 0: continue

                start_at = datetime.datetime.strptime(f"{today_iso} {extra.time_start}", "%Y-%m-%d %H:%M").replace(tzinfo=self.time_service.base_tz)
                delta_minutes = (start_at - now).total_seconds() / 60.0
                if delta_minutes <= 0 or delta_minutes > offset_minutes: continue

                # Уникальный ключ: Получатель + ID доп. занятия
                dedup_key = (extra.recipient_id, extra.extra_id)
                if dedup_key in candidates_map:
                    continue

                dto = LessonReminderDTO(
                    subject_name=extra.title, start_time=extra.time_start, room_name=extra.location or "—", is_extra=True,
                    child_name=(extra.child_name if extra.recipient_kind == "adult" else None),
                )

                try: 
                    text = UIRenderer.render_lesson_reminder(dto)
                except Exception as e:
                    logger.error("Render error for extra class %s: %s", extra.extra_id, e)
                    continue

                candidates_map[dedup_key] = NotificationSendDTO(
                    notification_type="extra_class", notification_date=today_iso, source_ids=[str(extra.extra_id)],
                    recipient_id=extra.recipient_id, text=text, context=f"extra_id={extra.extra_id}, kind={extra.recipient_kind}",
                )

            except (KeyError, ValueError, TypeError) as e:
                logger.error("Data prep error for extra class=%s: %s", getattr(extra, 'extra_id', 'unknown'), e)
            except Exception as e:
                logger.exception("Infrastructure error during extra class collect: %s", e)

        candidates = list(candidates_map.values())
        ctx.candidates += len(candidates)
        return candidates