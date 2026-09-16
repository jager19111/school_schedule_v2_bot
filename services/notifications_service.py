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
from typing import Optional, Any, Mapping
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from aiogram.types import InlineKeyboardMarkup
from bot import callbacks
from bot.keyboards.keyboard import Keyboards


from core.repository.notification_repository import NotificationRepository
from services.extra_classes_service import ExtraClassesService
from core.repository.schedule_repository import ScheduleRepository
from services.schedule_service import ScheduleService
from services.time_service import TimeService
from bot.utils.ui_renderer import UIRenderer

from core.models.dto import (
    LessonReminderDTO,
    ChangeReminderDTO,
    MorningSummaryDTO,
    PendingChangeDTO,
    MorningLessonDTO,
    ExtraClassItemDTO,
    DebugBurstResultDTO,
    MorningSummaryTaskDTO,
    TeacherMorningTaskDTO,
    PreLessonRecipientDTO,
    TeacherPreLessonRecipientDTO,
    ScheduleChangeRecipientDTO,
    TeacherChangeRecipientDTO,
    ExtraClassReminderTaskDTO,
    NotificationSendDTO, 
    DeliveredKeyDTO
)
from core.models.domain import LessonInstance
from core.mappers.notification_mapper import NotificationMapper

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
        extra_classes_service: ExtraClassesService,
        schedule_service: ScheduleService,
        admin_ids: Optional[list[int]] = None,
    ) -> None:
        self.bot = bot
        self.repo = notification_repo
        self.time_service = time_service
        self.schedule_repo = schedule_repo
        self.extra_classes_service = extra_classes_service
        self.schedule_service = schedule_service

        # Smart Throttling state.
        # Сериализация ВСЕХ отправок через один lock: планировщик
        # запускает несколько jobs, но лимиты Telegram — глобальные.
        self._send_lock = asyncio.Lock()
        self._global_last_send_at = 0.0
        self._chat_last_send_at: dict[int, float] = {}
        self._admin_ids = list(admin_ids or [])
        self._last_admin_alert_at: dict[str, float] = {}
    # ==============================================================
    # Smart Throttling
    # ==============================================================

    async def _paced_send(self, *, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None,) -> bool:
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
                        reply_markup=reply_markup,
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

    # Повтор одинакового алерта не чаще, чем раз в час.
    ADMIN_ALERT_COOLDOWN_SEC = 3600.0
    async def send_admin_alert(
        self,
        *,
        alert_key: str,
        text: str,
        cooldown_sec: float = ADMIN_ALERT_COOLDOWN_SEC,
    ) -> None:
        """
        Дедуплицированный алерт всем админам (ADMIN_IDS).

        Дедупликация по alert_key с cooldown: TLS-деградация длится,
        пока не обновят отпечаток сертификата, поэтому без cooldown
        админ получал бы сообщение каждые NIKA_REFRESH_INTERVAL_MINUTES.
        Отправка идёт через _paced_send — с учётом лимитов Telegram
        и обработкой 429/блокировок.
        """
        if not self._admin_ids:
            return

        now_mono = time.monotonic()
        last_sent_at = self._last_admin_alert_at.get(alert_key)
        if (
            last_sent_at is not None
            and now_mono - last_sent_at < cooldown_sec
        ):
            return
        self._last_admin_alert_at[alert_key] = now_mono

        for admin_id in self._admin_ids:
            sent = await self._paced_send(
                chat_id=admin_id,
                text=text,
            )
            if not sent:
                logger.warning(
                    "Admin alert not delivered: admin_id=%s, key=%s",
                    admin_id,
                    alert_key,
                )


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

    async def debug_send_burst(self, *, chat_id: int, count: int) -> DebugBurstResultDTO:
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
            NotificationSendDTO(
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

        return DebugBurstResultDTO(
            requested=len(pending),
            pending=len(to_send),
            sent=sent_count,
            failed=failed_count,
        )

    # ==============================================================
    # Общие помощники фаз collect/dedup/send
    # ==============================================================

    async def _drop_already_delivered(
        self,
        pending: list[NotificationSendDTO],
    ) -> list[NotificationSendDTO]:
        """
        Фаза dedup: батчевая проверка delivery log по каждому типу.

        Один вызов get_delivered_keys на каждый notification_type,
        встречающийся в pending, независимо от числа кандидатов.
        """
        if not pending:
            return []

        result: list[NotificationSendDTO] = []
        types = sorted({item.notification_type for item in pending})

        for notification_type in types:
            type_items = [
                item for item in pending if item.notification_type == notification_type
            ]
            candidate_keys = [
                DeliveredKeyDTO(
                    notification_date=item.notification_date,
                    source_id=item.source_id,
                    recipient_id=item.recipient_id,
                )
                for item in type_items
            ]
            delivered = await self.repo.get_delivered_keys(
                notification_type=notification_type,
                candidate_keys=candidate_keys,
            )
            for item in type_items:
                key = DeliveredKeyDTO(
                    notification_date=item.notification_date,
                    source_id=item.source_id,
                    recipient_id=item.recipient_id,
                )
                if key not in delivered:
                    result.append(item)

        return result

    async def _flush_pending(
        self,
        pending: list[NotificationSendDTO],
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
                if task.recipient_id not in blocked_ids
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
            DeliveredKeyDTO(
                notification_date=today_iso,
                source_id=f"morning_summary:{task.target_student_id}",
                recipient_id=task.recipient_id,
            )
            for task in tasks
        ]
        delivered = await self.repo.get_delivered_keys(
            notification_type="morning_summary",
            candidate_keys=candidate_keys,
        )

        metadata = await self.schedule_repo.get_metadata()

        classes = metadata.classes
        groups = metadata.groups

        # ИСПРАВЛЕНИЕ ТИПА: Больше никаких dict[str, Any]
        summaries_by_recipient: dict[
            int,
            list[tuple[MorningSummaryTaskDTO, MorningSummaryDTO]],
        ] = {}
        display_numbers_cache: dict[
            tuple[str, str],
            dict[int, str],
        ] = {}
        
        for task in tasks:
            try:
                # ИСПРАВЛЕНИЕ: Вызовы через точку к DTO
                recipient_id = task.recipient_id
                target_student_id = task.target_student_id
                source_id = f"morning_summary:{target_student_id}"

                if DeliveredKeyDTO(
                    notification_date=today_iso,
                    source_id=source_id,
                    recipient_id=recipient_id
                ) in delivered:
                    continue

                child_class_id = task.class_id
                child_group_id = task.group_id or "ALL"

                lessons_dtos: list[MorningLessonDTO] = []

                if child_class_id:
                    lessons = (
                        await self.schedule_repo.get_lessons_for_class(
                            class_id=child_class_id,
                            date_iso=today_iso,
                        )
                    )
                    day_permutation = self.schedule_service.detect_day_permutation(
                        lessons
                    )
                    display_key = (
                        child_class_id,
                        today_iso,
                    )

                    if display_key not in display_numbers_cache:
                        display_numbers_cache[display_key] = (
                            await self.schedule_service
                            .get_display_numbers_for_class_day(
                                class_id=child_class_id,
                                date_iso=today_iso,
                            )
                        )

                    display_numbers = display_numbers_cache[
                        display_key
                    ]

                    user_groups = (
                        child_group_id.split(",")
                        if child_group_id != "ALL"
                        else ["ALL"]
                    )

                    for lesson in lessons:
                        lesson_group_id = lesson.group_id or "ALL"

                        if (
                            "ALL" not in user_groups
                            and lesson_group_id != "ALL"
                            and lesson_group_id not in user_groups
                        ):
                            continue

                        group_name = None

                        if lesson_group_id != "ALL":
                            group_name = groups.get(
                                lesson_group_id,
                                f"Группа {lesson_group_id}",
                            )

                        lesson_display_num = display_numbers.get(
                            lesson.lesson_num,
                            (
                                str(lesson.lesson_num)
                                if lesson.lesson_num is not None
                                else "•"
                            ),
                        )

                        lessons_dtos.append(
                            NotificationMapper.map_school_lesson_to_morning_dto(
                                lesson,
                                display_num=lesson_display_num,
                                group_name=group_name,
                                day_permutation=day_permutation,
                            )
                        )

                if target_student_id is not None:
                    extra_items = (
                        await self.extra_classes_service
                        .get_extra_classes_for_student(
                            student_id=target_student_id,
                            day_of_week=weekday,
                        )
                    )

                    lessons_dtos.extend(
                        NotificationMapper.map_extra_to_morning_dto(extra)
                        for extra in extra_items
                    )

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
                        item.start_time or "99:99",
                        item.lesson_num
                        if item.lesson_num is not None
                        else 99,
                    )
                )

                class_name = child_class_id

                if child_class_id:
                    class_obj = classes.get(child_class_id)
                    if class_obj is not None:
                        class_name = class_obj.name

                summary_dto = MorningSummaryDTO(
                    date_iso=today_iso,
                    lessons=lessons_dtos,
                    child_name=(
                        task.child_name
                        if task.recipient_kind == "adult"
                        else None
                    ),
                    class_id=child_class_id,
                    class_name=class_name,
                    has_permutation=day_permutation,
                    origin="student",
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
            for task, summary_dto in entries:
                try:
                    text = UIRenderer.render_morning_summary(
                        summary_dto,
                    )

                    has_changes = any(
                        lesson.is_exchange or lesson.is_cancelled
                        for lesson in summary_dto.lessons
                        if not lesson.is_extra
                    )

                    keyboard = None

                    if has_changes:
                        changes_data = callbacks.DayChangesCD(
                            target_kind="student",
                            target_id=task.target_student_id,
                            class_id=str(task.class_id),
                            group_id=str(
                                task.group_id or "ALL"
                            ),
                            date_iso=today_iso,
                            origin="class",
                            return_to="morning",
                        )

                        keyboard = (
                            Keyboards.get_day_changes_kb(
                                changes_data,
                            )
                        )

                    sent = await self._paced_send(
                        chat_id=recipient_id,
                        text=text,
                        reply_markup=keyboard,
                    )

                    if not sent:
                        failed_count += 1
                        logger.warning(
                            "Morning summary send failed: "
                            "recipient_id=%s student_id=%s",
                            recipient_id,
                            task.target_student_id,
                        )
                        continue

                    sent_count += 1

                    await self.repo.record_notification_delivery(
                        notification_type="morning_summary",
                        notification_date=today_iso,
                        source_id=(
                            f"morning_summary:{task.target_student_id}"
                        ),
                        recipient_id=recipient_id,
                    )

                    logger.info(
                        "Morning summary delivered: "
                        "recipient_id=%s student_id=%s",
                        recipient_id,
                        task.target_student_id,
                    )

                except Exception:
                    failed_count += 1
                    logger.exception(
                        "Morning summary sending error: "
                        "recipient_id=%s task=%r",
                        recipient_id,
                        task,
                    )

        logger.info(
            "Morning summary tick done: tasks=%d, pending_recipients=%d, "
            "sent=%d, failed=%d",
            len(tasks),
            len(summaries_by_recipient),
            sent_count,
            failed_count,
        )

        # Учительские утренние сводки
        await self._send_teacher_morning_reminders(
            current_time_str=current_time_str,
            today_iso=today_iso,
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
        """
        tasks = await self.repo.get_teacher_morning_summary_tasks(
            time_str=current_time_str,
        )
        blocked_ids = await self._load_blocked_recipient_ids()
        if blocked_ids:
            tasks = [
                task
                for task in tasks
                if task.recipient_id not in blocked_ids
            ]
            
        if not tasks:
            return

        # --- Фаза 1 (dedup): батчевая проверка delivery log ---
        candidate_keys = [
            DeliveredKeyDTO(
                notification_date=today_iso,
                source_id=f"teacher_morning:{task.teacher_id}",
                recipient_id=task.recipient_id,
            )
            for task in tasks
        ]
        delivered = await self.repo.get_delivered_keys(
            notification_type="teacher_morning",
            candidate_keys=candidate_keys,
        )

        metadata = await self.schedule_repo.get_metadata()
        classes = metadata.classes
        
        sent_count = 0
        failed_count = 0

        for task in tasks:
            try:
                recipient_id = task.recipient_id
                teacher_id = task.teacher_id
                teacher_name = task.teacher_name or "Учитель"
                source_id = f"teacher_morning:{teacher_id}"

                if DeliveredKeyDTO(
                    notification_date=today_iso,
                    source_id=source_id,
                    recipient_id=recipient_id
                ) in delivered:
                    continue

                lessons = (
                    await self.schedule_repo.get_lessons_for_teacher(
                        teacher_id=teacher_id,
                        date_iso=today_iso,
                    )
                )

                lessons_dtos: list[MorningLessonDTO] = []

                for lesson in lessons:
                    class_name = lesson.class_name

                    if not class_name and lesson.class_id:
                        class_obj = classes.get(lesson.class_id)
                        class_name = (
                            class_obj.name
                            if class_obj is not None
                            else lesson.class_id
                        )

                    lessons_dtos.append(
                        NotificationMapper.map_school_lesson_to_morning_dto(
                            lesson,
                            display_num=(str(lesson.lesson_num) if lesson.lesson_num is not None else "•"),
                            class_name=class_name,
                            day_permutation=False,
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
                    class_name=None,
                    teacher_name=teacher_name,
                    has_permutation=False,
                    origin="teacher",
                )

                text = UIRenderer.render_morning_summary(summary_dto)

                has_changes = any(
                    lesson.is_exchange or lesson.is_cancelled
                    for lesson in summary_dto.lessons
                    if not lesson.is_extra
                )
                keyboard = None

                if has_changes:
                    changes_data = callbacks.DayChangesCD(
                        target_kind="teacher",
                        target_id=teacher_id,
                        class_id="ALL",
                        group_id="ALL",
                        date_iso=today_iso,
                        origin="teacher",
                        return_to="morning",
                    )

                    keyboard = Keyboards.get_day_changes_kb(
                        changes_data,
                    )
                    
                sent = await self._paced_send(
                    chat_id=recipient_id,
                    text=text,
                    reply_markup=keyboard,
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

    # ==============================================================
    # 2. Изменения расписания
    # ==============================================================
    
    @staticmethod
    def _to_change_reminder_dto(
        change: PendingChangeDTO,
        *,
        child_name: str | None = None,
        watch_target_title: str | None = None,
        display_num: str | None = None,
    ) -> ChangeReminderDTO:
        return ChangeReminderDTO(
            date=change.date,
            lesson_num=change.lesson_num,
            display_num=(
                display_num
                if display_num is not None
                else change.display_num
            ),
            subject_name=change.subject_name or "—",
            is_cancelled=change.is_cancelled,
            original_subject_name=change.original_subject_name,
            new_subject_name=change.subject_name,
            original_room_name=change.original_room_name,
            new_room_name=change.room_name,
            original_group_name=change.original_group_name,
            new_group_name=change.group_name,
            group_changed=(
                bool(change.original_group_id)
                and change.original_group_id != change.group_id
            ),
            child_name=child_name,
            watch_target_title=watch_target_title,
        )

    async def send_upcoming_changes(self) -> None:
        """
        Отправляет адресные уведомления о заменах и отменах.
        """
        now = self.time_service.get_now_base()
        today = now.date()
        today_iso = today.isoformat()

        window_end_iso = (
            today + datetime.timedelta(days=MAX_CHANGES_WINDOW_DAYS)
        ).isoformat()

        # Репозиторий теперь возвращает список готовых PendingChangeDTO
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
        
        recipients_cache: dict[tuple[str, str], list[ScheduleChangeRecipientDTO]] = {}
        teacher_cache: dict[str, list[TeacherChangeRecipientDTO]] = {}
        display_numbers_cache: dict[tuple[str, str],dict[int, str],] = {}
        pending: list[NotificationSendDTO] = []

        # --- Фаза 1 (collect) ---
        for change in changes:
            try:
                change_date = self.time_service.date_from_iso(
                    change.date,
                )
                class_display_num = str(change.lesson_num)

                try:
                    display_key = (
                        change.class_id,
                        change.date,
                    )

                    if display_key not in display_numbers_cache:
                        display_numbers_cache[display_key] = (
                            await self.schedule_service
                            .get_display_numbers_for_class_day(
                                class_id=change.class_id,
                                date_iso=change.date,
                            )
                        )

                    class_display_num = display_numbers_cache[
                        display_key
                    ].get(
                        change.lesson_num,
                        str(change.lesson_num),
                    )
                except Exception:
                    logger.exception(
                        "Failed to calculate display number: "
                        "class_id=%s date=%s lesson_num=%s",
                        change.class_id,
                        change.date,
                        change.lesson_num,
                    )

                cache_key = (
                    change.class_id,
                    change.group_id,
                )

                if cache_key not in recipients_cache:
                    recipients_cache[cache_key] = (
                        await self.repo.get_recipients_for_schedule_change(
                            class_id=change.class_id,
                            group_id=change.group_id,
                        )
                    )

                recipients = recipients_cache[cache_key]

                for recipient in recipients:
                    recipient_id = recipient.recipient_id

                    if recipient_id in blocked_ids:
                        continue

                    window_days = recipient.changes_window_days

                    if window_days <= 0:
                        continue

                    max_date = today + datetime.timedelta(
                        days=window_days,
                    )

                    if not (today <= change_date <= max_date):
                        continue

                    dto = NotificationMapper.to_change_reminder_dto(
                        change,
                        display_num=class_display_num,
                        child_name=(recipient.child_name if recipient.recipient_kind == "adult" else None),
                        watch_target_title=(recipient.watch_target_title if recipient.recipient_kind == "watch" else None),
                    )
                    pending.append(
                        NotificationSendDTO(
                            notification_type="schedule_change",
                            notification_date=change.date,
                            source_id=change.id,
                            recipient_id=recipient_id,
                            text=UIRenderer.render_change_reminder(dto),
                            context=(
                                f"change_id={change.id}, "
                                f"kind={recipient.recipient_kind}"
                            ),
                        )
                    )

                teacher_id = change.teacher_id

                if not teacher_id:
                    continue

                if teacher_id not in teacher_cache:
                    teacher_cache[teacher_id] = (
                        await self.repo.get_teacher_recipients_for_schedule_change(
                            teacher_id=teacher_id,
                        )
                    )

                for recipient in teacher_cache[teacher_id]:
                    try:
                        recipient_id = recipient.recipient_id
                        if recipient_id in blocked_ids:
                            continue
                            
                        window_days = recipient.changes_window_days
                        if window_days <= 0:
                            continue

                        max_date = today + datetime.timedelta(
                            days=window_days,
                        )
                        if not (today <= change_date <= max_date):
                            continue

                        dto = NotificationMapper.to_change_reminder_dto(
                            change,
                            display_num=str(change.lesson_num),
                        )

                        teacher_name = change.teacher_name or "Учитель"

                        text = (
                            "👨‍🏫 <b>Изменение в расписании учителя</b>\n"
                            f"👤 <b>{UIRenderer.escape_html(teacher_name)}</b>\n\n"
                            f"{UIRenderer.render_change_reminder(dto)}"
                        )

                        pending.append(
                            NotificationSendDTO(
                                notification_type="teacher_change",
                                notification_date=change.date,
                                source_id=change.id,
                                recipient_id=recipient_id,
                                text=text,
                                context=(
                                    f"teacher_id={teacher_id}, "
                                    f"change_id={change.id}"
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
        Включает рассылку ученикам, родителям и учителям.
        """
        now = self.time_service.get_now_base()
        today_iso = now.date().isoformat()

        # Получаем DTO, а не словари
        lessons = await self.repo.get_todays_lessons_for_pre_reminders(
            date_iso=today_iso,
        )

        logger.info(
            "Pre-lesson reminder tick: date=%s, lessons=%d",
            today_iso,
            len(lessons),
        )
        blocked_ids = await self._load_blocked_recipient_ids()

        recipients_cache: dict[tuple[str, str], list[PreLessonRecipientDTO]] = {}
        teacher_cache: dict[str, list[TeacherPreLessonRecipientDTO]] = {}

        pending: list[NotificationSendDTO] = []

        # --- Фаза 1 (collect) ---
        for lesson in lessons:
            try:
                lesson_start_at = datetime.datetime.strptime(
                    f"{today_iso} {lesson.start_time}",
                    "%Y-%m-%d %H:%M",
                ).replace(tzinfo=self.time_service.base_tz)
                
                delta_minutes = (lesson_start_at - now).total_seconds() / 60.0

                if delta_minutes <= 0:
                    continue

                # 1. ВЕТКА УЧЕНИКОВ И РОДИТЕЛЕЙ
                cache_key = (lesson.class_id, lesson.group_id or "ALL")
                if cache_key not in recipients_cache:
                    recipients_cache[cache_key] = (
                        await self.repo.get_recipients_for_pre_lesson_reminder(
                            class_id=lesson.class_id,
                            group_id=lesson.group_id or "ALL",
                        )
                    )
                recipients = recipients_cache[cache_key]

                for recipient in recipients:
                    recipient_id = recipient.recipient_id
                    if recipient_id in blocked_ids:
                        continue
                    
                    offset_minutes = recipient.offset_minutes
                    if offset_minutes <= 0 or delta_minutes > offset_minutes:
                        continue

                    dto = LessonReminderDTO(
                        subject_name=lesson.subject_name or "—",
                        start_time=lesson.start_time or "—",
                        room_name=lesson.room_name or "—",
                        is_extra=False,
                        child_name=(
                            recipient.child_name
                            if recipient.recipient_kind == "adult"
                            else None
                        ),
                    )

                    pending.append(
                        NotificationSendDTO(
                            notification_type="pre_lesson",
                            notification_date=today_iso,
                            source_id=lesson.id,
                            recipient_id=recipient_id,
                            text=UIRenderer.render_lesson_reminder(dto),
                            context=f"lesson_id={lesson.id}, kind={recipient.recipient_kind}",
                        )
                    )

                # 2. ВЕТКА УЧИТЕЛЕЙ
                teacher_id = lesson.teacher_id
                if not teacher_id:
                    continue

                # Мемоизация внутри тика, чтобы не дергать БД на каждый урок одного учителя
                if teacher_id not in teacher_cache:
                    teacher_cache[teacher_id] = (
                        await self.repo.get_teacher_recipients_for_pre_lesson_reminder(
                            teacher_id=teacher_id,
                        )
                    )

                for recipient in teacher_cache[teacher_id]:
                    try:
                        recipient_id = recipient.recipient_id
                        if recipient_id in blocked_ids:
                            continue
                            
                        offset_minutes = recipient.offset_minutes
                        if offset_minutes <= 0 or delta_minutes > offset_minutes:
                            continue

                        dto = LessonReminderDTO(
                            subject_name=lesson.subject_name or "—",
                            start_time=lesson.start_time or "—",
                            room_name=lesson.room_name or "—",
                            is_extra=False,
                            child_name=None,
                        )
                        text = (
                            "👨‍🏫 <b>Напоминание об уроке</b>\n\n"
                            f"{UIRenderer.render_lesson_reminder(dto)}"
                        )

                        pending.append(
                            NotificationSendDTO(
                                notification_type="teacher_pre_lesson",
                                notification_date=today_iso,
                                source_id=lesson.id,
                                recipient_id=recipient_id,
                                text=text,
                                context=f"teacher_id={teacher_id}, lesson_id={lesson.id}",
                            )
                        )
                    except Exception:
                        logger.exception(
                            "Teacher pre-lesson collect failed: lesson=%r recipient=%r",
                            lesson,
                            recipient,
                        )

            except (KeyError, TypeError, ValueError) as exc:
                logger.exception("Invalid pre-lesson reminder task: lesson=%r, error=%s", lesson, exc)
            except Exception:
                logger.exception("Unexpected pre-lesson reminder collect error: lesson=%r", lesson)

        # --- Фаза 2 (dedup) + Фаза 3 (send) ---
        # Вся дедупликация и отправка с защитой от лимитов Telegram происходит здесь
        to_send = await self._drop_already_delivered(pending)
        sent_count, failed_count = await self._flush_pending(to_send)

        logger.info(
            "Pre-lesson tick done: lessons=%d, candidates=%d, pending=%d, sent=%d, failed=%d, "
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
        pending: list[NotificationSendDTO] = []

        # --- Фаза 1 (collect) ---
        for extra in extras:
            try:
                extra_id = extra.extra_id
                recipient_id = extra.recipient_id
                
                if recipient_id in blocked_ids:
                    continue
                    
                offset_minutes = extra.offset_minutes

                if offset_minutes <= 0:
                    logger.debug(
                        "Extra reminder disabled by zero offset: extra_id=%s, "
                        "recipient_id=%s",
                        extra_id,
                        recipient_id,
                    )
                    continue

                start_at = datetime.datetime.strptime(
                    f"{today_iso} {extra.time_start}",
                    "%Y-%m-%d %H:%M",
                ).replace(tzinfo=self.time_service.base_tz)
                delta_minutes = (
                    start_at - now
                ).total_seconds() / 60.0

                if delta_minutes <= 0:
                    continue

                if delta_minutes > offset_minutes:
                    continue

                dto = LessonReminderDTO(
                    subject_name=extra.title,
                    start_time=extra.time_start,
                    room_name=extra.location or "—",
                    is_extra=True,
                    child_name=(
                        extra.child_name
                        if extra.recipient_kind == "adult"
                        else None
                    ),
                )

                pending.append(
                    NotificationSendDTO(
                        notification_type="extra_class",
                        notification_date=today_iso,
                        source_id=str(extra_id),
                        recipient_id=recipient_id,
                        text=UIRenderer.render_lesson_reminder(dto),
                        context=(
                            f"extra_id={extra_id}, "
                            f"kind={extra.recipient_kind}"
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