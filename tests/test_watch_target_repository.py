from __future__ import annotations


import asyncio


import pytest


from core.repository.watch_target_repository import (
    WatchTargetRepository,
)


MAX_TARGETS = 10


@pytest.mark.asyncio
async def test_create_watch_target_with_limit_creates_target(
    create_test_user,
    watch_target_repository: WatchTargetRepository,
):
    await create_test_user(user_id=1001)

    result = (
        await watch_target_repository.create_watch_target_with_limit(
            owner_user_id=1001,
            class_id="001",
            group_id="ALL",
            title="1 А",
            max_targets=MAX_TARGETS,
        )
    )

    assert result.error_code is None
    assert result.target is not None

    target = result.target

    assert target.owner_user_id == 1001
    assert target.class_id == "001"
    assert target.group_id == "ALL"
    assert target.title == "1 А"
    assert target.is_enabled is True
    assert target.receive_schedule_changes is True


@pytest.mark.asyncio
async def test_create_watch_target_with_limit_returns_duplicate(
    create_test_user,
    watch_target_repository: WatchTargetRepository,
):
    await create_test_user(user_id=1002)

    first = (
        await watch_target_repository.create_watch_target_with_limit(
            owner_user_id=1002,
            class_id="001",
            group_id="ALL",
            title="1 А",
            max_targets=MAX_TARGETS,
        )
    )

    second = (
        await watch_target_repository.create_watch_target_with_limit(
            owner_user_id=1002,
            class_id="001",
            group_id="ALL",
            title="1 А",
            max_targets=MAX_TARGETS,
        )
    )

    assert first.error_code is None
    assert first.target is not None

    assert second.target is None
    assert second.error_code == "duplicate"


@pytest.mark.asyncio
async def test_create_watch_target_with_limit_returns_limit_reached(
    create_test_user,
    watch_target_repository: WatchTargetRepository,
):
    await create_test_user(user_id=1003)

    for index in range(MAX_TARGETS):
        result = (
            await watch_target_repository.create_watch_target_with_limit(
                owner_user_id=1003,
                class_id=f"class-{index}",
                group_id="ALL",
                title=f"Класс {index}",
                max_targets=MAX_TARGETS,
            )
        )

        assert result.error_code is None
        assert result.target is not None

    result = (
        await watch_target_repository.create_watch_target_with_limit(
            owner_user_id=1003,
            class_id="class-over-limit",
            group_id="ALL",
            title="Лишний класс",
            max_targets=MAX_TARGETS,
        )
    )

    assert result.target is None
    assert result.error_code == "limit_reached"

    targets = await watch_target_repository.get_watch_targets(
        owner_user_id=1003,
    )

    assert len(targets) == MAX_TARGETS


@pytest.mark.asyncio
async def test_create_watch_target_with_limit_is_atomic_for_parallel_requests(
    create_test_user,
    watch_target_repository: WatchTargetRepository,
):
    """
    Regression test race condition.

    При девяти existing targets два параллельных request пытаются
    создать разные десятые цели. Создаться может строго одна.
    """
    await create_test_user(user_id=1004)

    for index in range(MAX_TARGETS - 1):
        result = (
            await watch_target_repository.create_watch_target_with_limit(
                owner_user_id=1004,
                class_id=f"class-{index}",
                group_id="ALL",
                title=f"Класс {index}",
                max_targets=MAX_TARGETS,
            )
        )

        assert result.error_code is None

    results = await asyncio.gather(
        watch_target_repository.create_watch_target_with_limit(
            owner_user_id=1004,
            class_id="parallel-class-a",
            group_id="ALL",
            title="Параллельный А",
            max_targets=MAX_TARGETS,
        ),
        watch_target_repository.create_watch_target_with_limit(
            owner_user_id=1004,
            class_id="parallel-class-b",
            group_id="ALL",
            title="Параллельный Б",
            max_targets=MAX_TARGETS,
        ),
    )

    created = [
        result
        for result in results
        if result.target is not None
    ]

    limited = [
        result
        for result in results
        if result.error_code == "limit_reached"
    ]

    assert len(created) == 1
    assert len(limited) == 1

    targets = await watch_target_repository.get_watch_targets(
        owner_user_id=1004,
    )

    assert len(targets) == MAX_TARGETS


@pytest.mark.asyncio
async def test_get_watch_targets_enabled_only_filters_paused_target(
    create_test_user,
    watch_target_repository: WatchTargetRepository,
):
    await create_test_user(user_id=1005)

    active_result = (
        await watch_target_repository.create_watch_target_with_limit(
            owner_user_id=1005,
            class_id="001",
            group_id="ALL",
            title="1 А",
            max_targets=MAX_TARGETS,
        )
    )

    paused_result = (
        await watch_target_repository.create_watch_target_with_limit(
            owner_user_id=1005,
            class_id="002",
            group_id="ALL",
            title="2 А",
            max_targets=MAX_TARGETS,
        )
    )

    assert active_result.target is not None
    assert paused_result.target is not None

    updated = await watch_target_repository.set_watch_target_enabled(
        owner_user_id=1005,
        target_id=paused_result.target.id,
        is_enabled=False,
    )

    assert updated is True

    all_targets = await watch_target_repository.get_watch_targets(
        owner_user_id=1005,
        enabled_only=False,
    )

    enabled_targets = await watch_target_repository.get_watch_targets(
        owner_user_id=1005,
        enabled_only=True,
    )

    assert len(all_targets) == 2
    assert len(enabled_targets) == 1
    assert enabled_targets[0].id == active_result.target.id


@pytest.mark.asyncio
async def test_delete_watch_target_rejects_foreign_owner(
    create_test_user,
    watch_target_repository: WatchTargetRepository,
):
    await create_test_user(user_id=1006)
    await create_test_user(user_id=1007)

    result = (
        await watch_target_repository.create_watch_target_with_limit(
            owner_user_id=1006,
            class_id="001",
            group_id="ALL",
            title="1 А",
            max_targets=MAX_TARGETS,
        )
    )

    assert result.target is not None

    deleted = await watch_target_repository.delete_watch_target(
        owner_user_id=1007,
        target_id=result.target.id,
    )

    assert deleted is False

    target = await watch_target_repository.get_watch_target(
        owner_user_id=1006,
        target_id=result.target.id,
    )

    assert target is not None