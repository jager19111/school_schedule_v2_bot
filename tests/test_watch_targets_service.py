from __future__ import annotations


import pytest


from core.models.dto import SchoolDictionariesDTO
from services.watch_targets_service import (
    MAX_TARGETS_PER_USER,
    WatchTargetsService,
)


@pytest.fixture
def school_dictionaries() -> SchoolDictionariesDTO:
    return SchoolDictionariesDTO(
        classes={
            "001": "1 А",
            "002": "2 А",
            "010": "10 А",
        },
        groups={
            "ENG": "Английский",
            "INF": "Информатика",
        },
    )


@pytest.mark.asyncio
async def test_add_target_creates_whole_class_target(
    create_test_user,
    watch_targets_service: WatchTargetsService,
    school_dictionaries: SchoolDictionariesDTO,
):
    await create_test_user(user_id=2001)

    response = (
        await watch_targets_service.add_target_from_school_dictionaries(
            owner_user_id=2001,
            class_id="001",
            group_id="ALL",
            dictionaries=school_dictionaries,
        )
    )

    assert response.success is True
    assert response.error_code is None
    assert response.data is not None

    target = response.data

    assert target.class_id == "001"
    assert target.group_id == "ALL"
    assert target.title == "1 А"


@pytest.mark.asyncio
async def test_add_target_rejects_unknown_class(
    create_test_user,
    watch_targets_service: WatchTargetsService,
    school_dictionaries: SchoolDictionariesDTO,
):
    await create_test_user(user_id=2002)

    response = (
        await watch_targets_service.add_target_from_school_dictionaries(
            owner_user_id=2002,
            class_id="unknown-class",
            group_id="ALL",
            dictionaries=school_dictionaries,
        )
    )

    assert response.success is False
    assert response.error_code == "invalid_class"


@pytest.mark.asyncio
async def test_add_target_rejects_unknown_group(
    create_test_user,
    watch_targets_service: WatchTargetsService,
    school_dictionaries: SchoolDictionariesDTO,
):
    await create_test_user(user_id=2003)

    response = (
        await watch_targets_service.add_target_from_school_dictionaries(
            owner_user_id=2003,
            class_id="001",
            group_id="unknown-group",
            dictionaries=school_dictionaries,
        )
    )

    assert response.success is False
    assert response.error_code == "invalid_group"


@pytest.mark.asyncio
async def test_add_target_rejects_all_mixed_with_specific_group(
    create_test_user,
    watch_targets_service: WatchTargetsService,
    school_dictionaries: SchoolDictionariesDTO,
):
    await create_test_user(user_id=2004)

    response = (
        await watch_targets_service.add_target_from_school_dictionaries(
            owner_user_id=2004,
            class_id="001",
            group_id="ALL,ENG",
            dictionaries=school_dictionaries,
        )
    )

    assert response.success is False
    assert response.error_code == "invalid_group"


@pytest.mark.asyncio
async def test_add_target_allows_same_class_with_different_group(
    create_test_user,
    watch_targets_service: WatchTargetsService,
    school_dictionaries: SchoolDictionariesDTO,
):
    await create_test_user(user_id=2005)

    whole_class_response = (
        await watch_targets_service.add_target_from_school_dictionaries(
            owner_user_id=2005,
            class_id="001",
            group_id="ALL",
            dictionaries=school_dictionaries,
        )
    )

    group_response = (
        await watch_targets_service.add_target_from_school_dictionaries(
            owner_user_id=2005,
            class_id="001",
            group_id="ENG",
            dictionaries=school_dictionaries,
        )
    )

    assert whole_class_response.success is True
    assert group_response.success is True

    targets = await watch_targets_service.get_targets(
        owner_user_id=2005,
    )

    assert len(targets) == 2
    assert {
        target.group_id
        for target in targets
    } == {
        "ALL",
        "ENG",
    }


@pytest.mark.asyncio
async def test_add_target_returns_duplicate_for_same_class_and_group(
    create_test_user,
    watch_targets_service: WatchTargetsService,
    school_dictionaries: SchoolDictionariesDTO,
):
    await create_test_user(user_id=2006)

    first = (
        await watch_targets_service.add_target_from_school_dictionaries(
            owner_user_id=2006,
            class_id="001",
            group_id="ENG",
            dictionaries=school_dictionaries,
        )
    )

    duplicate = (
        await watch_targets_service.add_target_from_school_dictionaries(
            owner_user_id=2006,
            class_id="001",
            group_id="ENG",
            dictionaries=school_dictionaries,
        )
    )

    assert first.success is True
    assert duplicate.success is False
    assert duplicate.error_code == "duplicate"


@pytest.mark.asyncio
async def test_get_whole_class_target_ignores_group_specific_target(
    create_test_user,
    watch_targets_service: WatchTargetsService,
    school_dictionaries: SchoolDictionariesDTO,
):
    await create_test_user(user_id=2007)

    response = (
        await watch_targets_service.add_target_from_school_dictionaries(
            owner_user_id=2007,
            class_id="001",
            group_id="ENG",
            dictionaries=school_dictionaries,
        )
    )

    assert response.success is True

    whole_class_target = (
        await watch_targets_service.get_whole_class_target(
            owner_user_id=2007,
            class_id="001",
        )
    )

    assert whole_class_target is None


@pytest.mark.asyncio
async def test_get_whole_class_target_returns_all_target(
    create_test_user,
    watch_targets_service: WatchTargetsService,
    school_dictionaries: SchoolDictionariesDTO,
):
    await create_test_user(user_id=2008)

    response = (
        await watch_targets_service.add_target_from_school_dictionaries(
            owner_user_id=2008,
            class_id="001",
            group_id="ALL",
            dictionaries=school_dictionaries,
        )
    )

    assert response.success is True

    whole_class_target = (
        await watch_targets_service.get_whole_class_target(
            owner_user_id=2008,
            class_id="001",
        )
    )

    assert whole_class_target is not None
    assert whole_class_target.group_id == "ALL"


@pytest.mark.asyncio
async def test_add_target_respects_limit(
    create_test_user,
    watch_targets_service: WatchTargetsService,
):
    await create_test_user(user_id=2009)

    classes = {
        f"class-{index}": f"Класс {index}"
        for index in range(MAX_TARGETS_PER_USER + 1)
    }

    dictionaries = SchoolDictionariesDTO(
        classes=classes,
        groups={},
    )

    for index in range(MAX_TARGETS_PER_USER):
        response = (
            await watch_targets_service.add_target_from_school_dictionaries(
                owner_user_id=2009,
                class_id=f"class-{index}",
                group_id="ALL",
                dictionaries=dictionaries,
            )
        )

        assert response.success is True

    limit_response = (
        await watch_targets_service.add_target_from_school_dictionaries(
            owner_user_id=2009,
            class_id=f"class-{MAX_TARGETS_PER_USER}",
            group_id="ALL",
            dictionaries=dictionaries,
        )
    )

    assert limit_response.success is False
    assert limit_response.error_code == "limit_reached"