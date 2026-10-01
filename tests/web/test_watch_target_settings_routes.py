from __future__ import annotations


from fastapi import FastAPI
from fastapi.testclient import TestClient


from core.models.dto import ScheduleWatchTargetDTO


ACTOR_USER_ID = 1001


def _watch_target(
    *,
    target_id: int,
    owner_user_id: int = ACTOR_USER_ID,
    is_enabled: bool = True,
    receive_schedule_changes: bool = True,
) -> ScheduleWatchTargetDTO:
    return ScheduleWatchTargetDTO(
        id=target_id,
        owner_user_id=owner_user_id,
        class_id="010",
        group_id="ALL",
        title="10 А",
        is_enabled=is_enabled,
        receive_schedule_changes=receive_schedule_changes,
    )


def _set_targets(
    app: FastAPI,
    *targets: ScheduleWatchTargetDTO,
) -> None:
    app.state.watch_targets_service.targets_by_owner[
        ACTOR_USER_ID
    ] = list(targets)


def test_pause_watch_target_updates_state_and_renders_list(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    target = _watch_target(
        target_id=901,
        is_enabled=True,
    )
    _set_targets(
        web_test_app,
        target,
    )

    response = web_client.post(
        "/settings/watch-targets/901/enabled",
        data={
            "is_enabled": "false",
        },
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 200
    assert target.is_enabled is False

    assert "⚫ Пауза" in response.text
    assert "Включить" in response.text
    assert 'aria-pressed="false"' in response.text


def test_resume_watch_target_updates_state_and_renders_list(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    target = _watch_target(
        target_id=902,
        is_enabled=False,
    )
    _set_targets(
        web_test_app,
        target,
    )

    response = web_client.post(
        "/settings/watch-targets/902/enabled",
        data={
            "is_enabled": "true",
        },
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 200
    assert target.is_enabled is True

    assert "🟢 Активно" in response.text
    assert "Пауза" in response.text
    assert 'aria-pressed="true"' in response.text


def test_disable_changes_notifications_updates_state(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    target = _watch_target(
        target_id=903,
        receive_schedule_changes=True,
    )
    _set_targets(
        web_test_app,
        target,
    )

    response = web_client.post(
        "/settings/watch-targets/"
        "903/changes-notifications",
        data={
            "receive_schedule_changes": "false",
        },
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 200
    assert target.receive_schedule_changes is False

    assert "🔕 Выключены" in response.text
    assert "Изменения: вкл" in response.text
    assert 'aria-pressed="false"' in response.text


def test_enable_changes_notifications_updates_state(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    target = _watch_target(
        target_id=904,
        receive_schedule_changes=False,
    )
    _set_targets(
        web_test_app,
        target,
    )

    response = web_client.post(
        "/settings/watch-targets/"
        "904/changes-notifications",
        data={
            "receive_schedule_changes": "true",
        },
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 200
    assert target.receive_schedule_changes is True

    assert "🔔 Включены" in response.text
    assert "Изменения: выкл" in response.text
    assert 'aria-pressed="true"' in response.text


def test_foreign_target_enabled_change_returns_alert(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    foreign_target = _watch_target(
        target_id=905,
        owner_user_id=2002,
        is_enabled=True,
    )

    web_test_app.state.watch_targets_service.targets_by_owner[
        2002
    ] = [foreign_target]

    response = web_client.post(
        "/settings/watch-targets/905/enabled",
        data={
            "is_enabled": "false",
        },
        headers={
            "HX-Request": "true",
        },
    )

    assert response.status_code == 200
    assert foreign_target.is_enabled is True

    assert (
        "Отслеживаемый класс уже удалён "
        "или недоступен."
        in response.text
    )


def test_deleted_target_notifications_change_returns_alert(
    web_client: TestClient,
):
    response = web_client.post(
        "/settings/watch-targets/"
        "906/changes-notifications",
        data={
            "receive_schedule_changes": "false",
        },
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


def test_enabled_change_without_htmx_redirects_to_settings_list(
    web_client: TestClient,
    web_test_app: FastAPI,
):
    target = _watch_target(
        target_id=907,
        is_enabled=True,
    )
    _set_targets(
        web_test_app,
        target,
    )

    response = web_client.post(
        "/settings/watch-targets/907/enabled",
        data={
            "is_enabled": "false",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/settings/watch-targets"
    )
    assert target.is_enabled is False