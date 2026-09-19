# core/repository/schedule_repository.py
#
# РЕФАКТОРИНГ (этап «эталонный вид»):
# 1. Публичные методы больше не возвращают Dict[str, Any]:
#    get_nika_source_state() -> NikaSourceStateDTO,
#    get_cached_raw_nika()  -> RawNikaCacheDTO,
#    get_nika_health_status() -> NikaSourceHealthDTO (DTO уже существовал).
# 2. parse_nika() больше не дергает приватный fetcher._extract_json_from_js —
#    требуется публичный fetcher.extract_json_from_js() (однострочный ренейм
#    в core/nika/fetcher.py, см. примечание в конце файла).
# 3. SQL UPSERT nika_source_state и raw_nika_cache существовал в двух
#    копиях (_update_revision_only / _apply_new_nika_version) — вынесен
#    в единые приватные хелперы _upsert_raw_cache / _upsert_source_state.
# 4. get_metadata() читает CLASS_SHIFT/SECOND_RELATIVE через normalizer,
#    а не сырые .get() по dict NIKA.

# ИСТОРИЯ ФИКСОВ _lesson_to_row:
#
# R1 (критично, v2): восстановленные orig_sub/orig_room вычислялись из
#     history_map, но НЕ попадали в возвращаемый кортеж — там оставались
#     lesson.original_subject_name / lesson.original_room_name. Механизм
#     спасения истории был мёртвым кодом.
#
# R2 (v2): фолбэк "_0" для слитых в ALL уроков слеп к реальным id групп
#     ("3"/"4" у классов 10-x). Заменён на prefix-scan по всем группам слота.
#
# БОМБА 3 (v3): у teacher-строк класс зашит в ID
#     (T{teacher}_{period}_{class}_{date}_{lesson}_{group}). Если замена
#     перевела учителя на ДРУГОЙ класс, prefix-scan с новым классом не
#     находит вчерашнюю историю.
#
#     ВНИМАНИЕ: патч через parts[2] НЕКОРРЕКТЕН:
#     1) триггер "lesson.original_class_id and ..." не срабатывает в
#        заявленном же сценарии (при удалённой базе original_class_id=None);
#     2) split('_')[2] ломается на fallback-классах TEACHER_{id}:
#        "T038_109_TEACHER_038_..." -> parts[2]=='TEACHER', а не класс.
#     Корректное решение — структурный поиск: голова T{teacher}_{period}_
#     + хвост _{date}_{lesson}_, между ними — ЛЮБОЙ класс.

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, List, Optional

import aiohttp

from core.models.domain import LessonInstance
from core.models.dto import (
    NikaSourceHealthDTO,
    NikaSourceStateDTO,
    RawNikaCacheDTO,
)
from core.nika.fetcher import NikaSourceDescriptor, ScheduleFetcher
from core.nika.normalizer import NikaNormalizer
from core.nika.exceptions import ScheduleDataError
from core.repository.base_repository import BaseRepository
from services.time_service import TimeService
from core.models.metadata import SchoolMetadata

logger = logging.getLogger(__name__)

# Единый UPSERT schedule_cache: защита original_subject_name через COALESCE
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
        
        original_subject_id = COALESCE(excluded.original_subject_id, schedule_cache.original_subject_id),
        original_subject_name = COALESCE(excluded.original_subject_name, schedule_cache.original_subject_name),
        original_teacher_id = COALESCE(excluded.original_teacher_id, schedule_cache.original_teacher_id),
        original_teacher_name = COALESCE(excluded.original_teacher_name, schedule_cache.original_teacher_name),
        original_room_id = COALESCE(excluded.original_room_id, schedule_cache.original_room_id),
        original_room_name = COALESCE(excluded.original_room_name, schedule_cache.original_room_name),
        original_class_id = COALESCE(excluded.original_class_id, schedule_cache.original_class_id),
        original_class_name = COALESCE(excluded.original_class_name, schedule_cache.original_class_name),
        original_group_id = COALESCE(excluded.original_group_id, schedule_cache.original_group_id),
        original_group_name = COALESCE(excluded.original_group_name, schedule_cache.original_group_name),
        
        start_time = excluded.start_time,
        end_time = excluded.end_time,
        is_exchange = excluded.is_exchange,
        is_cancelled = excluded.is_cancelled,
        is_methodological = excluded.is_methodological,
        created_at = excluded.created_at
"""

@dataclass(frozen=True)
class ScheduleRefreshResult:
    """Результат одной попытки синхронизации NIKA."""
    source_changed: bool
    schedule_changed: bool
    js_filename: Optional[str] = None
    lesson_count: int = 0
    reason: str = ""


def _iso_or_none(value: datetime.datetime | str | None) -> Optional[str]:
    """Aware UTC datetime -> ISO-строка для текстовых полей health DTO."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat(sep=" ")


class ScheduleRepository(BaseRepository):
    """
    Репозиторий школьного расписания.

    Правила:
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
        metadata_cache: Optional[SchoolMetadata] = None,
    ) -> None:
        super().__init__(db_path=db_path, time_service=time_service)
        self.fetcher = ScheduleFetcher(
            session=http_session,
            base_url=nika_base_url,
            proxy=proxy,
            tls_fingerprint_sha256=tls_fingerprint_sha256,
        )
        self.history_days = history_days
        self._metadata_cache = metadata_cache

    def is_ssl_degraded(self) -> bool:
        """True, если NIKA-фетчер работает в обход TLS-проверки."""
        return self.fetcher.ssl_degraded

    # ==========================================================
    # Public API: парсинг NIKA
    # ==========================================================

    def parse_nika(self, content: str) -> dict[str, Any]:
        """Извлекает JSON из JS-файла NIKA (публичный метод фетчера)."""
        return self.fetcher.extract_json_from_js(content)

    # ==========================================================
    # Row <-> LessonInstance mapping
    # ==========================================================
# НАЙДЕННЫЕ БАГИ в _lesson_to_row:
#
# R1 (КРИТИЧНО): восстановленные orig_sub/orig_room вычисляются из history_map,
#     но НЕ попадают в возвращаемый кортеж — там остаются
#     lesson.original_subject_name / lesson.original_room_name.
#     Весь механизм спасения истории — мёртвый код. Доказано в песочнице:
#     при удалении школой базового слота (крашеный день 3) оригиналы
#     терялись (NULL) при живом history_map.
#
# R2: фолбэк "_0" для слитых в ALL уроков слеп к реальным id групп:
#     в CLASSGROUPS существуют "3"/"4" ("1 группа"/"2 группа", классы 10-x),
#     и для них base_id + "_0" не находит историю. Доказано: класс 031,
#     слияние групп 3/4 → история не восстанавливалась.
# В текущий момент баги пофикшены

    @staticmethod
    def _lesson_to_row(
        lesson: LessonInstance,
        origin: str,
        now_utc: str,
        history_map: dict[str, dict[str, str]] | None = None,
    ) -> tuple:
        """
        LessonInstance -> кортеж.
        Восстанавливает original_subject_name / original_room_name из
        history_map, спасая их от стирания при DELETE/INSERT.

        Отличия от прежней версии:
        1. Возвращаем ИМЕННО восстановленные orig_sub / orig_room (баг R1).
        2. Смежную историю ищем prefix-scan'ом по всем группам слота,
           а не угадыванием "_0" (баг R2: группы бывают "3"/"4"/...).
        """
        orig_sub = lesson.original_subject_name
        orig_room = lesson.original_room_name
        orig_teacher = lesson.original_teacher_name
        orig_group_name = lesson.original_group_name

        if history_map:
            hist_data = history_map.get(lesson.id)

            if not hist_data:
                # Ищем ЛЮБУЮ смежную историю того же слота (того же
                # класса/учителя, даты и номера урока). Покрывает:
                # - деление: строки групп ищут историю "ALL";
                # - слияние: строка ALL ищет историю любой группы
                #   (в т.ч. экзотические "3"/"4", которые старый
                #   фолбэк "_0" не находил);
                # - регруппировку: группа "1" наследует историю группы "0".
                prefix = lesson.id.rsplit('_', 1)[0] + "_"
                candidates = [(k, v) for k, v in history_map.items() if k.startswith(prefix)]

                # 2) БОМБА 3: у teacher-строк класс зашит в ID. При смене
                #    класса в замене ищем по структуре БЕЗ сегмента класса:
                #    T{teacher}_{period}_{*}_{date}_{lesson}_{group}.
                if not candidates and origin == "teacher" and lesson.teacher_id and lesson.id.startswith("T"):
                    head = f"T{lesson.teacher_id}_{lesson.period_id}_"
                    mid = f"_{lesson.date}_{lesson.lesson_num}_"
                    candidates = [
                        (k, v) for k, v in history_map.items()
                        if k.startswith(head) and mid in k and k.find(mid) >= len(head)
                    ]

                if len(candidates) == 1:
                    hist_data = candidates[0][1]
                elif candidates:
                    # При слиянии предпочтём историю «весь класс»,
                    # иначе — первую групповую.
                    all_rows = [v for k, v in candidates if k.rsplit('_', 1)[-1] == "ALL"]
                    hist_data = all_rows[0] if all_rows else candidates[0][1]

            if hist_data:
                if not orig_sub:
                    orig_sub = hist_data.get("sub")
                if not orig_room:
                    orig_room = hist_data.get("room")
                if not orig_teacher:
                    orig_teacher = hist_data.get("teacher")
                if not orig_group_name:
                    orig_group_name = hist_data.get("group_name")

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
            orig_sub,                                # ФИКС R1 (Предмет)
            lesson.original_teacher_id,
            orig_teacher,                            # ФИКС: Восстановление учителя
            lesson.original_room_id,
            orig_room,                               # ФИКС R1 (Кабинет)
            lesson.original_class_id,
            lesson.original_class_name,
            lesson.original_group_id,
            orig_group_name,                         # ФИКС: Восстановление имени группы
            lesson.start_time,
            lesson.end_time,
            int(lesson.is_exchange),
            int(lesson.is_cancelled),
            int(lesson.is_methodological),
            now_utc,
        )

# ДОПОЛНИТЕЛЬНАЯ РЕКОМЕНДАЦИЯ (не баг, а усиление):
# в _apply_new_nika_version расширьте SELECT history_map, чтобы спасать
# и учителя/группу исходного урока, а не только предмет и кабинет:
#
#   cursor = await db.execute(
#       f"SELECT id, original_subject_name, original_room_name, "
#       f"original_teacher_name, original_group_id "
#       f"FROM schedule_cache WHERE date IN ({placeholders})",
#       tuple(target_date_values)
#   )
#   history_map = {
#       row[0]: {
#           "sub": row[1], "room": row[2],
#           "teacher": row[3], "group": row[4],
#       } for row in history_rows
#   }
#
# и в _lesson_to_row при пустых lesson.original_teacher_name /
# lesson.original_group_name подтягивайте их аналогично orig_sub/orig_room.


    @staticmethod
    def _row_to_lesson(row: dict[str, Any]) -> LessonInstance:
        """Строка schedule_cache -> LessonInstance."""
        weekday = row.get("weekday")
        if not weekday:
            weekday = datetime.date.fromisoformat(row["date"]).isoweekday()

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
    # NIKA source state (DTO, не dict)
    # ==========================================================

    async def get_nika_source_state(self) -> Optional[NikaSourceStateDTO]:
        row = await self._fetch_one(
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
        if row is None:
            return None
        return NikaSourceStateDTO(
            js_filename=row["js_filename"],
            raw_sha256=row["raw_sha256"],
            semantic_sha256=row["semantic_sha256"],
            export_date=row.get("export_date"),
            export_time=row.get("export_time"),
            last_checked_at=row.get("last_checked_at"),
            last_changed_at=row.get("last_changed_at"),
            coverage_start_date=row.get("coverage_start_date"),
            coverage_end_date=row.get("coverage_end_date"),
            last_error=row.get("last_error"),
            last_error_at=row.get("last_error_at"),
        )

    async def get_cached_raw_nika(self) -> Optional[RawNikaCacheDTO]:
        row = await self._fetch_one(
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
        if row is None:
            return None
        return RawNikaCacheDTO(
            js_filename=row["js_filename"],
            raw_sha256=row["raw_sha256"],
            content=row["content"],
            fetched_at=row.get("fetched_at"),
        )

    async def touch_nika_checked_at(self) -> None:
        """Фиксирует успешную HTML-проверку без изменения revision."""
        await self._execute(
            """
            UPDATE nika_source_state
            SET last_checked_at = ?,
                last_error = NULL,
                last_error_at = NULL
            WHERE id = 1
            """,
            (self._now_utc_str(),),
        )

    async def record_nika_refresh_error(self, *, error_message: str) -> None:
        """Сохраняет последнюю ошибку обновления NIKA."""
        normalized_error = (
            error_message.strip()[:1500]
            if error_message
            else "Unknown NIKA refresh error"
        )
        now_utc = self._now_utc_str()
        changed = await self._execute(
            """
            UPDATE nika_source_state
            SET last_error = ?,
                last_error_at = ?
            WHERE id = 1
            """,
            (normalized_error, now_utc),
        )
        if changed == 0:
            logger.warning(
                "NIKA refresh failed before initial source state exists: %s",
                normalized_error,
            )

    async def clear_nika_refresh_error(self) -> None:
        await self._execute(
            """
            UPDATE nika_source_state
            SET last_error = NULL,
                last_error_at = NULL
            WHERE id = 1
              AND (last_error IS NOT NULL OR last_error_at IS NOT NULL)
            """
        )

    async def get_nika_health_status(self) -> NikaSourceHealthDTO:
        """
        Сохранённый статус NIKA source и schedule cache.

        Без HTTP-запросов и refresh — безопасен для admin diagnostics.
        Возвращает NikaSourceHealthDTO (раньше — dict).
        """
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
        lesson_count = int(cache_info["lesson_count"]) if cache_info else 0
        first_date = cache_info.get("first_date") if cache_info else None
        last_date = cache_info.get("last_date") if cache_info else None

        if state is None:
            return NikaSourceHealthDTO(
                status=(
                    "cache_empty"
                    if lesson_count == 0
                    else "cache_without_source_state"
                ),
                lesson_count=lesson_count,
                coverage_start_date=first_date,
                coverage_end_date=last_date,
                today_date=today_iso,
            )

        if state.last_error:
            status = (
                "source_error_cache_available"
                if lesson_count > 0
                else "source_error_cache_empty"
            )
        elif lesson_count == 0:
            status = "source_healthy_cache_empty"
        else:
            status = "healthy"

        coverage_end_date = state.coverage_end_date or last_date

        return NikaSourceHealthDTO(
            status=status,
            lesson_count=lesson_count,
            coverage_start_date=state.coverage_start_date or first_date,
            coverage_end_date=coverage_end_date,
            today_date=today_iso,
            coverage_is_current=bool(
                coverage_end_date and coverage_end_date >= today_iso
            ),
            coverage_has_future=bool(
                coverage_end_date and coverage_end_date > today_iso
            ),
            js_filename=state.js_filename,
            export_date=state.export_date,
            export_time=state.export_time,
            last_checked_at=_iso_or_none(state.last_checked_at),
            last_changed_at=_iso_or_none(state.last_changed_at),
            last_error=state.last_error,
            last_error_at=_iso_or_none(state.last_error_at),
        )

    @staticmethod
    def _coverage_needs_refresh(
        state: Optional[NikaSourceStateDTO],
        target_dates: List[datetime.date],
    ) -> bool:
        """True, если rolling coverage не совпадает с требуемым окном дат."""
        if not target_dates:
            return False
        if state is None:
            return True

        expected_start = min(target_dates).isoformat()
        expected_end = max(target_dates).isoformat()

        return (
            state.coverage_start_date != expected_start
            or state.coverage_end_date != expected_end
        )

    # ==========================================================
    # Metadata / schedule reads
    # ==========================================================

    async def get_metadata(self) -> SchoolMetadata:
        """Строит SchoolMetadata один раз и кеширует в памяти."""
        if self._metadata_cache is not None:
            return self._metadata_cache

        raw = await self.get_cached_raw_nika()
        if raw is None or not raw.content:
            logger.error("NIKA raw cache is empty — cannot build metadata.")
            raise ScheduleDataError("NIKA raw cache is empty")

        try:
            nika_data = self.parse_nika(raw.content)
            normalizer = NikaNormalizer(nika_data)

            self._metadata_cache = SchoolMetadata(
                classes=normalizer.classes,
                groups=nika_data.get("CLASSGROUPS", {}),
                teachers=normalizer.teachers,
                class_shift=nika_data.get("CLASS_SHIFT", {}),
                second_relative=bool(nika_data.get("SECOND_RELATIVE", False)),
            )
            return self._metadata_cache
        except Exception as exc:
            logger.exception("Failed to build NIKA metadata from raw cache.")
            raise ScheduleDataError("Cannot build school metadata") from exc

    async def get_lessons_for_class(
        self,
        class_id: str,
        date_iso: str,
    ) -> list[LessonInstance]:
        """Расписание класса на дату (только class-origin строки)."""
        rows = await self._fetch_all(
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
        return [self._row_to_lesson(r) for r in rows]

    async def get_lessons_for_teacher(
        self,
        teacher_id: str,
        date_iso: str,
    ) -> list[LessonInstance]:
        """Расписание учителя на дату (teacher-origin: методчасы + TEACH_EXCHANGE)."""
        rows = await self._fetch_all(
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
        return [self._row_to_lesson(r) for r in rows]

    async def get_day_change_count(
        self,
        date_iso: str,
        origin: str = "class",
    ) -> int:
        """Количество изменённых/отменённых уроков за дату."""
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

        Причины:
        - empty_target_dates / same_filename / coverage_extended /
          export_changed_semantics_same / initial_bootstrap / schedule_changed.
        """
        if not target_dates:
            return ScheduleRefreshResult(
                source_changed=False,
                schedule_changed=False,
                reason="empty_target_dates",
            )

        source = await self.fetcher.probe()
        state = await self.get_nika_source_state()

        coverage_changed = self._coverage_needs_refresh(state, target_dates)

        # Дешёвый путь: HTML проверен, filename прежний, coverage актуален.
        if (
            state is not None
            and state.js_filename == source.js_filename
            and not coverage_changed
        ):
            await self.touch_nika_checked_at()
            return ScheduleRefreshResult(
                source_changed=False,
                schedule_changed=False,
                js_filename=source.js_filename,
                reason="same_filename",
            )

        # Filename прежний, но rolling horizon сдвинулся:
        # пересборка из локального raw cache без повторного скачивания JS.
        if (
            state is not None
            and state.js_filename == source.js_filename
            and coverage_changed
        ):
            raw = await self.get_cached_raw_nika()
            if raw is not None and raw.content:
                return await self._refresh_from_cached_raw(
                    target_dates=target_dates,
                    state=state,
                    raw=raw,
                )
            logger.warning(
                "Coverage changed but raw NIKA cache is missing. "
                "Downloading JS again."
            )

        # Новый filename либо первичный bootstrap.
        js_content = await self.fetcher.fetch_js_content(source)
        nika_data = self.parse_nika(js_content)
        raw_sha256 = self.fetcher.calculate_raw_sha256(js_content)
        semantic_sha256 = self.fetcher.calculate_semantic_sha256(nika_data)
        export_date = nika_data.get("EXPORT_DATE")
        export_time = nika_data.get("EXPORT_TIME")

        # Новый filename, но semantics не изменились: только revision + raw.
        if (
            state is not None
            and state.semantic_sha256 == semantic_sha256
            and not coverage_changed
        ):
            await self._update_revision_only(
                source=source,
                js_content=js_content,
                raw_sha256=raw_sha256,
                semantic_sha256=semantic_sha256,
                export_date=export_date,
                export_time=export_time,
                state=state,  # <-- Передаем state
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
        state: NikaSourceStateDTO,
        raw: RawNikaCacheDTO,
    ) -> ScheduleRefreshResult:
        """
        Расширяет rolling coverage из локального raw NIKA cache.

        schedule_changed=False: это не изменение расписания,
        immediate change notifications не нужны.
        """
        nika_data = self.parse_nika(raw.content)

        return await self._apply_new_nika_version(
            source=NikaSourceDescriptor(
                js_filename=state.js_filename,
                js_url="",
            ),
            js_content=raw.content,
            nika_data=nika_data,
            raw_sha256=state.raw_sha256,
            semantic_sha256=state.semantic_sha256,
            export_date=state.export_date,
            export_time=state.export_time,
            target_dates=target_dates,
            source_changed=False,
            schedule_changed=False,
            reason="coverage_extended",
            invalidate_metadata=False, # <-- : сохраняем кеш метаданных
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
        state: NikaSourceStateDTO,
    ) -> None:
        """Обновляет revision metadata и singleton raw cache.

        schedule_cache не трогается: semantic hash не изменился.
        Coverage сохраняется прежним (передаётся из текущего state).
        """
        now_utc = self._now_utc_str()

        async with self.transaction() as db:
            await self._upsert_raw_cache(
                db,
                js_filename=source.js_filename,
                raw_sha256=raw_sha256,
                now_utc=now_utc,
                js_content=js_content,
            )
            await self._upsert_source_state(
                db,
                js_filename=source.js_filename,
                export_date=export_date,
                export_time=export_time,
                raw_sha256=raw_sha256,
                semantic_sha256=semantic_sha256,
                now_utc=now_utc,
                coverage_start_date=state.coverage_start_date,
                coverage_end_date=state.coverage_end_date,
                schedule_changed=False,
            )

    async def _apply_new_nika_version(
        self, *, source: NikaSourceDescriptor, js_content: str, nika_data: dict[str, Any], raw_sha256: str, semantic_sha256: str,
        export_date: Optional[str], export_time: Optional[str], target_dates: List[datetime.date], source_changed: bool,
        schedule_changed: bool, reason: str, invalidate_metadata: bool = True,
    ) -> ScheduleRefreshResult:
        
        normalizer = NikaNormalizer(nika_data)
        
        # === ФИКС "СЛЕПОТЫ" БОТА: ЗАЩИТА ИСТОРИИ ===
        # Школа может удалить текущую неделю из NIKA и оставить только следующую.
        # Чтобы не затереть историю, мы будем обновлять (и удалять перед вставкой)
        # ТОЛЬКО те даты, для которых в скрипте NIKA реально есть активный период.
        valid_target_dates = [d for d in target_dates if normalizer._get_active_period(d) is not None]

        class_lessons = normalizer.build_class_lessons(valid_target_dates)
        teacher_lessons = normalizer.build_teacher_lessons(valid_target_dates)
        
        target_date_values = sorted({d.isoformat() for d in valid_target_dates})
        
        # Если валидных дат нет (скрипт пуст), берем запрошенные для метрик coverage
        coverage_start_date = target_date_values[0] if target_date_values else min(target_dates).isoformat()
        coverage_end_date = target_date_values[-1] if target_date_values else max(target_dates).isoformat()
        
        # history_cutoff привязываем строго к СЕГОДНЯШНЕМУ дню, а не к началу coverage NIKA,
        # чтобы перенос расписания на следующую неделю не удалил историю за текущую.
        now_date = self.time_service.get_now_base().date()
        history_cutoff = (now_date - datetime.timedelta(days=self.history_days)).isoformat()
        
        now_utc = self._now_utc_str()

        async with self.transaction() as db:
            await self._upsert_raw_cache(db, js_filename=source.js_filename, raw_sha256=raw_sha256, now_utc=now_utc, js_content=js_content)

            lesson_rows = []
            
            # Если NIKA прислала хоть какие-то валидные даты
            if target_date_values:
                placeholders = ",".join("?" for _ in target_date_values)

               # 1. Спасаем историю (Python-level COALESCE для обхода DELETE)
                cursor = await db.execute(
                    f"SELECT id, original_subject_name, original_room_name, "
                    f"original_teacher_name, original_group_name "
                    f"FROM schedule_cache WHERE date IN ({placeholders})",
                    tuple(target_date_values)
                )
                history_rows = await cursor.fetchall()
                history_map = {
                    row[0]: {
                        "sub": row[1],
                        "room": row[2],
                        "teacher": row[3],
                        "group_name": row[4]
                    } for row in history_rows
                }
                # 2. Формируем строки с учетом спасенной истории
                lesson_rows = [self._lesson_to_row(lesson, "class", now_utc, history_map) for lesson in class_lessons] + \
                              [self._lesson_to_row(lesson, "teacher", now_utc, history_map) for lesson in teacher_lessons]

                # 3. Удаляем старые записи ТОЛЬКО для тех дат, которые есть в новом NIKA
                await db.execute(f"DELETE FROM schedule_cache WHERE date IN ({placeholders})", tuple(target_date_values))

            # 4. Удаляем старую историю строго по актуальному cutoff от сегодняшнего дня
            await db.execute("DELETE FROM schedule_cache WHERE date < ?", (history_cutoff,))

            # 5. Вставляем новые записи
            if lesson_rows:
                await db.executemany(_SCHEDULE_UPSERT_SQL, lesson_rows)

            await self._upsert_source_state(
                db, js_filename=source.js_filename, export_date=export_date, export_time=export_time, raw_sha256=raw_sha256,
                semantic_sha256=semantic_sha256, now_utc=now_utc, coverage_start_date=coverage_start_date,
                coverage_end_date=coverage_end_date, schedule_changed=schedule_changed,
            )

        try: await self._execute("PRAGMA optimize")
        except Exception: pass

        if invalidate_metadata: self._metadata_cache = None

        return ScheduleRefreshResult(
            source_changed=source_changed, schedule_changed=schedule_changed, js_filename=source.js_filename,
            lesson_count=len(lesson_rows), reason=reason,
        )
        
    # ==========================================================
    # Внутренние SQL-хелперы (раньше дублировались в двух методах)
    # ==========================================================

    @staticmethod
    async def _upsert_raw_cache(
        db,
        *,
        js_filename: str,
        raw_sha256: str,
        now_utc: str,
        js_content: str,
    ) -> None:
        """Singleton raw NIKA cache (общий для обоих путей обновления)."""
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
            (js_filename, raw_sha256, now_utc, js_content),
        )

    @staticmethod
    async def _upsert_source_state(
        db,
        *,
        js_filename: str,
        export_date: Optional[str],
        export_time: Optional[str],
        raw_sha256: str,
        semantic_sha256: str,
        now_utc: str,
        coverage_start_date: Optional[str],
        coverage_end_date: Optional[str],
        schedule_changed: bool,
    ) -> None:
        """
        Единственный UPSERT nika_source_state.

        last_changed_at обновляется только при schedule_changed=1;
        при bootstrap (строки ещё нет) всегда берётся now_utc.
        """
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
                1, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL
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
                    ELSE COALESCE(nika_source_state.last_changed_at, ?)
                END,
                coverage_start_date = excluded.coverage_start_date,
                coverage_end_date = excluded.coverage_end_date,
                last_error = NULL,
                last_error_at = NULL
            """,
            (
                js_filename,
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
                now_utc,
            ),
        )

