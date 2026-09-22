"""CI-тесты утренней рассылки постерами (этап 4) — без браузера и БД."""

import asyncio
from types import SimpleNamespace

from core.models.dto import DayScheduleDTO, LessonDTO
from services.image_render.exceptions import ImageRenderError
from services.image_render.morning_posters import send_morning_posters
from services.image_render.models import RenderedPoster
from services.time_service import TimeService, TimeServiceConfig


class _FakeRepo:
    def __init__(self, student_tasks, teacher_tasks=()):
        self.student_tasks = student_tasks
        self.teacher_tasks = teacher_tasks
        self.recorded = []

    async def get_blocked_user_ids(self):
        return [99]

    async def get_morning_summary_tasks(self, *, time_str):
        return self.student_tasks

    async def get_teacher_morning_summary_tasks(self, *, time_str):
        return self.teacher_tasks

    async def record_notification_delivery(self, **kwargs):
        self.recorded.append(kwargs)


class _FakeScheduleRepo:
    async def get_nika_source_state(self):
        return SimpleNamespace(semantic_sha256="ab" * 32)


class _FakeScheduleService:
    def __init__(self, empty=False):
        self.empty = empty

    async def get_daily_schedule_for_student(self, *, class_id, group_id, date_iso, student_id):
        if self.empty:
            return DayScheduleDTO(date_iso=date_iso, lessons=[], origin="student", class_name="5А")
        return DayScheduleDTO(
            date_iso=date_iso,
            lessons=[
                LessonDTO(
                    lesson_num=1,
                    start_time="08:15",
                    end_time="09:00",
                    subject_name="Математика",
                    is_exchange=True,
                    original_subject_name="Физика",
                )
            ],
            origin="student",
            class_name="5А",
        )

    async def get_daily_schedule_for_teacher(self, *, teacher_id, date_iso):
        return DayScheduleDTO(
            date_iso=date_iso,
            lessons=[
                LessonDTO(
                    lesson_num=1,
                    start_time="08:15",
                    end_time="09:00",
                    subject_name="Математика",
                )
            ],
            origin="teacher",
        )


class _FakeExtraClasses:
    async def get_extra_classes_for_student(self, *, student_id, day_of_week):
        return []


class _FakeImagePrefs:
    def __init__(self, image_users):
        self.image_users = image_users

    async def prefers_image(self, user_id):
        return user_id in self.image_users


class _FakeImageService:
    def __init__(self, fail=False):
        self.fail = fail
        self.file_ids = {}

    async def get_poster(self, request, user_id=None):
        if self.fail:
            raise ImageRenderError("рендер недоступен (тест)")
        return RenderedPoster(
            request_id=request.request_id,
            png_bytes=b"\x89PNG-morning",
            width=request.width,
            height=100,
        )

    def get_file_id(self, request_id):
        return self.file_ids.get(request_id)

    def store_file_id(self, request_id, file_id):
        self.file_ids[request_id] = file_id

    def invalidate_file_id(self, request_id):
        self.file_ids.pop(request_id, None)


class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        self.sent.append(chat_id)
        return SimpleNamespace(photo=[SimpleNamespace(file_id="FID_MORNING")])


def _time_service() -> TimeService:
    return TimeService(TimeServiceConfig(timezone="Asia/Novosibirsk"))


def _student_task(recipient_id=1, student_id=42):
    return SimpleNamespace(
        recipient_id=recipient_id,
        target_student_id=student_id,
        recipient_kind="adult",
        child_name="Иван",
        class_id="016",
        group_id="ALL",
    )


def test_morning_poster_sent_and_delivery_recorded() -> None:
    async def scenario() -> None:
        repo = _FakeRepo(student_tasks=[_student_task()])
        bot = _FakeBot()

        result = await send_morning_posters(
            bot=bot,
            time_service=_time_service(),
            notification_repo=repo,
            schedule_repo=_FakeScheduleRepo(),
            schedule_service=_FakeScheduleService(),
            extra_classes_service=_FakeExtraClasses(),
            image_service=_FakeImageService(),
            image_prefs=_FakeImagePrefs(image_users={1}),
        )

        assert bot.sent == [1]
        assert result["sent"] == 1
        # Доставка зафиксирована ключами текстового конвейера — дубликата текстом не будет
        assert len(repo.recorded) == 1
        assert repo.recorded[0]["notification_type"] == "morning_summary"
        assert repo.recorded[0]["source_id"] == "morning_summary_42"
        assert repo.recorded[0]["recipient_id"] == 1

    asyncio.run(scenario())


def test_text_pref_and_blocked_users_skipped() -> None:
    async def scenario() -> None:
        repo = _FakeRepo(
            student_tasks=[
                _student_task(recipient_id=1),  # формат «текст»
                _student_task(recipient_id=99, student_id=43),  # заблокирован
            ]
        )
        bot = _FakeBot()

        result = await send_morning_posters(
            bot=bot,
            time_service=_time_service(),
            notification_repo=repo,
            schedule_repo=_FakeScheduleRepo(),
            schedule_service=_FakeScheduleService(),
            extra_classes_service=_FakeExtraClasses(),
            image_service=_FakeImageService(),
            image_prefs=_FakeImagePrefs(image_users=set()),
        )

        assert bot.sent == []
        assert repo.recorded == []
        assert result["text_pref"] == 1

    asyncio.run(scenario())


def test_render_failure_falls_back_to_text() -> None:
    async def scenario() -> None:
        repo = _FakeRepo(student_tasks=[_student_task()])
        bot = _FakeBot()

        result = await send_morning_posters(
            bot=bot,
            time_service=_time_service(),
            notification_repo=repo,
            schedule_repo=_FakeScheduleRepo(),
            schedule_service=_FakeScheduleService(),
            extra_classes_service=_FakeExtraClasses(),
            image_service=_FakeImageService(fail=True),
            image_prefs=_FakeImagePrefs(image_users={1}),
        )

        # Сбой рендера: доставка НЕ фиксируется — текст придёт на :30
        assert bot.sent == []
        assert repo.recorded == []
        assert result["failures"] == 1

    asyncio.run(scenario())


def test_empty_day_is_not_sent() -> None:
    async def scenario() -> None:
        repo = _FakeRepo(student_tasks=[_student_task()])
        bot = _FakeBot()

        result = await send_morning_posters(
            bot=bot,
            time_service=_time_service(),
            notification_repo=repo,
            schedule_repo=_FakeScheduleRepo(),
            schedule_service=_FakeScheduleService(empty=True),
            extra_classes_service=_FakeExtraClasses(),
            image_service=_FakeImageService(),
            image_prefs=_FakeImagePrefs(image_users={1}),
        )

        assert bot.sent == []
        assert repo.recorded == []
        assert result["empty_days"] == 1

    asyncio.run(scenario())


def test_teacher_morning_poster_recorded() -> None:
    async def scenario() -> None:
        repo = _FakeRepo(
            student_tasks=[],
            teacher_tasks=[
                SimpleNamespace(
                    recipient_id=7,
                    teacher_id="t01",
                    teacher_name="Петрова А.П.",
                )
            ],
        )
        bot = _FakeBot()

        result = await send_morning_posters(
            bot=bot,
            time_service=_time_service(),
            notification_repo=repo,
            schedule_repo=_FakeScheduleRepo(),
            schedule_service=_FakeScheduleService(),
            extra_classes_service=_FakeExtraClasses(),
            image_service=_FakeImageService(),
            image_prefs=_FakeImagePrefs(image_users={7}),
        )

        assert bot.sent == [7]
        assert result["sent"] == 1
        assert repo.recorded[0]["notification_type"] == "teacher_morning"
        assert repo.recorded[0]["source_id"] == "teacher_morning_t01"

    asyncio.run(scenario())
