from __future__ import annotations


from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace


import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates


from core.models.dto import (
    ActionResponseDTO,
    ScheduleTargetDTO,
    ScheduleTargetKind,
    ScheduleWatchTargetDTO,
    SchoolDictionariesDTO,
)
from services.web_sessions_service import WebSessionContext
from web.deps import require_family_allowed
from web.routes.schedule import router as schedule_router
from web.routes.school import router as school_router


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATES_DIR = _PROJECT_ROOT / "web" / "templates"


class FakeScheduleTargetsService:
    """
    Минимальный fake для selection endpoints.

    Проверяет route authorization contract:
    route ищет selected target только среди targets actor-а.
    """

    def __init__(self) -> None:
        self.targets_by_user: dict[
            int,
            list[ScheduleTargetDTO],
        ] = {}

    async def get_all_targets_for_user(
        self,
        *,
        user_id: int,
    ) -> list[ScheduleTargetDTO]:
        return list(
            self.targets_by_user.get(
                user_id,
                [],
            )
        )

    def find_target_by_selection_key(
        self,
        targets: list[ScheduleTargetDTO],
        selection_key: str,
    ) -> ScheduleTargetDTO | None:
        for target in targets:
            if target.selection_key == selection_key:
                return target

        return None


class FakeWatchTargetsService:
    """
    In-memory fake для whole-class star routes.

    Group-specific targets хранятся отдельно, но get_whole_class_target()
    намеренно возвращает только group_id=ALL.
    """

    def __init__(self) -> None:
        self.targets_by_owner: dict[
            int,
            list[ScheduleWatchTargetDTO],
        ] = {}
        self.next_target_id = 1000
        self.delete_calls: list[tuple[int, int]] = []

    async def get_whole_class_target(
        self,
        *,
        owner_user_id: int,
        class_id: str,
    ) -> ScheduleWatchTargetDTO | None:
        for target in self.targets_by_owner.get(
            owner_user_id,
            [],
        ):
            if (
                target.class_id == class_id
                and target.group_id == "ALL"
            ):
                return target

        return None

    async def add_target_from_school_dictionaries(
        self,
        *,
        owner_user_id: int,
        class_id: str,
        group_id: str,
        dictionaries: SchoolDictionariesDTO,
        title: str | None = None,
    ) -> ActionResponseDTO:
        if class_id not in dictionaries.classes:
            return ActionResponseDTO(
                success=False,
                error_code="invalid_class",
            )

        duplicate = await self.get_whole_class_target(
            owner_user_id=owner_user_id,
            class_id=class_id,
        )

        if duplicate is not None and group_id == "ALL":
            return ActionResponseDTO(
                success=False,
                error_code="duplicate",
            )

        target = ScheduleWatchTargetDTO(
            id=self.next_target_id,
            owner_user_id=owner_user_id,
            class_id=class_id,
            group_id=group_id,
            title=(
                title
                or dictionaries.get_readable_class(
                    class_id,
                )
            ),
        )

        self.next_target_id += 1

        self.targets_by_owner.setdefault(
            owner_user_id,
            [],
        ).append(target)

        return ActionResponseDTO(
            success=True,
            data=target,
        )

    async def delete_target(
        self,
        *,
        owner_user_id: int,
        target_id: int,
    ) -> ActionResponseDTO:
        targets = self.targets_by_owner.get(
            owner_user_id,
            [],
        )

        for index, target in enumerate(targets):
            if target.id != target_id:
                continue

            self.delete_calls.append(
                (
                    owner_user_id,
                    target_id,
                )
            )
            del targets[index]

            return ActionResponseDTO(success=True)

        return ActionResponseDTO(
            success=False,
            error_code="not_found",
        )


class FakeSchoolScheduleService:
    def __init__(
        self,
        dictionaries: SchoolDictionariesDTO,
    ) -> None:
        self.dictionaries = dictionaries

    async def get_school_dictionaries(
        self,
    ) -> SchoolDictionariesDTO:
        return self.dictionaries


@pytest.fixture
def web_session_context() -> WebSessionContext:
    return WebSessionContext(
        session_id=1,
        session_hash="test-session-hash",
        user_id=1001,
        csrf_token="test-csrf-token",
    )


@pytest.fixture
def web_test_app(
    web_session_context: WebSessionContext,
) -> FastAPI:
    """
    Small isolated route-test app.

    Здесь намеренно нет:
    - real sessions;
    - CSRF middleware;
    - gateway/rate limit middleware;
    - SQLite;
    - SSE;
    - NIKA network calls.

    require_family_allowed overridden, потому что эти tests проверяют
    route authorization по target list, cookie и HTML fragment contract.
    """
    app = FastAPI()

    app.state.templates = Jinja2Templates(
        directory=str(_TEMPLATES_DIR),
    )

    app.state.web_settings = SimpleNamespace(
        cookie_secure=False,
    )

    app.state.schedule_targets_service = (
        FakeScheduleTargetsService()
    )

    app.state.watch_targets_service = (
        FakeWatchTargetsService()
    )

    app.state.schedule_service = FakeSchoolScheduleService(
        SchoolDictionariesDTO(
            classes={
                "010": "10 А",
                "011": "11 А",
            },
            groups={
                "ENG": "Английский",
            },
        )
    )

    async def override_require_family_allowed():
        return web_session_context

    app.dependency_overrides[
        require_family_allowed
    ] = override_require_family_allowed

    app.include_router(schedule_router)
    app.include_router(school_router)

    return app


@pytest.fixture
def web_client(
    web_test_app: FastAPI,
) -> Iterator[TestClient]:
    with TestClient(web_test_app) as client:
        yield client