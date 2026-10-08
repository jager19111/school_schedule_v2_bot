from __future__ import annotations

import pytest
from aiosqlite import Connection

from core.models.dto import AuditAction
from core.repository.profile_repository import ProfileRepository
from services.profiles_service import ProfileService
from services.time_service import TimeService


@pytest.fixture
def profile_repository(
    sqlite_connection: Connection,
    time_service: TimeService,
) -> ProfileRepository:
    return ProfileRepository(
        db_path=sqlite_connection,
        time_service=time_service,
    )


async def _seed_family(
    connection: Connection,
    time_service: TimeService,
    *,
    family_id: int,
    family_code: str,
    admin_user_id: int,
) -> None:
    now_utc = time_service.now_utc_str()

    await connection.execute(
        """
        INSERT INTO families (
            id,
            family_code,
            admin_user_id,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            family_id,
            family_code,
            admin_user_id,
            now_utc,
            now_utc,
        ),
    )
    await connection.commit()


async def _add_user_to_family(
    connection: Connection,
    *,
    user_id: int,
    family_id: int,
) -> None:
    await connection.execute(
        """
        UPDATE users
        SET family_id = ?
        WHERE user_id = ?
        """,
        (
            family_id,
            user_id,
        ),
    )
    await connection.commit()


@pytest.mark.asyncio
async def test_fresh_schema_contains_family_invite_short_code(
    sqlite_connection: Connection,
) -> None:
    cursor = await sqlite_connection.execute(
        "PRAGMA table_info(family_invites)"
    )
    columns = {
        row["name"]
        for row in await cursor.fetchall()
    }

    index_cursor = await sqlite_connection.execute(
        "PRAGMA index_list(family_invites)"
    )
    indexes = {
        row["name"]
        for row in await index_cursor.fetchall()
    }

    assert "short_code" in columns
    assert "idx_family_invites_short_code" in indexes


@pytest.mark.asyncio
async def test_update_integer_setting_persists_changes_window_days(
    profile_repository: ProfileRepository,
    sqlite_connection: Connection,
    create_test_user,
) -> None:
    await create_test_user(
        user_id=101,
        role="child",
    )

    await profile_repository.update_integer_setting(
        user_id=101,
        field_name="changes_window_days",
        value=7,
    )

    cursor = await sqlite_connection.execute(
        """
        SELECT changes_window_days
        FROM users
        WHERE user_id = ?
        """,
        (101,),
    )
    row = await cursor.fetchone()

    assert row is not None
    assert row["changes_window_days"] == 7


@pytest.mark.asyncio
async def test_update_integer_setting_rejects_unknown_field(
    profile_repository: ProfileRepository,
    create_test_user,
) -> None:
    await create_test_user(
        user_id=102,
        role="child",
    )

    with pytest.raises(
        ValueError,
        match="Unsupported integer user field",
    ):
        await profile_repository.update_integer_setting(
            user_id=102,
            field_name="role",
            value=1,
        )


@pytest.mark.asyncio
async def test_transfer_family_admin_rejects_non_parent_successors(
    profile_repository: ProfileRepository,
    sqlite_connection: Connection,
    time_service: TimeService,
    create_test_user,
) -> None:
    await create_test_user(
        user_id=201,
        role="parent",
    )
    await create_test_user(
        user_id=202,
        role="observer",
    )
    await create_test_user(
        user_id=203,
        role="child",
    )
    await create_test_user(
        user_id=204,
        role="parent",
    )

    await _seed_family(
        sqlite_connection,
        time_service,
        family_id=10,
        family_code="TESTFAM10",
        admin_user_id=201,
    )

    await _add_user_to_family(
        sqlite_connection,
        user_id=201,
        family_id=10,
    )
    await _add_user_to_family(
        sqlite_connection,
        user_id=202,
        family_id=10,
    )
    await _add_user_to_family(
        sqlite_connection,
        user_id=203,
        family_id=10,
    )

    observer_result = await profile_repository.transfer_family_admin(
        from_user_id=201,
        to_user_id=202,
        family_id=10,
    )
    child_result = await profile_repository.transfer_family_admin(
        from_user_id=201,
        to_user_id=203,
        family_id=10,
    )
    external_parent_result = await profile_repository.transfer_family_admin(
        from_user_id=201,
        to_user_id=204,
        family_id=10,
    )

    cursor = await sqlite_connection.execute(
        """
        SELECT admin_user_id
        FROM families
        WHERE id = ?
        """,
        (10,),
    )
    row = await cursor.fetchone()

    assert observer_result is False
    assert child_result is False
    assert external_parent_result is False
    assert row is not None
    assert row["admin_user_id"] == 201


@pytest.mark.asyncio
async def test_transfer_family_admin_allows_parent_from_same_family(
    profile_repository: ProfileRepository,
    sqlite_connection: Connection,
    time_service: TimeService,
    create_test_user,
) -> None:
    await create_test_user(
        user_id=301,
        role="parent",
    )
    await create_test_user(
        user_id=302,
        role="parent",
    )

    await _seed_family(
        sqlite_connection,
        time_service,
        family_id=20,
        family_code="TESTFAM20",
        admin_user_id=301,
    )

    await _add_user_to_family(
        sqlite_connection,
        user_id=301,
        family_id=20,
    )
    await _add_user_to_family(
        sqlite_connection,
        user_id=302,
        family_id=20,
    )

    transferred = await profile_repository.transfer_family_admin(
        from_user_id=301,
        to_user_id=302,
        family_id=20,
    )

    cursor = await sqlite_connection.execute(
        """
        SELECT admin_user_id
        FROM families
        WHERE id = ?
        """,
        (20,),
    )
    row = await cursor.fetchone()

    assert transferred is True
    assert row is not None
    assert row["admin_user_id"] == 302


class _FailedTransferRepository:
    def __init__(self) -> None:
        self.disband_called = False

    async def get_profile_reset_impact(
        self,
        user_id: int,
    ) -> dict[str, object]:
        return {
            "user_id": user_id,
            "role": "parent",
            "family_id": 30,
            "is_family_admin": 1,
            "family_members_count": 2,
            "children_count": 0,
            "family_extra_classes_count": 0,
            "own_extra_classes_count": 0,
        }

    async def find_family_admin_successor(
        self,
        *,
        family_id: int,
        excluding_user_id: int,
    ) -> int:
        assert family_id == 30
        assert excluding_user_id == 401
        return 402

    async def transfer_family_admin(
        self,
        *,
        from_user_id: int,
        to_user_id: int,
        family_id: int,
    ) -> bool:
        assert from_user_id == 401
        assert to_user_id == 402
        assert family_id == 30
        return False

    async def disband_family_by_admin(
        self,
        *,
        admin_user_id: int,
    ) -> bool:
        self.disband_called = True
        return True


class _AuditSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    async def log_action(
        self,
        *args,
        **kwargs,
    ) -> None:
        self.calls.append((args, kwargs))


@pytest.mark.asyncio
async def test_failed_admin_transfer_does_not_disband_family() -> None:
    repository = _FailedTransferRepository()
    audit = _AuditSpy()
    service = ProfileService(
        repo=repository,
        audit_service=audit,
    )

    # ИСПРАВЛЕНИЕ: сохраняем ответ в одну переменную
    result = await service.reset_user_profile(
        user_id=401,
    )

    # ИСПРАВЛЕНИЕ: обращаемся к свойствам DTO
    assert result.success is False
    assert result.new_admin_user_id is None
    assert repository.disband_called is False
    assert audit.calls == []


class _ManualTransferRepository:
    def __init__(self) -> None:
        self.transfer_calls: list[dict[str, int]] = []

    async def get_user_profile_for_dto(
        self,
        user_id: int,
    ) -> dict[str, object]:
        if user_id == 501:
            return {
                "user_id": 501,
                "role": "parent",
                "family_id": 40,
            }

        if user_id == 502:
            return {
                "user_id": 502,
                "role": "parent",
                "family_id": 40,
            }

        raise AssertionError(f"Unexpected user_id: {user_id}")

    async def update_last_active(
        self,
        user_id: int,
    ) -> None:
        return None

    async def is_family_admin(
        self,
        *,
        user_id: int,
        family_id: int,
    ) -> bool:
        return user_id == 501 and family_id == 40

    async def transfer_family_admin(
        self,
        *,
        from_user_id: int,
        to_user_id: int,
        family_id: int,
    ) -> bool:
        self.transfer_calls.append(
            {
                "from_user_id": from_user_id,
                "to_user_id": to_user_id,
                "family_id": family_id,
            }
        )
        return True


@pytest.mark.asyncio
async def test_manual_admin_transfer_creates_audit_event() -> None:
    repository = _ManualTransferRepository()
    audit = _AuditSpy()
    service = ProfileService(
        repo=repository,
        audit_service=audit,
    )

    transferred = await service.transfer_family_admin(
        from_user_id=501,
        to_user_id=502,
    )

    assert transferred is True
    assert repository.transfer_calls == [
        {
            "from_user_id": 501,
            "to_user_id": 502,
            "family_id": 40,
        }
    ]

    assert len(audit.calls) == 1

    args, kwargs = audit.calls[0]

    assert args == ()
    assert kwargs["actor_id"] == 501
    assert kwargs["target_id"] == 502
    assert kwargs["action"] == AuditAction.FAMILY_ADMIN_TRANSFERRED
    assert kwargs["details"] == {
        "family_id": 40,
        "mode": "manual",
    }
    
    
@pytest.mark.asyncio
async def test_create_family_and_link_rejects_user_from_existing_family(
    profile_repository: ProfileRepository,
    sqlite_connection: Connection,
    time_service: TimeService,
    create_test_user,
) -> None:
    await create_test_user(
        user_id=601,
        role="parent",
    )

    await _seed_family(
        sqlite_connection,
        time_service,
        family_id=50,
        family_code="TESTFAM50",
        admin_user_id=601,
    )

    await _add_user_to_family(
        sqlite_connection,
        user_id=601,
        family_id=50,
    )

    with pytest.raises(
        ValueError,
        match="User already belongs to a family",
    ):
        await profile_repository.create_family_and_link(
            admin_user_id=601,
        )

    cursor = await sqlite_connection.execute(
        """
        SELECT
            family_id
        FROM users
        WHERE user_id = ?
        """,
        (601,),
    )
    user_row = await cursor.fetchone()

    families_cursor = await sqlite_connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM families
        """
    )
    families_row = await families_cursor.fetchone()

    assert user_row is not None
    assert user_row["family_id"] == 50
    assert families_row is not None
    assert families_row["count"] == 1
    
    
@pytest.mark.asyncio
async def test_link_user_to_family_rejects_cross_family_move(
    profile_repository: ProfileRepository,
    sqlite_connection: Connection,
    time_service: TimeService,
    create_test_user,
) -> None:
    await create_test_user(
        user_id=701,
        role="parent",
    )
    await create_test_user(
        user_id=702,
        role="parent",
    )

    await _seed_family(
        sqlite_connection,
        time_service,
        family_id=60,
        family_code="TESTFAM60",
        admin_user_id=701,
    )
    await _seed_family(
        sqlite_connection,
        time_service,
        family_id=61,
        family_code="TESTFAM61",
        admin_user_id=702,
    )

    await _add_user_to_family(
        sqlite_connection,
        user_id=701,
        family_id=60,
    )
    await _add_user_to_family(
        sqlite_connection,
        user_id=702,
        family_id=61,
    )

    with pytest.raises(
        ValueError,
        match="User already belongs to another family",
    ):
        await profile_repository.link_user_to_family(
            user_id=701,
            family_id=61,
            role="parent",
        )

    cursor = await sqlite_connection.execute(
        """
        SELECT
            family_id
        FROM users
        WHERE user_id = ?
        """,
        (701,),
    )
    row = await cursor.fetchone()

    assert row is not None
    assert row["family_id"] == 60
    
@pytest.mark.asyncio
async def test_link_user_to_family_is_idempotent_for_same_family(
    profile_repository: ProfileRepository,
    sqlite_connection: Connection,
    time_service: TimeService,
    create_test_user,
) -> None:
    await create_test_user(
        user_id=801,
        role="parent",
    )

    await _seed_family(
        sqlite_connection,
        time_service,
        family_id=70,
        family_code="TESTFAM70",
        admin_user_id=801,
    )

    await _add_user_to_family(
        sqlite_connection,
        user_id=801,
        family_id=70,
    )

    await profile_repository.link_user_to_family(
        user_id=801,
        family_id=70,
        role="observer",
    )

    cursor = await sqlite_connection.execute(
        """
        SELECT
            family_id,
            role
        FROM users
        WHERE user_id = ?
        """,
        (801,),
    )
    row = await cursor.fetchone()

    assert row is not None
    assert row["family_id"] == 70
    assert row["role"] == "parent"
    
    
@pytest.mark.asyncio
async def test_register_user_initial_reports_only_first_insert(
    profile_repository: ProfileRepository,
    sqlite_connection: Connection,
) -> None:
    created_first = await profile_repository.register_user_initial(
        user_id=901,
    )
    created_second = await profile_repository.register_user_initial(
        user_id=901,
    )

    cursor = await sqlite_connection.execute(
        """
        SELECT
            user_id,
            last_active_at
        FROM users
        WHERE user_id = ?
        """,
        (901,),
    )
    row = await cursor.fetchone()

    assert created_first is True
    assert created_second is False

    assert row is not None
    assert row["user_id"] == 901
    assert row["last_active_at"] is not None
    
    
@pytest.mark.asyncio
async def test_register_user_initial_audits_only_new_user(
    profile_repository: ProfileRepository,
) -> None:
    audit = _AuditSpy()

    service = ProfileService(
        repo=profile_repository,
        audit_service=audit,
    )

    await service.register_user_initial(
        user_id=902,
    )
    await service.register_user_initial(
        user_id=902,
    )

    assert len(audit.calls) == 1

    args, kwargs = audit.calls[0]

    assert args == ()
    assert kwargs["actor_id"] == 902
    assert kwargs["target_id"] == 902
    assert kwargs["action"] == AuditAction.USER_REGISTERED
    
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [
        "child",
        "observer",
        "teacher",
    ],
)
async def test_create_family_and_link_requires_parent_role(
    profile_repository: ProfileRepository,
    sqlite_connection: Connection,
    create_test_user,
    role: str,
) -> None:
    user_id = {
        "child": 1001,
        "observer": 1002,
        "teacher": 1003,
    }[role]

    await create_test_user(
        user_id=user_id,
        role=role,
    )

    with pytest.raises(
        ValueError,
        match="Only parent role can create a family",
    ):
        await profile_repository.create_family_and_link(
            admin_user_id=user_id,
        )

    family_cursor = await sqlite_connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM families
        """
    )
    family_row = await family_cursor.fetchone()

    user_cursor = await sqlite_connection.execute(
        """
        SELECT
            role,
            family_id
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    )
    user_row = await user_cursor.fetchone()

    assert family_row is not None
    assert family_row["count"] == 0

    assert user_row is not None
    assert user_row["role"] == role
    assert user_row["family_id"] is None
    
@pytest.mark.asyncio
async def test_reset_non_admin_profile_returns_success_dto(
    profile_repository: ProfileRepository,
    create_test_user,
) -> None:
    await create_test_user(
        user_id=1101,
        role="child",
    )

    audit = _AuditSpy()
    service = ProfileService(
        repo=profile_repository,
        audit_service=audit,
    )

    result = await service.reset_user_profile(
        user_id=1101,
    )

    # ИСПРАВЛЕНИЕ: проверяем атрибуты DTO по отдельности
    assert result.success is True
    assert result.new_admin_user_id is None
    assert result.family_disbanded is False
    
class _MissingUserResetRepository:
    async def get_profile_reset_impact(
        self,
        user_id: int,
    ) -> None:
        return None

    async def reset_non_admin_user(
        self,
        *,
        user_id: int,
    ) -> bool:
        return False


@pytest.mark.asyncio
async def test_reset_non_admin_failure_returns_false_dto() -> None:
    audit = _AuditSpy()

    service = ProfileService(
        repo=_MissingUserResetRepository(),
        audit_service=audit,
    )

    result = await service.reset_user_profile(
        user_id=1102,
    )

    # ИСПРАВЛЕНИЕ: проверяем атрибуты DTO по отдельности
    assert result.success is False
    assert result.new_admin_user_id is None
    assert result.family_disbanded is False
    assert audit.calls == []