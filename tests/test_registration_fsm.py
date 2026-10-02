from __future__ import annotations

import pytest
from types import SimpleNamespace

from bot.handlers.registration import (
    FSM_FAMILY_INVITE_ACTOR_USER_ID,
    FSM_FAMILY_INVITE_TOKEN,
    FSM_INVITED_ROLE,
    FSM_PENDING_INVITE_NAME,
    _FamilyInviteFSMContext,
    _store_family_invite_context,
    FSM_CLAIM_ACTOR_USER_ID,
    FSM_CLAIM_TOKEN,
    _store_student_claim_context,
    _read_registration_role,
    RegistrationStates,
    _start_family_invite_from_deep_link,
    _start_student_claim_from_deep_link,
    _complete_child_family_invite_registration,
    _complete_standalone_child_registration,
)
from core.models.dto import (
    FamilyInviteDTO,
    SchoolDictionariesDTO,
    StudentClaimInviteDTO,
    UserProfileDTO,
)

class _FakeState:
    def __init__(
        self,
        initial_data: dict[str, object] | None = None,
    ) -> None:
        self.data = dict(initial_data or {})
        self.clear_calls = 0
        self.current_state = None

    async def clear(self) -> None:
        self.clear_calls += 1
        self.data.clear()
        self.current_state = None

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def set_state(self, state) -> None:
        self.current_state = state

@pytest.mark.asyncio
async def test_store_family_invite_context_resets_stale_fsm_data() -> None:
    state = _FakeState(
        {
            "claim_token": "old-claim",
            "class_id": "016",
            FSM_PENDING_INVITE_NAME: "Старое имя",
        }
    )

    await _store_family_invite_context(
        state,
        token="new-family-token",
        role="child",
        actor_user_id=101,
        reset_existing_state=True,
    )

    assert state.clear_calls == 1
    assert state.data == {
        FSM_FAMILY_INVITE_TOKEN: "new-family-token",
        FSM_INVITED_ROLE: "child",
        FSM_FAMILY_INVITE_ACTOR_USER_ID: 101,
    }


@pytest.mark.asyncio
async def test_store_family_invite_context_adds_pending_name_without_reset() -> None:
    state = _FakeState(
        {
            FSM_FAMILY_INVITE_TOKEN: "family-token",
            FSM_INVITED_ROLE: "child",
            FSM_FAMILY_INVITE_ACTOR_USER_ID: 202,
            "class_id": "016",
        }
    )

    await _store_family_invite_context(
        state,
        token="family-token",
        role="child",
        actor_user_id=202,
        pending_name="Мария",
    )

    assert state.clear_calls == 0
    assert state.data == {
        FSM_FAMILY_INVITE_TOKEN: "family-token",
        FSM_INVITED_ROLE: "child",
        FSM_FAMILY_INVITE_ACTOR_USER_ID: 202,
        FSM_PENDING_INVITE_NAME: "Мария",
        "class_id": "016",
    }
    
def test_family_invite_fsm_context_returns_none_without_invite_token() -> None:
    context = _FamilyInviteFSMContext.from_fsm_data(
        {
            "role": "child",
            "class_id": "016",
        }
    )

    assert context is None
    
def test_family_invite_fsm_context_parses_valid_data() -> None:
    context = _FamilyInviteFSMContext.from_fsm_data(
        {
            FSM_FAMILY_INVITE_TOKEN: "family-invite-token",
            FSM_INVITED_ROLE: "child",
            FSM_FAMILY_INVITE_ACTOR_USER_ID: 101,
            FSM_PENDING_INVITE_NAME: "Мария",
            "class_id": "016",
        }
    )

    assert context is not None
    assert context.token == "family-invite-token"
    assert context.role == "child"
    assert context.actor_user_id == 101
    assert context.pending_name == "Мария"
    
@pytest.mark.parametrize(
    "data",
    [
        {
            FSM_FAMILY_INVITE_TOKEN: "",
            FSM_INVITED_ROLE: "child",
            FSM_FAMILY_INVITE_ACTOR_USER_ID: 101,
        },
        {
            FSM_FAMILY_INVITE_TOKEN: "token",
            FSM_INVITED_ROLE: "admin",
            FSM_FAMILY_INVITE_ACTOR_USER_ID: 101,
        },
        {
            FSM_FAMILY_INVITE_TOKEN: "token",
            FSM_INVITED_ROLE: "child",
            FSM_FAMILY_INVITE_ACTOR_USER_ID: "101",
        },
        {
            FSM_FAMILY_INVITE_TOKEN: "token",
            FSM_INVITED_ROLE: "child",
            FSM_FAMILY_INVITE_ACTOR_USER_ID: True,
        },
    ],
)
def test_family_invite_fsm_context_rejects_corrupted_data(
    data: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _FamilyInviteFSMContext.from_fsm_data(data)
        
        
        
@pytest.mark.asyncio
async def test_store_student_claim_context_clears_previous_flow_data() -> None:
    state = _FakeState(
        {
            FSM_FAMILY_INVITE_TOKEN: "old-family-token",
            FSM_INVITED_ROLE: "child",
            FSM_FAMILY_INVITE_ACTOR_USER_ID: 101,
            FSM_PENDING_INVITE_NAME: "Старое имя",
            "class_id": "016",
            "claim_student_id": 77,
        }
    )

    await _store_student_claim_context(
        state,
        token="new-claim-token",
        actor_user_id=202,
    )

    assert state.clear_calls == 1
    assert state.data == {
        FSM_CLAIM_TOKEN: "new-claim-token",
        FSM_CLAIM_ACTOR_USER_ID: 202,
    }
    
@pytest.mark.asyncio
async def test_store_student_claim_context_keeps_only_token_and_actor() -> None:
    state = _FakeState()

    await _store_student_claim_context(
        state,
        token="claim-token",
        actor_user_id=303,
    )

    assert state.data == {
        FSM_CLAIM_TOKEN: "claim-token",
        FSM_CLAIM_ACTOR_USER_ID: 303,
    }

    assert "claim_student_id" not in state.data
    assert "claim_source_student_id" not in state.data
    
    
@pytest.mark.parametrize(
    "role",
    [
        "child",
        "parent",
        "observer",
        "teacher",
    ],
)
def test_read_registration_role_accepts_supported_roles(
    role: str,
) -> None:
    assert _read_registration_role({"role": role}) == role
    
    
@pytest.mark.parametrize(
    "data",
    [
        {},
        {"role": None},
        {"role": ""},
        {"role": "admin"},
        {"role": 1},
        {"role": True},
    ],
)
def test_read_registration_role_rejects_invalid_values(
    data: dict[str, object],
) -> None:
    assert _read_registration_role(data) is None
    
    
    
class _FakeMessage:
    def __init__(self) -> None:
        self.answers: list[dict[str, object]] = []
        self.delete_calls = 0

    async def answer(
        self,
        text: str,
        **kwargs: object,
    ) -> None:
        self.answers.append(
            {
                "text": text,
                **kwargs,
            }
        )

    async def delete(self) -> None:
        self.delete_calls += 1

class _FakeCallback:
    def __init__(
        self,
        *,
        user_id: int,
    ) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.message = _FakeMessage()
        self.answers: list[dict[str, object]] = []

    async def answer(
        self,
        text: str | None = None,
        **kwargs: object,
    ) -> None:
        self.answers.append(
            {
                "text": text,
                **kwargs,
            }
        )
        
class _ClaimStudentsService:
    def __init__(
        self,
        *,
        invite: StudentClaimInviteDTO | None,
        current_student: object | None,
    ) -> None:
        self.invite = invite
        self.current_student = current_student
        self.claim_tokens: list[str] = []
        self.student_user_ids: list[int] = []

    async def get_valid_student_claim_invite(
        self,
        *,
        token: str,
    ) -> StudentClaimInviteDTO | None:
        self.claim_tokens.append(token)
        return self.invite

    async def get_student_by_telegram_user_id(
        self,
        *,
        telegram_user_id: int,
    ) -> object | None:
        self.student_user_ids.append(telegram_user_id)
        return self.current_student


class _FakeScheduleService:
    def __init__(self) -> None:
        self.calls = 0

    async def get_school_dictionaries(self) -> SchoolDictionariesDTO:
        self.calls += 1

        return SchoolDictionariesDTO(
            classes={
                "016": "10А",
            },
            groups={
                "ALL": "Весь класс",
                "0": "Группа 1",
            },
        )


class _FamilyInviteProfileService:
    def __init__(
        self,
        invite: FamilyInviteDTO | None,
    ) -> None:
        self.invite = invite
        self.tokens: list[str] = []

    async def get_valid_family_invite(
        self,
        *,
        token: str,
    ) -> FamilyInviteDTO | None:
        self.tokens.append(token)
        return self.invite
    
    
@pytest.mark.asyncio
async def test_claim_deep_link_stores_minimal_context_and_opens_confirmation() -> None:
    message = _FakeMessage()
    state = _FakeState(
        {
            FSM_FAMILY_INVITE_TOKEN: "stale-family-token",
            "class_id": "016",
        }
    )

    invite = StudentClaimInviteDTO(
        id=1,
        token="claim-token",
        student_id=11,
        family_id=5,
        created_by_user_id=700,
        expires_at="2026-10-03 12:00:00",
        student_name="Мария",
        student_class_id="016",
        student_group_id="ALL",
    )

    students_service = _ClaimStudentsService(
        invite=invite,
        current_student=None,
    )
    schedule_service = _FakeScheduleService()

    user_dto = UserProfileDTO(
        user_id=101,
        role="child",
        is_fully_registered=False,
        family_id=None,
    )

    await _start_student_claim_from_deep_link(
        message,
        token="claim-token",
        user_id=101,
        user_dto=user_dto,
        state=state,
        students_service=students_service,
        schedule_service=schedule_service,
    )

    assert students_service.claim_tokens == ["claim-token"]
    assert students_service.student_user_ids == [101]
    assert schedule_service.calls == 1

    assert state.clear_calls == 1
    assert state.data == {
        FSM_CLAIM_TOKEN: "claim-token",
        FSM_CLAIM_ACTOR_USER_ID: 101,
    }
    assert (
        state.current_state
        == RegistrationStates.waiting_for_claim_confirmation
    )

    assert len(message.answers) == 1
    assert message.answers[0]["parse_mode"] == "HTML"
    assert "Мария" in str(message.answers[0]["text"])
    
@pytest.mark.asyncio
async def test_claim_deep_link_rejects_user_already_in_family_before_lookup() -> None:
    message = _FakeMessage()
    state = _FakeState()

    students_service = _ClaimStudentsService(
        invite=None,
        current_student=None,
    )
    schedule_service = _FakeScheduleService()

    user_dto = UserProfileDTO(
        user_id=102,
        role="child",
        is_fully_registered=True,
        family_id=50,
    )

    await _start_student_claim_from_deep_link(
        message,
        token="claim-token",
        user_id=102,
        user_dto=user_dto,
        state=state,
        students_service=students_service,
        schedule_service=schedule_service,
    )

    assert students_service.claim_tokens == []
    assert students_service.student_user_ids == []
    assert schedule_service.calls == 0

    assert state.clear_calls == 1
    assert state.data == {}
    assert state.current_state is None

    assert len(message.answers) == 1
    assert "уже состоите в семье" in str(
        message.answers[0]["text"]
    )
    
@pytest.mark.asyncio
async def test_family_invite_deep_link_allows_standalone_child() -> None:
    message = _FakeMessage()
    state = _FakeState(
        {
            FSM_CLAIM_TOKEN: "stale-claim-token",
        }
    )

    user_dto = UserProfileDTO(
        user_id=201,
        role="child",
        is_fully_registered=True,
        family_id=None,
    )

    current_student = SimpleNamespace(
        id=31,
        family_id=None,
        is_active=True,
    )

    invite = FamilyInviteDTO(
        id=2,
        token="family-invite-token",
        family_id=77,
        intended_role="child",
        expires_at="2026-10-03 12:00:00",
        max_uses=1,
    )

    profile_service = _FamilyInviteProfileService(
        invite=invite,
    )
    students_service = _ClaimStudentsService(
        invite=None,
        current_student=current_student,
    )

    await _start_family_invite_from_deep_link(
        message,
        token="family-invite-token",
        user_id=201,
        user_dto=user_dto,
        state=state,
        profile_service=profile_service,
        students_service=students_service,
    )

    assert students_service.student_user_ids == [201]
    assert profile_service.tokens == ["family-invite-token"]

    assert state.clear_calls == 1
    assert state.data == {
        FSM_FAMILY_INVITE_TOKEN: "family-invite-token",
        FSM_INVITED_ROLE: "child",
        FSM_FAMILY_INVITE_ACTOR_USER_ID: 201,
    }
    assert state.current_state == RegistrationStates.waiting_for_name

    assert len(message.answers) == 1
    assert message.answers[0]["parse_mode"] == "HTML"
    
    
@pytest.mark.asyncio
async def test_family_invite_deep_link_rejects_registered_non_standalone_user() -> None:
    message = _FakeMessage()
    state = _FakeState()

    user_dto = UserProfileDTO(
        user_id=202,
        role="parent",
        is_fully_registered=True,
        family_id=88,
    )

    profile_service = _FamilyInviteProfileService(
        invite=None,
    )
    students_service = _ClaimStudentsService(
        invite=None,
        current_student=None,
    )

    await _start_family_invite_from_deep_link(
        message,
        token="family-invite-token",
        user_id=202,
        user_dto=user_dto,
        state=state,
        profile_service=profile_service,
        students_service=students_service,
    )

    assert students_service.student_user_ids == [202]
    assert profile_service.tokens == []

    assert state.clear_calls == 1
    assert state.data == {}
    assert state.current_state is None

    assert len(message.answers) == 1
    assert "уже зарегистрированы" in str(
        message.answers[0]["text"]
    )
    
class _CompletionProfileService:
    def __init__(
        self,
        *,
        consume_result: str | None = "child",
        user_dto: UserProfileDTO | None = None,
    ) -> None:
        self.consume_result = consume_result
        self.user_dto = user_dto or UserProfileDTO(
            user_id=1,
            role="child",
            is_fully_registered=True,
            name="Ученик",
            class_id="016",
            group_id="ALL",
        )
        self.consume_calls: list[dict[str, object]] = []
        self.class_group_calls: list[dict[str, object]] = []

    async def consume_family_invite(
        self,
        *,
        token: str,
        user_id: int,
        name: str,
        class_id: str,
        group_id: str,
    ) -> str | None:
        self.consume_calls.append(
            {
                "token": token,
                "user_id": user_id,
                "name": name,
                "class_id": class_id,
                "group_id": group_id,
            }
        )
        return self.consume_result

    async def get_user_profile_dto(
        self,
        user_id: int,
    ) -> UserProfileDTO:
        return self.user_dto

    async def set_child_class_and_group(
        self,
        user_id: int,
        class_id: str,
        group_id: str,
    ) -> None:
        self.class_group_calls.append(
            {
                "user_id": user_id,
                "class_id": class_id,
                "group_id": group_id,
            }
        )


class _CompletionStudentsService:
    def __init__(
        self,
        *,
        student: object | None,
    ) -> None:
        self.student = student
        self.ensure_calls: list[int] = []

    async def ensure_telegram_student_profile(
        self,
        *,
        telegram_user_id: int,
    ) -> object | None:
        self.ensure_calls.append(telegram_user_id)
        return self.student
    
    
@pytest.mark.asyncio
async def test_child_family_completion_rejects_foreign_fsm_actor() -> None:
    callback = _FakeCallback(user_id=501)
    state = _FakeState()

    profile_service = _CompletionProfileService()
    students_service = _CompletionStudentsService(
        student=SimpleNamespace(id=1),
    )

    invite_context = _FamilyInviteFSMContext(
        token="family-token",
        role="child",
        actor_user_id=999,
        pending_name="Мария",
    )

    await _complete_child_family_invite_registration(
        callback,
        state=state,
        invite_context=invite_context,
        class_id="016",
        group_id="ALL",
        profile_service=profile_service,
        students_service=students_service,
    )

    assert state.clear_calls == 1
    assert profile_service.consume_calls == []
    assert students_service.ensure_calls == []

    assert callback.message.delete_calls == 0
    assert callback.message.answers == []

    assert callback.answers == [
        {
            "text": (
                "❌ Состояние приглашения устарело. "
                "Откройте приглашение заново."
            ),
            "show_alert": True,
        }
    ]
    
@pytest.mark.asyncio
async def test_child_family_completion_consumes_invite_and_syncs_student() -> None:
    callback = _FakeCallback(user_id=502)
    state = _FakeState()

    profile_service = _CompletionProfileService(
        user_dto=UserProfileDTO(
            user_id=502,
            role="child",
            is_fully_registered=True,
            name="Мария",
            family_id=77,
            class_id="016",
            group_id="ALL",
        )
    )
    students_service = _CompletionStudentsService(
        student=SimpleNamespace(id=22),
    )

    invite_context = _FamilyInviteFSMContext(
        token="family-token",
        role="child",
        actor_user_id=502,
        pending_name="Мария",
    )

    await _complete_child_family_invite_registration(
        callback,
        state=state,
        invite_context=invite_context,
        class_id="016",
        group_id="0",
        profile_service=profile_service,
        students_service=students_service,
    )

    assert state.clear_calls == 1

    assert profile_service.consume_calls == [
        {
            "token": "family-token",
            "user_id": 502,
            "name": "Мария",
            "class_id": "016",
            "group_id": "0",
        }
    ]
    assert students_service.ensure_calls == [502]

    assert callback.message.delete_calls == 1

    # Первый message — registration success.
    # Второй message — persistent main menu.
    assert len(callback.message.answers) == 2
    assert callback.message.answers[0]["parse_mode"] == "HTML"
    assert "Мария" in str(
        callback.message.answers[0]["text"]
    )

    assert callback.answers == [
        {
            "text": "✅ Регистрация через приглашение завершена.",
        }
    ]
    
@pytest.mark.asyncio
async def test_standalone_child_completion_rejects_non_child_role() -> None:
    callback = _FakeCallback(user_id=601)
    state = _FakeState()

    profile_service = _CompletionProfileService(
        user_dto=UserProfileDTO(
            user_id=601,
            role="parent",
            is_fully_registered=True,
            name="Родитель",
            family_id=10,
        )
    )
    students_service = _CompletionStudentsService(
        student=SimpleNamespace(id=1),
    )

    await _complete_standalone_child_registration(
        callback,
        state=state,
        class_id="016",
        group_id="ALL",
        profile_service=profile_service,
        students_service=students_service,
    )

    assert state.clear_calls == 1
    assert profile_service.class_group_calls == []
    assert students_service.ensure_calls == []

    assert callback.message.delete_calls == 0
    assert callback.message.answers == []

    assert callback.answers == [
        {
            "text": (
                "❌ Регистрация ученика недоступна "
                "для текущей роли."
            ),
            "show_alert": True,
        }
    ]
    
@pytest.mark.asyncio
async def test_standalone_child_completion_saves_class_and_syncs_student() -> None:
    callback = _FakeCallback(user_id=602)
    state = _FakeState()

    profile_service = _CompletionProfileService(
        user_dto=UserProfileDTO(
            user_id=602,
            role="child",
            is_fully_registered=True,
            name="Иван",
            class_id="016",
            group_id="1",
        )
    )
    students_service = _CompletionStudentsService(
        student=SimpleNamespace(id=33),
    )

    await _complete_standalone_child_registration(
        callback,
        state=state,
        class_id="016",
        group_id="1",
        profile_service=profile_service,
        students_service=students_service,
    )

    assert state.clear_calls == 1

    assert profile_service.class_group_calls == [
        {
            "user_id": 602,
            "class_id": "016",
            "group_id": "1",
        }
    ]
    assert students_service.ensure_calls == [602]

    assert callback.message.delete_calls == 1
    assert len(callback.message.answers) == 2
    assert callback.message.answers[0]["parse_mode"] == "HTML"
    assert "Иван" in str(
        callback.message.answers[0]["text"]
    )

    assert callback.answers == [
        {
            "text": None,
        }
    ]