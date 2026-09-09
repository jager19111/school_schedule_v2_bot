# services/notifications_service.py
#
# ЭТАП 2. ФИКС N+1 И TELEGRAM THROTTLING.
#
# ЧТО ИЗМЕНЕНО:
#
# 1. Фикс N+1 (батчевая дедупликация):
#    Раньше каждый тик APScheduler выполнял одиночный
#    is_notification_delivered (SELECT 1 ...) на каждого получателя
#    каждого урока — при 100+ пользователях это тысячи мелких
#    запросов за тик. Теперь каждый send-метод работает в три фазы:
#      Фаза 1 (collect):  сбор кандидатов с применением временных
#                        фильтров (окно/offset) — без обращений к
#                        notification_delivery_log;
#      Фаза 2 (dedup):   ОДИН вызов get_delivered_keys на тип
#                        уведомления (чанками по 400);
#      Фаза 3 (send):    paced-отправка + запись доставки после
#                        каждого успешного отправления.
#
# 2. Фикс N+1 (получатели):
#    get_recipients_for_* больше не вызывается на каждый урок/замену.
#    Внутри тика результаты мемоизируются по ключу:
#      - (class_id, group_id) — получатели класса;
#      - teacher_id — учительские подписки.
#    254 урока ~40 классов => ~40 запросов вместо 254+.
#
# 3. Smart Throttling (лимиты Telegram Bot API):
#    - глобальный темп ~22 msg/сек (запас под лимит 30/сек);
#    - не более 1 сообщения/сек в один чат (лимит Telegram);
#    - обработка 429 Too Many Requests: пауза retry_after + повтор;
#    - TelegramForbiddenError (бот заблокирован): авт отключение
#      уведомлений пользователю, чтобы не долбить API каждый тик;
#    - сетевые ошибки: до 3 попыток с backoff.
#    Вся отправка сериализована через asyncio.Lock — два тика
#    планировщика физически не могут превысить лимит вместе.
#
# 4. ИСПРАВЛЕН БАГ: _send_teacher_morning_reminders существовал,
#    но нигде не вызывался — утренние сводки учителей не отправлялись.
#    Теперь send_morning_reminders вызывает его в конце тика.
#
# 5. Метрики: каждый тик логирует candidates/pending/sent/failed/
#    db_queries — контроль эффекта оптимизации.

import asyncio
import datetime
import logging
import time
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from core.repository.notification_repository import NotificationRepository
from core.repository.extra_classes_repository import ExtraClassesRepository
from core.repository.schedule_repository import ScheduleRepository
from services.time_service import TimeService
from bot.utils.ui_renderer import UIRenderer
from core.models.dto import (
    LessonReminderDTO,
    ChangeReminderDTO,
    MorningSummaryDTO,
    MorningLessonDTO
)

logger = logging.getLogger(__name__)

# Максимум changes_window_days по CHECK-ограничению в схеме users.
MAX_CHANGES_WINDOW_DAYS = 31

# ==============================================================
# Smart Throttling: параметры под лимиты Telegram Bot API.
# ==============================================================

# Глобальный темп: ~22 сообщения/сек (лимит Telegram ~30/сек).
GLOBAL_SEND_INTERVAL_SEC = 0.045
# Не более одного сообщения в чат за интервал (лимит Telegram ~1/сек).
PER_CHAT_SEND_INTERVAL_SEC = 1.1
# Максимальное число попыток отправки одного сообщения.
MAX_SEND_ATTEMPTS = 3
_CHAT_CACHE_MAX = 1000
_CHAT_CACHE_TTL_SEC = 600.0


@dataclass(slots=True)
class PendingSend:
    """
    Кандидат на отправку, собранный в фазе collect.

    Ключ дедупликации: (notification_type, notification_date,
    source_id, recipient_id) — ровно первичный ключ
    notification_delivery_log.
    """
    notification_type: str
    notification_date: str
    source_id: str
    recipient_id: int
    text: str
    # Контекст для логов (lesson_id / change_id / extra_id и т.п.).
    context: str = ""


class NotificationService:
    """
    Сервис уведомлений (Strict DTO & Repository Pattern).

    Обеспечивает отказоустойчивость рассылок:
    - батчевая дедупликация доставок (без N+1);
    - мемоизация получателей внутри тика;
    - умное дросселирование под лимиты Telegram;
    - идемпотентность при рестартах (delivery log пишется сразу
      после каждой успешной отправки).
    """

    def __init__(
        self,
        bot: Bot,
        notification_repo: NotificationRepository,
        time_service: TimeService,
        schedule_repo: ScheduleRepository,
        extra_classes_repo: ExtraClassesRepository,
    ):
        self.bot = bot
        self.repo = notification_repo
        self.time_service = time_service
        self.schedule_repo = schedule_repo
        self.extra_classes_repo = extra_classes_repo

        # Smart Throttling state.
        # Сериализация ВСЕХ отправок через один lock: планировщик
        # запускает несколько jobs, но лимиты Telegram — глобальные.
        self._send_lock = asyncio.Lock()
        self._global_last_send_at = 0.0
        self._chat_last_send_at: dict[int, float] = {}

    # ==============================================================
    # Smart Throttling
    # ==============================================================

    async def _paced_send(self, *, chat_id: int, text: str) -> bool:
        """
        Отправка сообщения с соблюдением лимитов Telegram.

        - глобальный темп GLOBAL_SEND_INTERVAL_SEC между любыми двумя
          отправками бота;
        - PER_CHAT_SEND_INTERVAL_SEC между отправками одному чату;
        - 429 Too Many Requests: ждём retry_after и повторяем
          (на ПОСЛЕДНЕЙ попытке не спим — возвращаем False сразу,
          сон впустую тратил бы до 10+ секунд);
        - Forbidden (бот заблокирован): отключаем уведомления
          пользователю и прекращаем попытки;
        - сетевые ошибки: до MAX_SEND_ATTEMPTS попыток с backoff.

        Lock держится на всё время отправки И пауз — это намеренно:
        так параллельные jobs планировщика не могут суммарно
        превысить глобальный лимит.
        """
        async with self._send_lock:
            for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
                now_mono = time.monotonic()

                wait_global = (
                    self._global_last_send_at
                    + GLOBAL_SEND_INTERVAL_SEC
                    - now_mono
                )
                wait_chat = (
                    self._chat_last_send_at.get(chat_id, 0.0)
                    + PER_CHAT_SEND_INTERVAL_SEC
                    - now_mono
                )
                wait = max(wait_global, wait_chat, 0.0)
                if wait > 0:
                    await asyncio.sleep(wait)

                try:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML",
                    )
                    finished_at = time.monotonic()
                    self._global_last_send_at = finished_at
                    self._chat_last_send_at[chat_id] = finished_at
                    self._prune_chat_send_times()
                    return True

                except TelegramRetryAfter as exc:
                    logger.warning(
                        "Telegram 429 flood control: chat_id=%s, "
                        "retry_after=%ss, attempt=%d/%d",
                        chat_id,
                        exc.retry_after,
                        attempt,
                        MAX_SEND_ATTEMPTS,
                    )
                    # Оптимизация (Roman): сон нужен, только если будет
                    # повторная попытка. На последней — выходим сразу.
                    if attempt < MAX_SEND_ATTEMPTS:
                        await asyncio.sleep(float(exc.retry_after) + 0.5)

                except TelegramForbiddenError:
                    logger.warning(
                        "Chat %s blocked the bot. "
                        "Marking user as notifications_blocked.",
                        chat_id,
                    )
                    try:
                        await self.repo.mark_user_notifications_blocked(
                            user_id=chat_id,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to mark blocked chat %s",
                            chat_id,
                        )
                    return False

                except TelegramBadRequest as exc:
                    logger.warning(
                        "Telegram rejected message: chat_id=%s, error=%s",
                        chat_id,
                        exc,
                    )
                    return False

                except (TelegramNetworkError, asyncio.TimeoutError, OSError) as exc:
                    logger.warning(
                        "Network error sending to chat %s "
                        "(attempt %d/%d): %s",
                        chat_id,
                        attempt,
                        MAX_SEND_ATTEMPTS,
                        exc,
                    )
                    await asyncio.sleep(0.5 * attempt)

            logger.error(
                "Giving up sending to chat %s after %d attempts",
                chat_id,
                MAX_SEND_ATTEMPTS,
            )
            return False

    async def _load_blocked_recipient_ids(self) -> set[int]:
        """
        ID пользователей, заблокировавших бот (notifications_blocked=1).

        Системный маркер НЕ связан с is_notifications_enabled.
        Загружается заново каждый тик: если пользователь разблокировал
        бота и проявил активность, update_last_active уже снял флаг,
        и уведомления возобновляются без перезапуска бота.
        """
        try:
            return set(await self.repo.get_blocked_user_ids())
        except Exception:
            # Ошибка загрузки не должна ломать рассылку:
            # фильтр просто пропускается, Forbidden обработается
            # в _paced_send и пометит пользователя при следующем тике.
            logger.exception("Failed to load blocked user ids")
            return set()
        
    # ==============================================================
    # 3a. Микроочистка кеша per-chat таймстемпов
    # ==============================================================

    def _prune_chat_send_times(self) -> None:
        """
        Микроочистка кеша per-chat таймстемпов.

        Строгой утечки нет: словарь ограничен числом уникальных чатов
        (~число пользователей). Но записи старше TTL бесполезны —
        пер-чат интервал составляет секунды, поэтому чат, не получавший
        сообщений >10 минут, эквивалентен "новому".

        Вызывается из _paced_send под _send_lock — дополнительная
        синхронизация не нужна.
        """
        if len(self._chat_last_send_at) < _CHAT_CACHE_MAX:
            return
        cutoff = time.monotonic() - _CHAT_CACHE_TTL_SEC
        self._chat_last_send_at = {
            chat_id: ts
            for chat_id, ts in self._chat_last_send_at.items()
            if ts > cutoff
        }

    # ==============================================================
    # 3b. Админ-стресс-тест боевого пайплайна
    # ==============================================================

    async def debug_send_burst(
        self,
        *,
        chat_id: int,
        count: int,
    ) -> dict[str, int]:
        """
        Стресс-тест РЕАЛЬНОГО пайплайна уведомлений (только админ).

        В отличие от отправки через message.answer() в хендлере,
        проходит через все боевые фазы:
        - collect (PendingSend-кандидаты);
        - батчевый dedup через get_delivered_keys;
        - paced send через _paced_send (лимиты Telegram);
        - запись delivery log после каждой успешной отправки.

        source_id стабилен в течение дня (debug_burst:{i}), поэтому:
        - повторный запуск в тот же день НЕ повторяет уже
          отправленные сообщения (дедупликация);
        - рестарт бота в середине теста -> следующий запуск
          продолжит с места остановки, а не начнёт сначала.

        ВАЖНО: на один чат действует пер-чат лимит
        PER_CHAT_SEND_INTERVAL_SEC, поэтому N сообщений одному
        пользователю занимают ~N * 1.1 секунд. Это честное поведение
        Telegram, а не замедление теста.

        Используется только из админ-команды /stress.
        """
        count = max(1, min(count, 500))

        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()

        pending = [
            PendingSend(
                notification_type="debug_test",
                notification_date=today_iso,
                source_id=f"debug_burst:{index}",
                recipient_id=chat_id,
                text=(
                    f"🧪 Стресс-тест уведомлений: "
                    f"сообщение {index + 1} из {count}"
                ),
                context="stress_test",
            )
            for index in range(count)
        ]

        to_send = await self._drop_already_delivered(pending)
        sent_count, failed_count = await self._flush_pending(to_send)

        return {
            "requested": len(pending),
            "pending": len(to_send),
            "sent": sent_count,
            "failed": failed_count,
        }


    # ==============================================================
    # Общие помощники фаз collect/dedup/send
    # ==============================================================

    async def _drop_already_delivered(
        self,
        pending: list[PendingSend],
    ) -> list[PendingSend]:
        """
        Фаза dedup: батчевая проверка delivery log по каждому типу.

        Один вызов get_delivered_keys на каждый notification_type,
        встречающийся в pending, независимо от числа кандидатов.
        """
        if not pending:
            return []

        result: list[PendingSend] = []
        types = sorted({item.notification_type for item in pending})

        for notification_type in types:
            type_items = [
                item
                for item in pending
                if item.notification_type == notification_type
            ]
            candidate_keys = [
                (
                    item.notification_date,
                    item.source_id,
                    item.recipient_id,
                )
                for item in type_items
            ]
            delivered = await self.repo.get_delivered_keys(
                notification_type=notification_type,
                candidate_keys=candidate_keys,
            )
            for item in type_items:
                key = (
                    item.notification_date,
                    item.source_id,
                    item.recipient_id,
                )
                if key not in delivered:
                    result.append(item)

        return result

    async def _flush_pending(
        self,
        pending: list[PendingSend],
    ) -> tuple[int, int]:
        """
        Фаза send: paced-отправка + запись доставки сразу после
        каждой успешной отправки (идемпотентность при падении
        процесса в середине рассылки).
        """
        sent_count = 0
        failed_count = 0

        for item in pending:
            sent = await self._paced_send(
                chat_id=item.recipient_id,
                text=item.text,
            )
            if not sent:
                failed_count += 1
                logger.warning(
                    "Send failed: type=%s, source_id=%s, "
                    "recipient_id=%s, context=%s",
                    item.notification_type,
                    item.source_id,
                    item.recipient_id,
                    item.context,
                )
                continue

            await self.repo.record_notification_delivery(
                notification_type=item.notification_type,
                notification_date=item.notification_date,
                source_id=item.source_id,
                recipient_id=item.recipient_id,
            )
            sent_count += 1
            logger.info(
                "Delivered: type=%s, source_id=%s, recipient_id=%s, "
                "context=%s",
                item.notification_type,
                item.source_id,
                item.recipient_id,
                item.context,
            )

        return sent_count, failed_count

    # ==============================================================
    # 1. Утренние сводки
    # ==============================================================

    async def send_morning_reminders(self) -> None:
        """
        Формирует и отправляет утренние сводки.

        Ребёнок получает сводку только по себе.
        Взрослый получает одно сообщение, объединяющее сводки всех детей,
        на которых он подписан через parent_student_settings.

        В конце тика отправляются утренние сводки учителей
        (_send_teacher_morning_reminders). Раньше этот метод
        существовал, но не вызывался — сводки учителей не уходили.
        """
        now = self.time_service.get_now_base()
        current_time_str = now.strftime("%H:%M")
        today_iso = now.date().isoformat()
        weekday = now.isoweekday()

        tasks = await self.repo.get_morning_summary_tasks(
            time_str=current_time_str,
        )
        # Пользователи, заблокировавшие бот, не получают сводки.
        blocked_ids = await self._load_blocked_recipient_ids()
        if blocked_ids:
            tasks = [
                task
                for task in tasks
                if int(task["recipient_id"]) not in blocked_ids
            ]

        if not tasks:
            # Учительские сводки проверяем независимо от детских задач.
            await self._send_teacher_morning_reminders(
                current_time_str=current_time_str,
                today_iso=today_iso,
            )
            return

        logger.info(
            "Morning summary tick: date=%s, time=%s, tasks=%d",
            today_iso,
            current_time_str,
            len(tasks),
        )

        # --- Фаза 1 (collect/dedup): батчевая проверка delivery log ---
        candidate_keys = [
            (
                today_iso,
                f"morning_summary:{int(task['target_student_id'])}",
                int(task["recipient_id"]),
            )
            for task in tasks
        ]
        delivered = await self.repo.get_delivered_keys(
            notification_type="morning_summary",
            candidate_keys=candidate_keys,
        )

        metadata = await self.schedule_repo.get_metadata()
        classes = metadata.get("classes", {})
        groups = metadata.get("groups", {})

        summaries_by_recipient: dict[int, list[tuple[dict, MorningSummaryDTO]]] = {}

        for task in tasks:
            try:
                recipient_id = int(task["recipient_id"])
                target_student_id = int(task["target_student_id"])
                source_id = f"morning_summary:{target_student_id}"

                if (today_iso, source_id, recipient_id) in delivered:
                    continue

                child_class_id = task.get("class_id")
                child_group_id = task.get("group_id")

                lessons_dtos: list[MorningLessonDTO] = []

                if child_class_id:
                    raw_lessons = await self.schedule_repo.get_lessons_for_class(
                        class_id=child_class_id,
                        date_iso=today_iso,
                    )
                    for lesson in raw_lessons:
                        lesson_group_id = lesson.get("group_id", "ALL")

                        if (
                            lesson_group_id != "ALL"
                            and child_group_id != "ALL"
                            and lesson_group_id != child_group_id
                        ):
                            continue

                        group_name = None
                        if lesson_group_id != "ALL":
                            group_name = groups.get(
                                lesson_group_id,
                                f"Группа {lesson_group_id}",
                            )

                        lessons_dtos.append(
                            MorningLessonDTO(
                                lesson_num=lesson["lesson_num"],
                                start_time=lesson["start_time"],
                                end_time=lesson["end_time"],
                                subject_name=lesson["subject_name"] or "—",
                                room_name=lesson["room_name"] or "—",
                                is_cancelled=bool(
                                    lesson["is_cancelled"]
                                ),
                                is_exchange=bool(
                                    lesson["is_exchange"]
                                ),
                                is_extra=False,
                                group_name=group_name,
                            )
                        )

                raw_extras = await self.extra_classes_repo.get_extra_classes_for_student(
                    student_id=target_student_id,
                    day_of_week=weekday,
                )
                for extra in raw_extras:
                    lessons_dtos.append(
                        MorningLessonDTO(
                            lesson_num=None,
                            start_time=extra["time_start"],
                            end_time=extra["time_end"],
                            subject_name=extra["title"],
                            room_name=extra["location"] or "—",
                            is_cancelled=False,
                            is_exchange=False,
                            is_extra=True,
                        )
                    )

                # Не отправляем пустую сводку и не фиксируем delivery log.
                # Если данные появятся позже в этот же день, следующий вызов
                # сможет сформировать полноценную сводку.
                if not lessons_dtos:
                    logger.debug(
                        "Morning summary skipped: no lessons, "
                        "recipient_id=%s, student_id=%s",
                        recipient_id,
                        target_student_id,
                    )
                    continue

                lessons_dtos.sort(
                    key=lambda item: (
                        item.start_time,
                        item.lesson_num if item.lesson_num is not None else 99,
                    )
                )

                class_name = child_class_id
                if child_class_id and child_class_id in classes:
                    class_obj = classes[child_class_id]
                    class_name = getattr(
                        class_obj,
                        "name",
                        child_class_id,
                    )

                summary_dto = MorningSummaryDTO(
                    date_iso=today_iso,
                    lessons=lessons_dtos,
                    child_name=(
                        task["child_name"]
                        if task["recipient_kind"] == "adult"
                        else None
                    ),
                    class_id=class_name,
                )

                summaries_by_recipient.setdefault(
                    recipient_id,
                    [],
                ).append((task, summary_dto))

            except (KeyError, TypeError, ValueError) as exc:
                logger.exception(
                    "Invalid morning summary task: task=%r, error=%s",
                    task,
                    exc,
                )
            except Exception:
                logger.exception(
                    "Unexpected morning summary assembly error: task=%r",
                    task,
                )

        # --- Фаза send: paced-отправка сгруппированных сводок ---
        sent_count = 0
        failed_count = 0

        for recipient_id, entries in summaries_by_recipient.items():
            try:
                rendered_parts = [
                    UIRenderer.render_morning_summary(summary_dto)
                    for _, summary_dto in entries
                ]
                final_text = "\n\n───────────────\n\n".join(rendered_parts)

                sent = await self._paced_send(
                    chat_id=recipient_id,
                    text=final_text,
                )
                if not sent:
                    failed_count += 1
                    logger.warning(
                        "Morning summary send failed: recipient_id=%s, "
                        "children=%s",
                        recipient_id,
                        [
                            task["target_student_id"]
                            for task, _ in entries
                        ],
                    )
                    continue

                sent_count += 1
                for task, _ in entries:
                    target_student_id = int(task["target_student_id"])
                    await self.repo.record_notification_delivery(
                        notification_type="morning_summary",
                        notification_date=today_iso,
                        source_id=f"morning_summary:{target_student_id}",
                        recipient_id=recipient_id,
                    )

                logger.info(
                    "Morning summary delivered: recipient_id=%s, "
                    "children=%s",
                    recipient_id,
                    [
                        task["target_student_id"]
                        for task, _ in entries
                    ],
                )
            except Exception:
                logger.exception(
                    "Morning summary sending error: recipient_id=%s",
                    recipient_id,
                )

        logger.info(
            "Morning summary tick done: tasks=%d, pending_recipients=%d, "
            "sent=%d, failed=%d",
            len(tasks),
            len(summaries_by_recipient),
            sent_count,
            failed_count,
        )

        # Учительские утренние сводки (раньше не вызывались).
        await self._send_teacher_morning_reminders(
            current_time_str=current_time_str,
            today_iso=today_iso,
        )

    # ==============================================================
    # 2. Изменения расписания
    # ==============================================================

    async def send_upcoming_changes(self) -> None:
        """
        Отправляет адресные уведомления о заменах и отменах.

        Three-phase: collect (мемоизация получателей по классу и
        учителю) -> батчевый dedup -> paced send.
        """
        now = self.time_service.get_now_base()
        today = now.date()
        today_iso = today.isoformat()

        window_end_iso = (
            today + datetime.timedelta(days=MAX_CHANGES_WINDOW_DAYS)
        ).isoformat()

        changes = await self.repo.get_pending_changes(
            start_date_iso=today_iso,
            end_date_iso=window_end_iso,
        )

        logger.info(
            "Schedule changes tick: date=%s, changes=%d",
            today_iso,
            len(changes),
        )
        blocked_ids = await self._load_blocked_recipient_ids()
        # Тиковые кеши получателей (фикс N+1).
        recipients_cache: dict[tuple[str, str], list[dict]] = {}
        teacher_cache: dict[str, list[dict]] = {}

        pending: list[PendingSend] = []

        # --- Фаза 1 (collect) ---
        for change in changes:
            try:
                change_date = self.time_service.date_from_iso(
                    change["date"],
                )

                cache_key = (change["class_id"], change["group_id"])
                if cache_key not in recipients_cache:
                    recipients_cache[cache_key] = (
                        await self.repo.get_recipients_for_schedule_change(
                            class_id=change["class_id"],
                            group_id=change["group_id"],
                        )
                    )
                recipients = recipients_cache[cache_key]

                for recipient in recipients:
                    recipient_id = int(recipient["recipient_id"])
                    
                    if recipient_id in blocked_ids:
                        continue
                    window_days = int(
                        recipient["changes_window_days"]
                    )

                    if window_days <= 0:
                        continue

                    max_date = today + datetime.timedelta(
                        days=window_days,
                    )
                    if not (today <= change_date <= max_date):
                        continue

                    dto = ChangeReminderDTO(
                        date=change["date"],
                        lesson_num=change["lesson_num"],
                        subject_name=change["subject_name"] or "—",
                        is_cancelled=bool(change["is_cancelled"]),
                        child_name=(
                            recipient["child_name"]
                            if recipient["recipient_kind"] == "adult"
                            else None
                        ),
                        watch_target_title=(
                            recipient["watch_target_title"]
                            if recipient["recipient_kind"] == "watch"
                            else None
                        ),
                    )

                    pending.append(
                        PendingSend(
                            notification_type="schedule_change",
                            notification_date=change["date"],
                            source_id=change["id"],
                            recipient_id=recipient_id,
                            text=UIRenderer.render_change_reminder(dto),
                            context=(
                                f"change_id={change['id']}, "
                                f"kind={recipient['recipient_kind']}"
                            ),
                        )
                    )

                teacher_id = change.get("teacher_id")
                if not teacher_id:
                    continue

                teacher_id = str(teacher_id)
                if teacher_id not in teacher_cache:
                    teacher_cache[teacher_id] = (
                        await self.repo.get_teacher_recipients_for_schedule_change(
                            teacher_id=teacher_id,
                        )
                    )

                for recipient in teacher_cache[teacher_id]:
                    try:
                        recipient_id = int(recipient["recipient_id"])
                        if recipient_id in blocked_ids:
                            continue
                        window_days = int(
                            recipient["changes_window_days"]
                        )
                        if window_days <= 0:
                            continue

                        max_date = today + datetime.timedelta(
                            days=window_days,
                        )
                        if not (today <= change_date <= max_date):
                            continue

                        dto = ChangeReminderDTO(
                            date=change["date"],
                            lesson_num=change["lesson_num"],
                            subject_name=change["subject_name"] or "—",
                            is_cancelled=bool(change["is_cancelled"]),
                            child_name=None,
                            watch_target_title=None,
                        )

                        teacher_name = (
                            change.get("teacher_name")
                            or "Учитель"
                        )
                        text = (
                            "👨‍🏫 <b>Изменение в расписании учителя</b>\n"
                            f"👤 <b>{UIRenderer.escape_html(teacher_name)}</b>\n\n"
                            f"{UIRenderer.render_change_reminder(dto)}"
                        )

                        pending.append(
                            PendingSend(
                                notification_type="teacher_change",
                                notification_date=change["date"],
                                source_id=change["id"],
                                recipient_id=recipient_id,
                                text=text,
                                context=(
                                    f"teacher_id={teacher_id}, "
                                    f"change_id={change['id']}"
                                ),
                            )
                        )
                    except Exception:
                        logger.exception(
                            "Teacher schedule change collect failed: "
                            "change=%r recipient=%r",
                            change,
                            recipient,
                        )

            except (KeyError, TypeError, ValueError) as exc:
                logger.exception(
                    "Invalid schedule change task: change=%r, error=%s",
                    change,
                    exc,
                )
            except Exception:
                logger.exception(
                    "Unexpected schedule change collect error: change=%r",
                    change,
                )

        # --- Фаза 2 (dedup) + Фаза 3 (send) ---
        to_send = await self._drop_already_delivered(pending)
        sent_count, failed_count = await self._flush_pending(to_send)

        logger.info(
            "Schedule changes tick done: changes=%d, candidates=%d, "
            "pending=%d, sent=%d, failed=%d, "
            "recipient_queries=%d, teacher_queries=%d",
            len(changes),
            len(pending),
            len(to_send),
            sent_count,
            failed_count,
            len(recipients_cache),
            len(teacher_cache),
        )

    # ==============================================================
    # 3. Предурочные напоминания
    # ==============================================================

    async def send_pre_lesson_reminders(self) -> None:
        """
        Отправляет адресные предурочные напоминания.

        Three-phase + тиковая мемоизация получателей:
        254 урока ~40 классов => ~40 запросов получателей вместо 254+.
        """
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()

        lessons = await self.repo.get_todays_lessons_for_pre_reminders(
            date_iso=today_iso,
        )

        logger.info(
            "Pre-lesson reminder tick: date=%s, lessons=%d",
            today_iso,
            len(lessons),
        )
        blocked_ids = await self._load_blocked_recipient_ids()

        # Тиковые кеши получателей (фикс N+1).
        recipients_cache: dict[tuple[str, str], list[dict]] = {}
        teacher_cache: dict[str, list[dict]] = {}

        pending: list[PendingSend] = []

        # --- Фаза 1 (collect) ---
        for lesson in lessons:
            try:
                lesson_start_at = datetime.datetime.strptime(
                    f"{today_iso} {lesson['start_time']}",
                    "%Y-%m-%d %H:%M",
                ).replace(tzinfo=self.time_service.base_tz)
                delta_minutes = (
                    lesson_start_at - now
                ).total_seconds() / 60.0

                # Урок уже начался или прошёл.
                if delta_minutes <= 0:
                    continue

                cache_key = (lesson["class_id"], lesson["group_id"])
                if cache_key not in recipients_cache:
                    recipients_cache[cache_key] = (
                        await self.repo.get_recipients_for_pre_lesson_reminder(
                            class_id=lesson["class_id"],
                            group_id=lesson["group_id"],
                        )
                    )
                recipients = recipients_cache[cache_key]

                for recipient in recipients:
                    recipient_id = int(recipient["recipient_id"])
                    if recipient_id in blocked_ids:
                        continue
                    offset_minutes = int(recipient["offset_minutes"])

                    # 0 = получатель отключил этот тип напоминаний.
                    if offset_minutes <= 0:
                        continue

                    # До окна уведомления ещё далеко.
                    if delta_minutes > offset_minutes:
                        continue

                    dto = LessonReminderDTO(
                        subject_name=lesson["subject_name"] or "—",
                        start_time=lesson["start_time"],
                        room_name=lesson["room_name"] or "—",
                        is_extra=False,
                        child_name=(
                            recipient["child_name"]
                            if recipient["recipient_kind"] == "adult"
                            else None
                        ),
                    )

                    pending.append(
                        PendingSend(
                            notification_type="pre_lesson",
                            notification_date=today_iso,
                            source_id=lesson["id"],
                            recipient_id=recipient_id,
                            text=UIRenderer.render_lesson_reminder(dto),
                            context=(
                                f"lesson_id={lesson['id']}, "
                                f"kind={recipient['recipient_kind']}"
                            ),
                        )
                    )

                teacher_id = lesson.get("teacher_id")
                if not teacher_id:
                    continue

                teacher_id = str(teacher_id)
                if teacher_id not in teacher_cache:
                    teacher_cache[teacher_id] = (
                        await self.repo.get_teacher_recipients_for_pre_lesson_reminder(
                            teacher_id=teacher_id,
                        )
                    )

                for recipient in teacher_cache[teacher_id]:
                    try:
                        recipient_id = int(recipient["recipient_id"])
                        if recipient_id in blocked_ids:
                            continue
                        offset_minutes = int(recipient["offset_minutes"])

                        if offset_minutes <= 0:
                            continue

                        if delta_minutes > offset_minutes:
                            continue

                        dto = LessonReminderDTO(
                            subject_name=lesson["subject_name"] or "—",
                            start_time=lesson["start_time"],
                            room_name=lesson["room_name"] or "—",
                            is_extra=False,
                            child_name=None,
                        )
                        text = (
                            "👨‍🏫 <b>Напоминание об уроке</b>\n\n"
                            f"{UIRenderer.render_lesson_reminder(dto)}"
                        )

                        pending.append(
                            PendingSend(
                                notification_type="teacher_pre_lesson",
                                notification_date=today_iso,
                                source_id=lesson["id"],
                                recipient_id=recipient_id,
                                text=text,
                                context=(
                                    f"teacher_id={teacher_id}, "
                                    f"lesson_id={lesson['id']}"
                                ),
                            )
                        )
                    except Exception:
                        logger.exception(
                            "Teacher pre-lesson collect failed: "
                            "lesson=%r recipient=%r",
                            lesson,
                            recipient,
                        )

            except (KeyError, TypeError, ValueError) as exc:
                logger.exception(
                    "Invalid pre-lesson reminder task: lesson=%r, error=%s",
                    lesson,
                    exc,
                )
            except Exception:
                logger.exception(
                    "Unexpected pre-lesson reminder collect error: lesson=%r",
                    lesson,
                )

        # --- Фаза 2 (dedup) + Фаза 3 (send) ---
        to_send = await self._drop_already_delivered(pending)
        sent_count, failed_count = await self._flush_pending(to_send)

        logger.info(
            "Pre-lesson tick done: lessons=%d, candidates=%d, "
            "pending=%d, sent=%d, failed=%d, "
            "recipient_queries=%d, teacher_queries=%d",
            len(lessons),
            len(pending),
            len(to_send),
            sent_count,
            failed_count,
            len(recipients_cache),
            len(teacher_cache),
        )

    # ==============================================================
    # 4. Напоминания о доп. занятиях
    # ==============================================================

    async def send_extra_class_reminders(self) -> None:
        """
        Отправляет адресные напоминания о дополнительных занятиях.

        Получатели уже приходят адресно из репозитория — фаза collect
        только применяет временные фильтры.
        """
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()
        weekday = now.isoweekday()

        extras = await self.repo.get_todays_extra_classes_for_reminders(
            day_of_week=weekday,
        )

        logger.info(
            "Extra reminder tick: date=%s, weekday=%s, candidates=%d",
            today_iso,
            weekday,
            len(extras),
        )
        blocked_ids = await self._load_blocked_recipient_ids()
        pending: list[PendingSend] = []

        # --- Фаза 1 (collect) ---
        for extra in extras:
            try:
                extra_id = int(extra["extra_id"])
                recipient_id = int(extra["recipient_id"])
                if recipient_id in blocked_ids:
                    continue
                offset_minutes = int(extra["offset_minutes"])

                if offset_minutes <= 0:
                    logger.debug(
                        "Extra reminder disabled by zero offset: extra_id=%s, "
                        "recipient_id=%s",
                        extra_id,
                        recipient_id,
                    )
                    continue

                start_at = datetime.datetime.strptime(
                    f"{today_iso} {extra['time_start']}",
                    "%Y-%m-%d %H:%M",
                ).replace(tzinfo=self.time_service.base_tz)
                delta_minutes = (
                    start_at - now
                ).total_seconds() / 60.0

                # Занятие уже началось.
                if delta_minutes <= 0:
                    continue

                # Ещё не вошли в окно напоминания.
                if delta_minutes > offset_minutes:
                    continue

                dto = LessonReminderDTO(
                    subject_name=extra["title"],
                    start_time=extra["time_start"],
                    room_name=extra["location"] or "—",
                    is_extra=True,
                    child_name=(
                        extra["child_name"]
                        if extra["recipient_kind"] == "adult"
                        else None
                    ),
                )

                pending.append(
                    PendingSend(
                        notification_type="extra_class",
                        notification_date=today_iso,
                        source_id=str(extra_id),
                        recipient_id=recipient_id,
                        text=UIRenderer.render_lesson_reminder(dto),
                        context=(
                            f"extra_id={extra_id}, "
                            f"kind={extra['recipient_kind']}"
                        ),
                    )
                )

            except (KeyError, TypeError, ValueError) as exc:
                logger.exception(
                    "Invalid extra reminder task: task=%r, error=%s",
                    extra,
                    exc,
                )
            except Exception:
                logger.exception(
                    "Unexpected extra reminder collect error: task=%r",
                    extra,
                )

        # --- Фаза 2 (dedup) + Фаза 3 (send) ---
        to_send = await self._drop_already_delivered(pending)
        sent_count, failed_count = await self._flush_pending(to_send)

        logger.info(
            "Extra reminder tick done: candidates=%d, pending=%d, "
            "sent=%d, failed=%d",
            len(pending),
            len(to_send),
            sent_count,
            failed_count,
        )

    # ==============================================================
    # Утренние сводки учителей
    # ==============================================================

    async def _send_teacher_morning_reminders(
        self,
        *,
        current_time_str: str,
        today_iso: str,
    ) -> None:
        """
        Отправляет утренние сводки зарегистрированным учителям.

        Teacher summary состоит только из lesson records:
        extra classes student profiles сюда не подмешиваются.

        ИСПРАВЛЕНО (Этап 2): метод существовал, но не вызывался.
        Теперь вызывается из send_morning_reminders каждый тик.
        """
        tasks = await self.repo.get_teacher_morning_summary_tasks(
            time_str=current_time_str,
        )
        blocked_ids = await self._load_blocked_recipient_ids()
        if blocked_ids:
            tasks = [
                task
                for task in tasks
                if int(task["recipient_id"]) not in blocked_ids
            ]
            
        if not tasks:
            return

        # --- Фаза 1 (dedup): батчевая проверка delivery log ---
        candidate_keys = [
            (
                today_iso,
                f"teacher_morning:{str(task['teacher_id'])}",
                int(task["recipient_id"]),
            )
            for task in tasks
        ]
        delivered = await self.repo.get_delivered_keys(
            notification_type="teacher_morning",
            candidate_keys=candidate_keys,
        )

        metadata = await self.schedule_repo.get_metadata()
        classes = metadata.get("classes", {})

        sent_count = 0
        failed_count = 0

        for task in tasks:
            try:
                recipient_id = int(task["recipient_id"])
                teacher_id = str(task["teacher_id"])
                teacher_name = task.get("teacher_name") or "Учитель"
                source_id = f"teacher_morning:{teacher_id}"

                if (today_iso, source_id, recipient_id) in delivered:
                    continue

                raw_lessons = (
                    await self.schedule_repo.get_lessons_for_teacher(
                        teacher_id=teacher_id,
                        date_iso=today_iso,
                    )
                )

                lessons_dtos: list[MorningLessonDTO] = []
                for lesson in raw_lessons:
                    class_id = lesson.get("class_id")
                    class_obj = classes.get(class_id)
                    class_name = (
                        getattr(class_obj, "name", class_obj)
                        if class_obj is not None
                        else class_id
                    )
                    room_name = lesson.get("room_name") or "—"
                    if class_name:
                        room_name = (
                            f"{room_name} · {class_name}"
                        )
                    lessons_dtos.append(
                        MorningLessonDTO(
                            lesson_num=lesson.get("lesson_num"),
                            start_time=lesson.get("start_time") or "—",
                            end_time=lesson.get("end_time") or "—",
                            subject_name=(
                                lesson.get("subject_name") or "—"
                            ),
                            room_name=room_name,
                            is_cancelled=bool(
                                lesson.get("is_cancelled")
                            ),
                            is_exchange=bool(
                                lesson.get("is_exchange")
                            ),
                            is_extra=False,
                            group_name=None,
                        )
                    )

                if not lessons_dtos:
                    continue

                lessons_dtos.sort(
                    key=lambda item: (
                        item.start_time,
                        (
                            item.lesson_num
                            if item.lesson_num is not None
                            else 99
                        ),
                    )
                )

                summary_dto = MorningSummaryDTO(
                    date_iso=today_iso,
                    lessons=lessons_dtos,
                    child_name=None,
                    class_id=None,
                )

                text = (
                    "👨‍🏫 <b>Расписание учителя</b>\n"
                    f"👤 <b>{UIRenderer.escape_html(teacher_name)}</b>\n\n"
                    f"{UIRenderer.render_morning_summary(summary_dto)}"
                )

                sent = await self._paced_send(
                    chat_id=recipient_id,
                    text=text,
                )
                if not sent:
                    failed_count += 1
                    continue

                sent_count += 1
                await self.repo.record_notification_delivery(
                    notification_type="teacher_morning",
                    notification_date=today_iso,
                    source_id=source_id,
                    recipient_id=recipient_id,
                )
                logger.info(
                    "Teacher morning summary delivered: "
                    "teacher_id=%s recipient_id=%s",
                    teacher_id,
                    recipient_id,
                )
            except Exception:
                logger.exception(
                    "Teacher morning summary failed: task=%r",
                    task,
                )

        if sent_count or failed_count:
            logger.info(
                "Teacher morning summary tick done: tasks=%d, "
                "sent=%d, failed=%d",
                len(tasks),
                sent_count,
                failed_count,
            )
