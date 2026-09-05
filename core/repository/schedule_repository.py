from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.models.domain import LessonInstance
from core.nika.fetcher import (
    NikaSourceDescriptor,
    ScheduleFetcher,
)
from core.nika.normalizer import NikaNormalizer
from core.repository.base_repository import BaseRepository
from services.time_service import TimeService

logger = logging.getLogger(__name__)


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
    - schedule_cache хранит ограниченный горизонт дат.
    """

    HISTORY_DAYS = 7

    def __init__(
        self,
        db_path: str,
        time_service: TimeService,
        proxy: str | None = None,
    ):
        super().__init__(
            db_path=db_path,
            time_service=time_service,
        )

        self.fetcher = ScheduleFetcher(
            proxy=proxy,
        )

    # ==========================================================
    # State / raw cache
    # ==========================================================

    async def get_nika_source_state(
        self,
    ) -> Optional[Dict[str, Any]]:
        """
        Возвращает единственную строку состояния актуального NIKA source.
        """
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
        """
        Возвращает текущий singleton raw NIKA cache.
        """
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
        await self._execute(
            """
            UPDATE nika_source_state
            SET
                last_checked_at = CURRENT_TIMESTAMP,
                last_error = NULL,
                last_error_at = NULL
            WHERE id = 1
            """
        )

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
        Возвращает расписание класса на конкретную дату.
        """
        return await self._fetch_all(
            """
            SELECT *
            FROM schedule_cache
            WHERE class_id = ?
              AND date = ?
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
        Возвращает расписание учителя на конкретную дату.
        """
        return await self._fetch_all(
            """
            SELECT *
            FROM schedule_cache
            WHERE teacher_id = ?
              AND date = ?
            ORDER BY start_time, lesson_num, id
            """,
            (teacher_id, date_iso),
        )

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

        schedule_cache не трогается, потому что semantic hash совпадает.
        """
        async with self._connection() as db:
            await db.execute("BEGIN")

            try:
                await db.execute(
                    """
                    INSERT INTO raw_nika_cache (
                        id,
                        js_filename,
                        raw_sha256,
                        fetched_at,
                        content
                    )
                    VALUES (
                        1,
                        ?,
                        ?,
                        CURRENT_TIMESTAMP,
                        ?
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        js_filename = excluded.js_filename,
                        raw_sha256 = excluded.raw_sha256,
                        fetched_at = CURRENT_TIMESTAMP,
                        content = excluded.content
                    """,
                    (
                        source.js_filename,
                        raw_sha256,
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
                        CURRENT_TIMESTAMP,
                        COALESCE(
                            (
                                SELECT last_changed_at
                                FROM nika_source_state
                                WHERE id = 1
                            ),
                            CURRENT_TIMESTAMP
                        ),
                        (
                            SELECT coverage_start_date
                            FROM nika_source_state
                            WHERE id = 1
                        ),
                        (
                            SELECT coverage_end_date
                            FROM nika_source_state
                            WHERE id = 1
                        ),
                        NULL,
                        NULL
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        js_filename = excluded.js_filename,
                        export_date = excluded.export_date,
                        export_time = excluded.export_time,
                        raw_sha256 = excluded.raw_sha256,
                        semantic_sha256 = excluded.semantic_sha256,
                        last_checked_at = CURRENT_TIMESTAMP,
                        last_error = NULL,
                        last_error_at = NULL
                    """,
                    (
                        source.js_filename,
                        export_date,
                        export_time,
                        raw_sha256,
                        semantic_sha256,
                    ),
                )

                await db.commit()

            except Exception:
                await db.rollback()
                raise

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
        Нормализует NIKA и применяет новый rolling snapshot транзакционно.

        При ошибке:
        - raw cache не меняется;
        - nika state не меняется;
        - schedule_cache не очищается;
        - работает прошлый актуальный cache.
        """
        normalizer = NikaNormalizer(
            nika_data,
        )

        lessons: List[LessonInstance] = normalizer.build_class_lessons(
            target_dates,
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
            - datetime.timedelta(days=self.HISTORY_DAYS)
        ).isoformat()

        placeholders = ",".join(
            "?"
            for _ in target_date_values
        )

        async with self._connection() as db:
            await db.execute("BEGIN")

            try:
                # Raw NIKA singleton.
                await db.execute(
                    """
                    INSERT INTO raw_nika_cache (
                        id,
                        js_filename,
                        raw_sha256,
                        fetched_at,
                        content
                    )
                    VALUES (
                        1,
                        ?,
                        ?,
                        CURRENT_TIMESTAMP,
                        ?
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        js_filename = excluded.js_filename,
                        raw_sha256 = excluded.raw_sha256,
                        fetched_at = CURRENT_TIMESTAMP,
                        content = excluded.content
                    """,
                    (
                        source.js_filename,
                        raw_sha256,
                        js_content,
                    ),
                )


                # Удаляем только обновляемый rolling horizon.
                await db.execute(
                    f"""
                    DELETE FROM schedule_cache
                    WHERE date IN ({placeholders})
                    """,
                    tuple(target_date_values),
                )

                # Очищаем даты старше history window.
                await db.execute(
                    """
                    DELETE FROM schedule_cache
                    WHERE date < ?
                    """,
                    (history_cutoff,),
                )

                for lesson in lessons:
                    await db.execute(
                        """
                        INSERT INTO schedule_cache (
                            id,
                            date,
                            period_id,
                            class_id,
                            lesson_num,
                            group_id,
                            group_name,
                            subject_id,
                            subject_name,
                            teacher_id,
                            teacher_name,
                            room_id,
                            room_name,
                            start_time,
                            end_time,
                            is_exchange,
                            is_cancelled,
                            created_at
                        )
                        VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
                        )
                        ON CONFLICT(id) DO UPDATE SET
                            date = excluded.date,
                            period_id = excluded.period_id,
                            class_id = excluded.class_id,
                            lesson_num = excluded.lesson_num,
                            group_id = excluded.group_id,
                            group_name = excluded.group_name,
                            subject_id = excluded.subject_id,
                            subject_name = excluded.subject_name,
                            teacher_id = excluded.teacher_id,
                            teacher_name = excluded.teacher_name,
                            room_id = excluded.room_id,
                            room_name = excluded.room_name,
                            start_time = excluded.start_time,
                            end_time = excluded.end_time,
                            is_exchange = excluded.is_exchange,
                            is_cancelled = excluded.is_cancelled,
                            created_at = CURRENT_TIMESTAMP
                        """,
                        (
                            lesson.id,
                            lesson.date,
                            lesson.period_id,
                            lesson.class_id,
                            lesson.lesson_num,
                            lesson.group_id,
                            lesson.group_name,
                            lesson.subject_id,
                            lesson.subject_name,
                            lesson.teacher_id,
                            lesson.teacher_name,
                            lesson.room_id,
                            lesson.room_name,
                            lesson.start_time,
                            lesson.end_time,
                            int(lesson.is_exchange),
                            int(lesson.is_cancelled),
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
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP,
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
                        last_checked_at = CURRENT_TIMESTAMP,
                        last_changed_at = CASE
                            WHEN ? = 1
                            THEN CURRENT_TIMESTAMP
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
                        coverage_start_date,
                        coverage_end_date,
                        int(schedule_changed),
                    ),
                )

                await db.commit()

            except Exception:
                await db.rollback()
                raise

        logger.info(
            "NIKA snapshot applied: source_changed=%s, "
            "schedule_changed=%s, lessons=%d, "
            "coverage=%s..%s, revision=%s",
            source_changed,
            schedule_changed,
            len(lessons),
            coverage_start_date,
            coverage_end_date,
            source.js_filename,
        )

        return ScheduleRefreshResult(
            source_changed=source_changed,
            schedule_changed=schedule_changed,
            js_filename=source.js_filename,
            lesson_count=len(lessons),
            reason=reason,
        )