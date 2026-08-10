"""Unit tests for guest (anonymous trial) access controls.

These mirror the DB-free style of ``test_chat_orchestration.py``: quota math,
identity flags and token conversion are exercised against fakes instead of a
live database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from jat_api.auth.routes import guest_user_from_token
from jat_api.auth.schemas import RegisterRequest, UserResponse
from jat_api.auth.security import issue_access_token
from jat_api.config import Settings
from jat_api.db.models import User
from jat_api.guest import (
    GUEST_EXPIRED,
    GUEST_LIMIT_REACHED,
    enforce_guest_conversation_cap,
    enforce_guest_quota,
    guest_expires_at,
    guest_message_usage,
    guest_problem,
    is_guest,
)


def _guest(*, created_at: datetime | None = None, status: str = "active") -> User:
    user = User(
        id=uuid4(),
        email="guest-abc@guest.jat.local",
        password_hash="guest:unusable",
        display_name="Guest",
        kind="guest",
        status=status,
    )
    user.created_at = created_at or datetime.now(UTC) - timedelta(minutes=5)
    return user


def _person() -> User:
    return User(
        id=uuid4(),
        email="person@example.test",
        password_hash="hash",
        display_name="Person",
        kind="person",
    )


def _settings() -> Settings:
    return Settings(
        environment="testing",
        guest_enabled=True,
        guest_message_limit=10,
        guest_ttl_hours=24,
        guest_max_conversations=5,
    )


class FakeSession:
    """Async session stand-in returning canned scalars / identities."""

    def __init__(self, *, scalar_value: object = 0, user: User | None = None) -> None:
        self._value = scalar_value
        self._user = user

    async def scalar(self, _statement: object) -> object:
        return self._value

    async def get(self, _model: object, user_id: object) -> User | None:
        return self._user if self._user is not None and self._user.id == user_id else None


def test_guest_identity_flag_distinguishes_trial_users() -> None:
    assert is_guest(_guest())
    assert not is_guest(_person())


def test_guest_expiry_is_created_at_plus_ttl() -> None:
    created = datetime(2026, 8, 1, tzinfo=UTC)
    settings = _settings()
    assert guest_expires_at(_guest(created_at=created), settings) == created + timedelta(hours=24)


def test_guest_problem_carries_machine_readable_code() -> None:
    problem = guest_problem(GUEST_LIMIT_REACHED, "hello")
    assert problem["code"] == GUEST_LIMIT_REACHED
    assert problem["detail"] == "hello"


@pytest.mark.asyncio
async def test_enforce_guest_quota_rejects_when_message_limit_reached() -> None:
    db = FakeSession(scalar_value=10)  # user messages == message limit
    with pytest.raises(HTTPException) as excinfo:
        await enforce_guest_quota(db, _guest(), _settings())  # type: ignore[arg-type]
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail["code"] == GUEST_LIMIT_REACHED  # type: ignore[index]


@pytest.mark.asyncio
async def test_enforce_guest_quota_allows_requests_under_the_limit() -> None:
    db = FakeSession(scalar_value=4)
    await enforce_guest_quota(db, _guest(), _settings())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_enforce_guest_quota_rejects_expired_trials() -> None:
    old = datetime.now(UTC) - timedelta(hours=48)
    db = FakeSession(scalar_value=0)
    with pytest.raises(HTTPException) as excinfo:
        await enforce_guest_quota(db, _guest(created_at=old), _settings())  # type: ignore[arg-type]
    assert excinfo.value.detail["code"] == GUEST_EXPIRED  # type: ignore[index]


@pytest.mark.asyncio
async def test_enforce_guest_quota_passes_person_accounts_through() -> None:
    await enforce_guest_quota(FakeSession(scalar_value=0), _person(), _settings())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_guest_message_usage_counts_reported_messages() -> None:
    db = FakeSession(scalar_value=7)
    assert await guest_message_usage(db, _guest()) == 7  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_enforce_guest_conversation_cap_limits_open_chats() -> None:
    settings = _settings()  # max 5 conversations
    with pytest.raises(HTTPException) as excinfo:
        await enforce_guest_conversation_cap(  # type: ignore[arg-type]
            FakeSession(scalar_value=5), _guest(), settings
        )
    assert excinfo.value.detail["code"] == GUEST_LIMIT_REACHED  # type: ignore[index]
    await enforce_guest_conversation_cap(  # type: ignore[arg-type]
        FakeSession(scalar_value=3), _guest(), settings
    )
    # Person accounts are never capped.
    await enforce_guest_conversation_cap(  # type: ignore[arg-type]
        FakeSession(scalar_value=99), _person(), settings
    )


def test_register_request_accepts_optional_guest_token() -> None:
    payload = RegisterRequest(email="new@example.com", password="password123", display_name="N")
    assert payload.guest_token is None
    with_token = RegisterRequest(
        email="new@example.com",
        password="password123",
        display_name="N",
        guest_token="abc",
    )
    assert with_token.guest_token == "abc"


def test_user_response_includes_identity_kind() -> None:
    guest_user = _guest()
    response = UserResponse(
        id=guest_user.id,
        email=guest_user.email,
        display_name=guest_user.display_name,
        kind=guest_user.kind,
    )
    assert response.kind == "guest"
    assert UserResponse(id=uuid4(), email="a@b.test", display_name="A").kind == "person"


def _request_with(settings: Settings) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))


@pytest.mark.asyncio
async def test_guest_user_from_token_accepts_only_active_guest_identities() -> None:
    settings = _settings()
    request = _request_with(settings)

    guest = _guest()
    token = issue_access_token(guest.id, settings)
    resolved = await guest_user_from_token(  # type: ignore[arg-type]
        FakeSession(user=guest), request, token
    )
    assert resolved is not None and resolved.id == guest.id

    person = _person()
    person_token = issue_access_token(person.id, settings)
    assert (
        await guest_user_from_token(  # type: ignore[arg-type]
            FakeSession(user=person), request, person_token
        )
        is None
    )

    disabled = _guest(status="disabled")
    disabled_token = issue_access_token(disabled.id, settings)
    assert (
        await guest_user_from_token(  # type: ignore[arg-type]
            FakeSession(user=disabled), request, disabled_token
        )
        is None
    )

    assert (
        await guest_user_from_token(FakeSession(), request, "not-a-jwt") is None  # type: ignore[arg-type]
    )
