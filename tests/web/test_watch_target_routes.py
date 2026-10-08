from __future__ import annotations


from fastapi import FastAPI
from fastapi.testclient import TestClient


from core.models.dto import (
    ScheduleTargetDTO,
    ScheduleTargetKind,
    ScheduleWatchTargetDTO,
)


ACTOR_USER_ID = 1001


def _student_target(
    *,
    student_id: int,
) -> ScheduleTargetDTO:
    return ScheduleTargetDTO(
        kind=ScheduleTargetKind.STUDENT,
        selection_key=(
            ScheduleTargetKind.STUDENT.build_selection_key(
                student_id,
            )
        ),
        name=f"Ученик {student_id}",
        student_id=student_id,
        class_id="010",
        group_id="ALL",
    )


def _watch_target(
    *,
    target_id: int,
) -> ScheduleTargetDTO:
    return ScheduleTargetDTO(
        kind=ScheduleTargetKind.WATCH,
        selection_key=(
            ScheduleTargetKind.WATCH.build_selection_key(
                target_id,
            )
        ),
        name="10 А",
        student_id=None,
        class_id="010",
        group_id="ALL",
        watch_target_id=target_id,
    )


def test_select_student_sets_typed_cookie_and_triggers_revalidate(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    target = _student_target(student_id=501)

    web_test_app.state.schedule_targets_service.targets_by_user[
        ACTOR_USER_ID
    ] = [target]

    response = web_client.post(
        "/api/v1/schedule/select/student/501"
        "?next_url=/schedule/week",
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 200
    
    # ИСПРАВЛЕНИЕ: Проверяем триггер вместо редиректа
    assert response.headers["hx-trigger"] == "schedule:revalidate"

    assert response.cookies.get(
        "web_schedule_target",
    ) == "student:501"

    set_cookie_headers = response.headers.get_list(
        "set-cookie",
    )

    assert any(
        header.startswith("web_student=")
        for header in set_cookie_headers
    )


def test_select_watch_target_sets_typed_cookie(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    target = _watch_target(target_id=701)

    web_test_app.state.schedule_targets_service.targets_by_user[
        ACTOR_USER_ID
    ] = [target]

    response = web_client.post(
        "/api/v1/schedule/select/watch/701",
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 200
    
    # ИСПРАВЛЕНИЕ: Проверяем триггер вместо редиректа
    assert response.headers["hx-trigger"] == "schedule:revalidate"

    assert response.cookies.get(
        "web_schedule_target",
    ) == "watch:701"
    
def test_select_foreign_watch_target_returns_403(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    foreign_target = _watch_target(target_id=702)

    web_test_app.state.schedule_targets_service.targets_by_user[
        2002
    ] = [foreign_target]

    response = web_client.post(
        "/api/v1/schedule/select/watch/702",
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Отслеживаемый класс недоступен."
    )


def test_select_disabled_watch_target_returns_403(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    """
    Disabled target отсутствует в get_all_targets_for_user().
    Route получает тот же безопасный 403, что и для foreign target.
    """
    response = web_client.post(
        "/api/v1/schedule/select/watch/703",
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Отслеживаемый класс недоступен."
    )


def test_legacy_student_selection_writes_typed_cookie(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    target = _student_target(student_id=502)

    web_test_app.state.schedule_targets_service.targets_by_user[
        ACTOR_USER_ID
    ] = [target]

    response = web_client.post(
        "/api/v1/schedule/select/502",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"

    assert response.cookies.get(
        "web_schedule_target",
    ) == "student:502"


def test_star_add_returns_delete_url_with_real_class_id(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    response = web_client.post(
        "/school/class/010/watch",
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 200

    assert (
        'hx-post="/school/class/010/watch/delete"'
        in response.text
    )

def test_star_delete_returns_add_url_with_real_class_id(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    whole_class_target = ScheduleWatchTargetDTO(
        id=801,
        owner_user_id=ACTOR_USER_ID,
        class_id="010",
        group_id="ALL",
        title="10 А",
    )

    web_test_app.state.watch_targets_service.targets_by_owner[
        ACTOR_USER_ID
    ] = [whole_class_target]

    response = web_client.post(
        "/school/class/010/watch/delete",
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 200

    assert (
        'hx-post="/school/class/010/watch"'
        in response.text
    )

    assert "/school/class//watch" not in response.text

    assert (
        web_test_app.state.watch_targets_service
        .targets_by_owner[ACTOR_USER_ID]
        == []
    )


def test_star_delete_does_not_remove_group_specific_target(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    group_target = ScheduleWatchTargetDTO(
        id=802,
        owner_user_id=ACTOR_USER_ID,
        class_id="010",
        group_id="ENG",
        title="10 А",
    )

    web_test_app.state.watch_targets_service.targets_by_owner[
        ACTOR_USER_ID
    ] = [group_target]

    response = web_client.post(
        "/school/class/010/watch/delete",
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 200

    assert (
        "Отслеживаемый класс уже удалён "
        "или недоступен."
        in response.text
    )

    stored_targets = (
        web_test_app.state.watch_targets_service
        .targets_by_owner[ACTOR_USER_ID]
    )

    assert stored_targets == [group_target]

    assert (
        web_test_app.state.watch_targets_service.delete_calls
        == []
    )