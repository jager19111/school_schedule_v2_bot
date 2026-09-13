# core/repository/schedule_repository.py
#
# ЭТАП 3 (фундамент → репозиторий): синхронизация с расширенным
# LessonInstance (class_name, original_*, is_methodological,
# original_group_*) и хранение расписания УЧИТЕЛЕЙ.
#
# РЕШЁННЫЕ ПРОБЛЕМЫ (наследие Этапов 1-2 сохранено):
#
# 1. Bulk Inserts (Задача 1.2): executemany с одним UPSERT.
#
# 2. Strict Time Governance (Задача 1.3): все временные метки —
#    плейсхолдеры ? со значением now_utc из TimeService.
#
# 3. Транзакции через self.transaction() с общим write-lock.
#
# 4. Shared-соединение SQLite (db_path = aiosqlite.Connection).
#
# НОВОЕ ЭТАПА 3:
#
# 5. Origin-разделение: расписание классов и учителей пишется в
#    одну таблицу schedule_cache с колонкой origin ('class'/'teacher').
#    Запросы по классу фильтруют origin='class', по учителю —
#    origin='teacher'. Без этого class- и teacher-уроки одного слота
#    дублировались бы в выдаче.
#
# 6. Коллизия ID устранена НА УРОВНЕ НОРМАЛИЗАТОРА: учительский
#    lesson_id получает префикс T{teacher_id}_ (см. патч normalizer).
#    Это обязательное условие: формат ID классов и учителей совпадал,
#    и ON CONFLICT(id) молча перезаписывал бы class-уроки teacher-уроками.
#
# 7. Сохраняются ВСЕ поля «было → стало»: original_subject_*,
#    original_teacher_*, original_room_*, original_class_*,
#    original_group_*, а также class_name, weekday, is_methodological.
#
# 8. groups_raw / subjects_raw / rooms_raw в БД НЕ хранятся:
#    параллельные подгруппы восстанавливаются группировкой строк по
#    (date, lesson_num, origin) на уровне сервиса/рендерера. Это
#    избавляет от JSON-блобов в кэше.
#
# 9. Методические часы (M) теперь попадают в кэш через
#    build_teacher_lessons() и видны в расписании учителя.

from __future__ import annotations


import datetime
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


import aiohttp


from core.models.domain import LessonInstance
from core.nika.fetcher import (
    NikaSourceDescriptor,
    ScheduleFetcher,
)
from core.nika.normalizer import NikaNormalizer
from core.repository.base_repository import BaseRepository
from services.time_service import TimeService


logger = logging.getLogger(__name__)


# Единый UPSERT: 32 колонки, включая origin и все original_* (Этап 3).
_SCHEDULE_UPSERT_SQL = """
    INSERT INTO schedule_cache (
        id,
        date,
        period_id,
        class_id,
        origin,
        class_name,
        weekday,
        lesson_num,
        group_id,
        group_name,
        subject_id,
        subject_name,
        teacher_id,
        teacher_name,
        room_id,
        room_name,
        original_subject_id,
        original_subject_name,
        original_teacher_id,
        original_teacher_name,
        original_room_id,
        original_room_name,
        original_class_id,
        original_class_name,
        original_group_id,
        original_group_name,
        start_time,
        end_time,
        is_exchange,
        is_cancelled,
        is_methodological,
        created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        date = excluded.date,
        period_id = excluded.period_id,
        class_id = excluded.class_id,
        origin = excluded.origin,
        class_name = excluded.class_name,
        weekday = excluded.weekday,
        lesson_num = excluded.lesson_num,
        group_id = excluded.group_id,
        group_name = excluded.group_name,
        subject_id = excluded.subject_id,
        subject_name = excluded.subject_name,
        teacher_id = excluded.teacher_id,
        teacher_name = excluded.teacher_name,
        room_id = excluded.room_id,
        room_name = excluded.room_name,
        original_subject_id = excluded.original_subject_id,
        original_subject_name = excluded.original_subject_name,
        original_teacher_id = excluded.original_teacher_id,
        original_teacher_name = excluded.original_teacher_name,
        original_room_id = excluded.original_room_id,
        original_room_name = excluded.original_room_name,
        original_class_id = excluded.original_class_id,
        original_class_name = excluded.original_class_name,
        original_group_id = excluded.original_group_id,
        original_group_name = excluded.original_group_name,
        start_time = excluded.start_time,
        end_time = excluded.end_time,
        is_exchange = excluded.is_exchange,
        is_cancelled = excluded.is_cancelled,
        is_methodological = excluded.is_methodological,
        created_at = excluded.created_at
"""


@dataclass(frozen=True)
class ScheduleRefreshResult:
    """
    Результат одной попытки синхронизации NIKA.
    """
    source_changed: bool
    schedule_changed: bool
    js_filename: Optional[str] = None
    lesson_count: int = 0
    reason: str = ""


class ScheduleRepository(BaseRepository):
    """
    Репозиторий школьного расписания.


    Основные правила:
    - HTML schedule.html проверяется часто;
    - JS NIKA скачивается только при новом js_filename;
    - schedule_cache пересобирается только при semantic change NIKA
      или при расширении rolling coverage;
    - raw_nika_cache хранит только одну актуальную версию;
    - schedule_cache хранит ограниченный горизонт дат;
    - class- и teacher-уроки живут в одной таблице, разделены origin.
    """


    def __init__(
        self,
        *,
        db_path,
        time_service: TimeService,
        http_session: aiohttp.ClientSession,
        tls_fingerprint_sha256: str | None = None,
        proxy: str | None = None,
        nika_base_url: str = "https://lyceum.nstu.ru/rasp",
        history_days: int = 7,
    ) -> None:
        super().__init__(
            db_path=db_path,
            time_service=time_service,
        )
        self.fetcher = ScheduleFetcher(
            session=http_session,
            base_url=nika_base_url,
            proxy=proxy,
            tls_fingerprint_sha256=tls_fingerprint_sha256,
        )
        self.history_days = history_days


    def is_ssl_degraded(self) -> bool:
        """
        True, если NIKA-фетчер работает в обход TLS-проверки.

        Используется main.refresh_schedule_cache для админ-алерта.
        Состояние обновляется фетчером при каждой попытке запроса.
        """
        return self.fetcher.ssl_degraded


    # ==========================================================
    # Row <-> LessonInstance mapping (Этап 3)
    # ==========================================================


    @staticmethod
    def _lesson_to_row(
        lesson: LessonInstance,
        origin: str,
        now_utc: str,
    ) -> tuple:
        """
        LessonInstance → кортеж для executemany (32 значения).

        origin: 'class' | 'teacher'. Сам LessonInstance про origin не
        знает — это характеристика источника записи, а не урока.
        """
        return (
            lesson.id,
            lesson.date,
            lesson.period_id,
            lesson.class_id,
            origin,
            lesson.class_name,
            lesson.weekday,
            lesson.lesson_num,
            lesson.group_id,
            lesson.group_name,
            lesson.subject_id,
            lesson.subject_name,
            lesson.teacher_id,
            lesson.teacher_name,
            lesson.room_id,
            lesson.room_name,
            lesson.original_subject_id,
            lesson.original_subject_name,
            lesson.original_teacher_id,
            lesson.original_teacher_name,
            lesson.original_room_id,
            lesson.original_room_name,
            lesson.original_class_id,
            lesson.original_class_name,
            lesson.original_group_id,
            lesson.original_group_name,
            lesson.start_time,
            lesson.end_time,
            int(lesson.is_exchange),
            int(lesson.is_cancelled),
            int(lesson.is_methodological),
            now_utc,
        )


    @staticmethod
    def _row_to_lesson(row: Dict[str, Any]) -> LessonInstance:
        """
        Строка schedule_cache → LessonInstance (DTO для сервиса/рендерера).

        weekday восстанавливается из даты, если колонка пуста
        (строки, оставшиеся до применения миграции).
        """
        weekday = row.get("weekday")
        if not weekday:
            weekday = datetime.date.fromisoformat(
                row["date"]
            ).isoweekday()

        return LessonInstance(
            id=row["id"],
            period_id=row["period_id"],
            class_id=row["class_id"],
            class_name=row.get("class_name"),
            date=row["date"],
            weekday=weekday,
            lesson_num=row["lesson_num"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            subject_id=row.get("subject_id"),
            subject_name=row.get("subject_name"),
            teacher_id=row.get("teacher_id"),
            teacher_name=row.get("teacher_name"),
            room_id=row.get("room_id"),
            room_name=row.get("room_name"),
            original_subject_id=row.get("original_subject_id"),
            original_subject_name=row.get("original_subject_name"),
            original_teacher_id=row.get("original_teacher_id"),
            original_teacher_name=row.get("original_teacher_name"),
            original_room_id=row.get("original_room_id"),
            original_room_name=row.get("original_room_name"),
            original_class_id=row.get("original_class_id"),
            original_class_name=row.get("original_class_name"),
            original_group_id=row.get("original_group_id"),
            original_group_name=row.get("original_group_name"),
            group_id=row.get("group_id") or "ALL",
            group_name=row.get("group_name") or "Весь класс",
            is_exchange=bool(row.get("is_exchange")),
            is_cancelled=bool(row.get("is_cancelled")),
            is_methodological=bool(row.get("is_methodological")),
        )


    # ==========================================================
    # NIKA source state
    # ==========================================================


    async def get_nika_source_state(
        self,
    ) -> Optional[Dict[str, Any]]:
        return await self._fetch_one(
            """
            SELECT
                id,
                js_filename,
                export_date,
                export_time,
                raw_sha256,
                semantic_sha256,
                last_checked_at,
                last_changed_at,
                coverage_start_date,
                coverage_end_date,
                last_error,
                last_error_at
            FROM nika_source_state
            WHERE id = 1
            """
        )


    async def get_cached_raw_nika(
        self,
    ) -> Optional[Dict[str, Any]]:
        return await self._fetch_one(
            """
            SELECT
                id,
                js_filename,
                raw_sha256,
                fetched_at,
                content
            FROM raw_nika_cache
            WHERE id = 1
            """
        )


    async def touch_nika_checked_at(
        self,
    ) -> None:
        """
        Записывает факт успешной HTML-проверки без изменения revision.
        """
        # Задача 1.3: время передаёт приложение, а не СУБД.
        now_utc = self._now_utc_str()
        await self._execute(
            """
            UPDATE nika_source_state
            SET last_checked_at = ?,
                last_error = NULL,
                last_error_at = NULL
            WHERE id = 1
            """,
            (now_utc,),
        )


    async def record_nika_refresh_error(
        self,
        *,
        error_message: str,
    ) -> None:
        """
        Сохраняет последнюю ошибку обновления NIKA.

        Не создаёт nika_source_state при первом bootstrap failure,
        потому что в этом случае ещё неизвестны обязательные metadata:
        js_filename, raw_sha256 и semantic_sha256.

        Когда успешный snapshot уже существует, ошибка записывается
        в текущую единственную строку id=1.
        """
        normalized_error = (
            error_message.strip()[:1500]
            if error_message
            else "Unknown NIKA refresh error"
        )
        # Задача 1.3: явный таймстемп ошибки из Python.
        now_utc = self._now_utc_str()
        changed = await self._execute(
            """
            UPDATE nika_source_state
            SET last_error = ?,
                last_error_at = ?
            WHERE id = 1
            """,
            (
                normalized_error,
                now_utc,
            ),
        )
        if changed == 0:
            logger.warning(
                "NIKA refresh failed before initial source state exists: %s",
                normalized_error,
            )


    async def clear_nika_refresh_error(
        self,
    ) -> None:
        """
        Очищает last_error после успешного refresh/probe.
        """
        await self._execute(
            """
            UPDATE nika_source_state
            SET last_error = NULL,
                last_error_at = NULL
            WHERE id = 1
            """
        )


    async def get_nika_health_status(
        self,
    ) -> Dict[str, Any]:
        """
        Возвращает сохранённый статус NIKA source и schedule cache.

        Не делает HTTP-запросов.
        Не запускает refresh.
        Безопасен для admin diagnostics.
        """
        # получение текущей даты относительно часового пояса бота ---
        today_iso = self.time_service.get_now_base().date().isoformat()
        state = await self.get_nika_source_state()


        cache_info = await self._fetch_one(
            """
            SELECT
                COUNT(*) AS lesson_count,
                MIN(date) AS first_date,
                MAX(date) AS last_date
            FROM schedule_cache
            """
        )


        lesson_count = int(
            cache_info["lesson_count"]
            if cache_info
            else 0
        )


        first_date = (
            cache_info.get("first_date")
            if cache_info
            else None
        )
        last_date = (
            cache_info.get("last_date")
            if cache_info
            else None
        )


        if state is None:
            return {
                "status": (
                    "cache_empty"
                    if lesson_count == 0
                    else "cache_without_source_state"
                ),
                "lesson_count": lesson_count,
                "coverage_start_date": first_date,
                "coverage_end_date": last_date,
                "today_date": today_iso,
                "coverage_is_current": False,
                "coverage_has_future": False,
                "js_filename": None,
                "export_date": None,
                "export_time": None,
                "last_checked_at": None,
                "last_changed_at": None,
                "last_error": None,
                "last_error_at": None,
            }


        if state.get("last_error"):
            status = (
                "source_error_cache_available"
                if lesson_count > 0
                else "source_error_cache_empty"
            )
        elif lesson_count == 0:
            status = "source_healthy_cache_empty"
        else:
            status = "healthy"


        coverage_end_date = (
            state.get("coverage_end_date")
            or last_date
        )


        coverage_is_current = bool(
            coverage_end_date
            and coverage_end_date >= today_iso
        )


        coverage_has_future = bool(
            coverage_end_date
            and coverage_end_date > today_iso
        )


        return {
            "status": status,
            "lesson_count": lesson_count,
            "coverage_start_date": (
                state.get("coverage_start_date")
                or first_date
            ),
            "coverage_end_date": coverage_end_date,
            "today_date": today_iso,
            "coverage_is_current": coverage_is_current,
            "coverage_has_future": coverage_has_future,
            "js_filename": state.get("js_filename"),
            "export_date": state.get("export_date"),
            "export_time": state.get("export_time"),
            "last_checked_at": state.get("last_checked_at"),
            "last_changed_at": state.get("last_changed_at"),
            "last_error": state.get("last_error"),
            "last_error_at": state.get("last_error_at"),
        }


    @staticmethod
    def _coverage_needs_refresh(
        state: Optional[Dict[str, Any]],
        target_dates: List[datetime.date],
    ) -> bool:
        """
        Проверяет, требуется ли расширение rolling coverage.

        Даже если NIKA revision не изменился, через неделю набор target_dates
        сдвинется, и кэш должен получить новые будущие даты.
        """
        if not target_dates:
            return False
        if state is None:
            return True


        expected_start = min(target_dates).isoformat()
        expected_end = max(target_dates).isoformat()


        return (
            state.get("coverage_start_date") != expected_start
            or state.get("coverage_end_date") != expected_end
        )


    # ==========================================================
    # Public metadata / schedule reads
    # ==========================================================


    async def get_metadata(
        self,
    ) -> Dict[str, Any]:
        """
        Строит metadata из текущего singleton raw NIKA cache.
        """
        raw = await self.get_cached_raw_nika()


        if not raw or not raw.get("content"):
            logger.warning(
                "NIKA raw cache is empty."
            )
            return {
                "classes": {},
                "groups": {},
                "teachers": {},
            }


        try:
            nika_data = self.fetcher._extract_json_from_js(
                raw["content"],
            )
            normalizer = NikaNormalizer(
                nika_data,
            )
            classes, teachers, _, _ = normalizer.build_metadata()


            return {
                "classes": classes,
                "groups": nika_data.get(
                    "CLASSGROUPS",
                    {},
                ),
                "teachers": teachers,
                "class_shift": nika_data.get(
                    "CLASS_SHIFT",
                    {},
                ),
                "second_relative": nika_data.get(
                    "SECOND_RELATIVE",
                    False,
                ),
            }
        except Exception:
            logger.exception(
                "Failed to build NIKA metadata from raw cache."
            )
            return {
                "classes": {},
                "groups": {},
                "teachers": {},
            }


    async def get_lessons_for_class(
        self,
        class_id: str,
        date_iso: str,
    ) -> List[Dict[str, Any]]:
        """
        Расписание класса на дату (только class-origin строки).
        """
        return await self._fetch_all(
            """
            SELECT *
            FROM schedule_cache
            WHERE class_id = ?
              AND date = ?
              AND origin = 'class'
            ORDER BY lesson_num, start_time, id
            """,
            (class_id, date_iso),
        )


    async def get_lessons_for_teacher(
        self,
        teacher_id: str,
        date_iso: str,
    ) -> List[Dict[str, Any]]:
        """
        Расписание учителя на дату (только teacher-origin строки:
        включает методические часы и TEACH_EXCHANGE).
        """
        logger.info(f"Тест SQL: teacher={teacher_id} date={date_iso}")  # ← ДОБАВИТЬ
        return await self._fetch_all(
            """
            SELECT *
            FROM schedule_cache
            WHERE teacher_id = ?
              AND date = ?
              AND origin = 'teacher'
            ORDER BY start_time, lesson_num, id
            """,
            (teacher_id, date_iso),
        )


    async def get_lesson_instances_for_class(
        self,
        class_id: str,
        date_iso: str,
    ) -> List[LessonInstance]:
        """
        Типизированный вариант get_lessons_for_class: строки → DTO.
        Сервис и рендерер работают с LessonInstance, а не со словарями.
        """
        rows = await self.get_lessons_for_class(class_id, date_iso)
        return [self._row_to_lesson(r) for r in rows]


    async def get_lesson_instances_for_teacher(
        self,
        teacher_id: str,
        date_iso: str,
    ) -> List[LessonInstance]:
        """
        Типизированный вариант get_lessons_for_teacher: строки → DTO.
        """
        logger.info(f"Тест Repo: teacher={teacher_id} date={date_iso}")  # ← ДОБАВИТЬ
        rows = await self.get_lessons_for_teacher(teacher_id, date_iso)
        return [self._row_to_lesson(r) for r in rows]



    async def get_day_change_count(
        self,
        date_iso: str,
        origin: str = "class",
    ) -> int:
        """
        Количество изменённых/отменённых уроков за дату.

        Используется для быстрой проверки «есть ли смысл показывать
        кнопку изменений» без выгрузки всего дня.
        """
        row = await self._fetch_one(
            """
            SELECT COUNT(*) AS cnt
            FROM schedule_cache
            WHERE date = ?
              AND origin = ?
              AND (is_exchange = 1 OR is_cancelled = 1)
            """,
            (date_iso, origin),
        )
        return int(row["cnt"]) if row else 0


    # ==========================================================
    # NIKA source updates
    # ==========================================================


    async def refresh_if_changed(
        self,
        target_dates: List[datetime.date],
    ) -> ScheduleRefreshResult:
        """
        Проверяет NIKA и обновляет расписание только при реальной причине.


        Возможные результаты:
        - same_filename:
            HTML указывает на уже известный JS, coverage актуален.
        - coverage_extended:
            JS тот же, но rolling date range изменился.
            Расписание строится из локального raw cache без сетевого JS download.
        - export_changed_semantics_same:
            Имя JS изменилось, но semantic NIKA не изменился.
            Обновляется только revision metadata + raw singleton.
        - schedule_changed:
            Semantic NIKA изменился, расписание пересобрано.
        """
        if not target_dates:
            return ScheduleRefreshResult(
                source_changed=False,
                schedule_changed=False,
                reason="empty_target_dates",
            )


        source = await self.fetcher.probe()


        state = await self.get_nika_source_state()


        coverage_changed = self._coverage_needs_refresh(
            state,
            target_dates,
        )

        # Самый дешёвый нормальный путь:
        # HTML проверен, filename прежний, coverage уже актуален.
        if (
            state is not None
            and state["js_filename"] == source.js_filename
            and not coverage_changed
        ):
            await self.touch_nika_checked_at()
            return ScheduleRefreshResult(
                source_changed=False,
                schedule_changed=False,
                js_filename=source.js_filename,
                reason="same_filename",
            )

        # Filename прежний, но rolling horizon сдвинулся.
        # Используем локальный raw cache без повторной загрузки JS.
        if (
            state is not None
            and state["js_filename"] == source.js_filename
            and coverage_changed
        ):
            raw = await self.get_cached_raw_nika()
            if raw and raw.get("content"):
                return await self._refresh_from_cached_raw(
                    target_dates=target_dates,
                    state=state,
                    raw_content=raw["content"],
                )
            logger.warning(
                "Coverage changed but raw NIKA cache is missing. "
                "Downloading JS again."
            )

        # Новый filename либо нет локального state.
        js_content = await self.fetcher.fetch_js_content(
            source,
        )


        nika_data = self.fetcher._extract_json_from_js(
            js_content,
        )


        raw_sha256 = self.fetcher.calculate_raw_sha256(
            js_content,
        )
        semantic_sha256 = self.fetcher.calculate_semantic_sha256(
            nika_data,
        )


        export_date = nika_data.get("EXPORT_DATE")
        export_time = nika_data.get("EXPORT_TIME")

        # Новый filename, но содержательная часть NIKA не изменилась.
        # Расписание не пишем; обновляем revision и singleton raw cache.
        if (
            state is not None
            and state["semantic_sha256"] == semantic_sha256
            and not coverage_changed
        ):
            await self._update_revision_only(
                source=source,
                js_content=js_content,
                raw_sha256=raw_sha256,
                semantic_sha256=semantic_sha256,
                export_date=export_date,
                export_time=export_time,
            )
            return ScheduleRefreshResult(
                source_changed=True,
                schedule_changed=False,
                js_filename=source.js_filename,
                reason="export_changed_semantics_same",
            )

        # Новый semantic NIKA либо первый bootstrap.
        return await self._apply_new_nika_version(
            source=source,
            js_content=js_content,
            nika_data=nika_data,
            raw_sha256=raw_sha256,
            semantic_sha256=semantic_sha256,
            export_date=export_date,
            export_time=export_time,
            target_dates=target_dates,
            source_changed=True,
            schedule_changed=True,
            reason=(
                "initial_bootstrap"
                if state is None
                else "schedule_changed"
            ),
        )


    async def _refresh_from_cached_raw(
        self,
        *,
        target_dates: List[datetime.date],
        state: Dict[str, Any],
        raw_content: str,
    ) -> ScheduleRefreshResult:
        """
        Расширяет rolling coverage из локального raw NIKA cache.

        Это не новое изменение расписания, поэтому schedule_changed=False:
        immediate change notifications запускать не нужно.
        """
        nika_data = self.fetcher._extract_json_from_js(
            raw_content,
        )


        return await self._apply_new_nika_version(
            source=NikaSourceDescriptor(
                js_filename=state["js_filename"],
                js_url="",
            ),
            js_content=raw_content,
            nika_data=nika_data,
            raw_sha256=state["raw_sha256"],
            semantic_sha256=state["semantic_sha256"],
            export_date=state.get("export_date"),
            export_time=state.get("export_time"),
            target_dates=target_dates,
            source_changed=False,
            schedule_changed=False,
            reason="coverage_extended",
        )


    async def _update_revision_only(
        self,
        *,
        source: NikaSourceDescriptor,
        js_content: str,
        raw_sha256: str,
        semantic_sha256: str,
        export_date: Optional[str],
        export_time: Optional[str],
    ) -> None:
        """
        Обновляет revision metadata и singleton raw NIKA cache.
        schedule_cache не трогается: semantic hash не изменился.
        """
        now_utc = self._now_utc_str()


        async with self.transaction() as db:
            await db.execute(
                """
                INSERT INTO raw_nika_cache (
                    id, js_filename, raw_sha256, fetched_at, content
                )
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    js_filename = excluded.js_filename,
                    raw_sha256 = excluded.raw_sha256,
                    fetched_at = excluded.fetched_at,
                    content = excluded.content
                """,
                (
                    source.js_filename,
                    raw_sha256,
                    now_utc,
                    js_content,
                ),
            )


            await db.execute(
                """
                INSERT INTO nika_source_state (
                    id,
                    js_filename,
                    export_date,
                    export_time,
                    raw_sha256,
                    semantic_sha256,
                    last_checked_at,
                    last_changed_at,
                    coverage_start_date,
                    coverage_end_date,
                    last_error,
                    last_error_at
                )
                VALUES (
                    1,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    COALESCE(
                        (SELECT last_changed_at
                         FROM nika_source_state WHERE id = 1),
                        ?
                    ),
                    (SELECT coverage_start_date
                     FROM nika_source_state WHERE id = 1),
                    (SELECT coverage_end_date
                     FROM nika_source_state WHERE id = 1),
                    NULL,
                    NULL
                )
                ON CONFLICT(id) DO UPDATE SET
                    js_filename = excluded.js_filename,
                    export_date = excluded.export_date,
                    export_time = excluded.export_time,
                    raw_sha256 = excluded.raw_sha256,
                    semantic_sha256 = excluded.semantic_sha256,
                    last_checked_at = excluded.last_checked_at,
                    last_changed_at = excluded.last_changed_at,
                    coverage_start_date = excluded.coverage_start_date,
                    coverage_end_date = excluded.coverage_end_date,
                    last_error = NULL,
                    last_error_at = NULL
                """,
                (
                    source.js_filename,
                    export_date,
                    export_time,
                    raw_sha256,
                    semantic_sha256,
                    now_utc,
                    now_utc,
                ),
            )


    async def _apply_new_nika_version(
        self,
        *,
        source: NikaSourceDescriptor,
        js_content: str,
        nika_data: Dict[str, Any],
        raw_sha256: str,
        semantic_sha256: str,
        export_date: Optional[str],
        export_time: Optional[str],
        target_dates: List[datetime.date],
        source_changed: bool,
        schedule_changed: bool,
        reason: str,
    ) -> ScheduleRefreshResult:
        """
        Применяет новый NIKA rolling snapshot атомарно:
        - raw cache (singleton);
        - nika_source_state;
        - schedule_cache (очистка окна + массовый UPSERT);
        - очистка history window.

        Этап 3: строятся ОБА набора — build_class_lessons() и
        build_teacher_lessons() (методические часы, TEACH_EXCHANGE).
        Учительские ID обязаны иметь префикс T{teacher_id}_ (патч
        normalizer), иначе они коллидируют с классовыми.
        """
        normalizer = NikaNormalizer(
            nika_data,
        )


        class_lessons: List[LessonInstance] = (
            normalizer.build_class_lessons(target_dates)
        )
        teacher_lessons: List[LessonInstance] = (
            normalizer.build_teacher_lessons(target_dates)
        )


        target_date_values = sorted(
            {
                target_date.isoformat()
                for target_date in target_dates
            }
        )


        if not target_date_values:
            return ScheduleRefreshResult(
                source_changed=source_changed,
                schedule_changed=False,
                js_filename=source.js_filename,
                lesson_count=0,
                reason="empty_target_dates",
            )


        coverage_start_date = target_date_values[0]
        coverage_end_date = target_date_values[-1]


        history_cutoff = (
            datetime.date.fromisoformat(
                coverage_start_date
            )
            - datetime.timedelta(days=self.history_days)
        ).isoformat()


        placeholders = ",".join(
            "?"
            for _ in target_date_values
        )


        # Единый таймстемп снапшота для всех строк батча.
        now_utc = self._now_utc_str()


        lesson_rows = [
            self._lesson_to_row(lesson, "class", now_utc)
            for lesson in class_lessons
        ] + [
            self._lesson_to_row(lesson, "teacher", now_utc)
            for lesson in teacher_lessons
        ]


        async with self.transaction() as db:
            await db.execute(
                """
                INSERT INTO raw_nika_cache (
                    id, js_filename, raw_sha256, fetched_at, content
                )
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    js_filename = excluded.js_filename,
                    raw_sha256 = excluded.raw_sha256,
                    fetched_at = excluded.fetched_at,
                    content = excluded.content
                """,
                (
                    source.js_filename,
                    raw_sha256,
                    now_utc,
                    js_content,
                ),
            )


            await db.execute(
                f"""
                DELETE FROM schedule_cache
                WHERE date IN ({placeholders})
                """,
                tuple(target_date_values),
            )


            await db.execute(
                """
                DELETE FROM schedule_cache
                WHERE date < ?
                """,
                (history_cutoff,),
            )


            if lesson_rows:
                await db.executemany(
                    _SCHEDULE_UPSERT_SQL,
                    lesson_rows,
                )


            await db.execute(
                """
                INSERT INTO nika_source_state (
                    id,
                    js_filename,
                    export_date,
                    export_time,
                    raw_sha256,
                    semantic_sha256,
                    last_checked_at,
                    last_changed_at,
                    coverage_start_date,
                    coverage_end_date,
                    last_error,
                    last_error_at
                )
                VALUES (
                    1,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    NULL,
                    NULL
                )
                ON CONFLICT(id) DO UPDATE SET
                    js_filename = excluded.js_filename,
                    export_date = excluded.export_date,
                    export_time = excluded.export_time,
                    raw_sha256 = excluded.raw_sha256,
                    semantic_sha256 = excluded.semantic_sha256,
                    last_checked_at = excluded.last_checked_at,
                    last_changed_at = CASE
                        WHEN ? = 1 THEN ?
                        ELSE nika_source_state.last_changed_at
                    END,
                    coverage_start_date = excluded.coverage_start_date,
                    coverage_end_date = excluded.coverage_end_date,
                    last_error = NULL,
                    last_error_at = NULL
                """,
                (
                    source.js_filename,
                    export_date,
                    export_time,
                    raw_sha256,
                    semantic_sha256,
                    now_utc,
                    now_utc,
                    coverage_start_date,
                    coverage_end_date,
                    int(schedule_changed),
                    now_utc,
                ),
            )

        # Обновление статистики query planner'а после массовой
        # перезаписи кэша (дёшево, заметно ускоряет последующие SELECT).
        try:
            await self._execute("PRAGMA optimize")
        except Exception:
            logger.debug("PRAGMA optimize after snapshot failed.")


        logger.info(
            "NIKA snapshot applied: source_changed=%s, "
            "schedule_changed=%s, lessons=%d "
            "(class=%d, teacher=%d), "
            "coverage=%s..%s, revision=%s",
            source_changed,
            schedule_changed,
            len(lesson_rows),
            len(class_lessons),
            len(teacher_lessons),
            coverage_start_date,
            coverage_end_date,
            source.js_filename,
        )


        return ScheduleRefreshResult(
            source_changed=source_changed,
            schedule_changed=schedule_changed,
            js_filename=source.js_filename,
            lesson_count=len(lesson_rows),
            reason=reason,
        )
