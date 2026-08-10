"""Guest (anonymous trial) access controls.

Visitors can experiment with the LLM before creating an account. Guest
identities are ordinary ``users`` rows marked ``kind = "guest"`` with an
opaque email and an unusable password; they are scoped to their own personal
organization just like any other account, so every conversation, message and
RAG object they create stays inside their sandbox.

Operators bound the trial with:

* ``JAT_GUEST_ENABLED`` — master switch for the whole feature,
* ``JAT_GUEST_MESSAGE_LIMIT`` — free assistant turns before sign-up is
  required,
* ``JAT_GUEST_TTL_HOURS`` — how long a guest session may live,
* ``JAT_GUEST_MAX_CONVERSATIONS`` — cap on open conversations per guest.

Quotas are enforced at request time against the database, so they survive
token refreshes and cannot be bypassed by clearing browser storage.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.config import Settings
from jat_api.db.models import Conversation, Message, User

# Machine-readable error codes the web client keys its sign-up prompts on.
GUEST_LIMIT_REACHED = "guest_limit_reached"
GUEST_EXPIRED = "guest_expired"
GUEST_DISABLED = "guest_disabled"

_GUEST_PROBLEM = "Guest accounts cannot do that. Create an account to continue."


def is_guest(user: User) -> bool:
    """Whether this identity is an anonymous trial session."""
    return user.kind == "guest"


def guest_expires_at(user: User, settings: Settings) -> datetime:
    """When this guest's trial window runs out (created_at + TTL)."""
    return user.created_at + timedelta(hours=settings.guest_ttl_hours)


def guest_problem(code: str, message: str = _GUEST_PROBLEM) -> dict[str, str]:
    """Build a structured problem body the client can branch on by code."""
    return {"code": code, "detail": message}


def guest_limit_problem(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=guest_problem(GUEST_LIMIT_REACHED, message),
    )


async def guest_message_usage(db: AsyncSession, user: User) -> int:
    """Count the guest's user turns (one per assistant response)."""
    used = await db.scalar(
        select(func.count(Message.id))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.created_by_user_id == user.id,
            Message.role == "user",
        )
    )
    return int(used or 0)


async def guest_conversation_count(db: AsyncSession, user: User) -> int:
    """Count the guest's open conversations."""
    count = await db.scalar(
        select(func.count(Conversation.id)).where(
            Conversation.created_by_user_id == user.id,
            Conversation.archived_at.is_(None),
        )
    )
    return int(count or 0)


async def enforce_guest_quota(db: AsyncSession, user: User, settings: Settings) -> None:
    """Reject guest requests that exceed their trial window or message budget.

    Non-guest identities pass through untouched.
    """
    if not is_guest(user):
        return
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=guest_problem(GUEST_DISABLED, "This guest session is no longer active."),
        )
    if datetime.now(UTC) >= guest_expires_at(user, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=guest_problem(
                GUEST_EXPIRED,
                "Your free trial session has expired. Create an account to keep going.",
            ),
        )
    if await guest_message_usage(db, user) >= settings.guest_message_limit:
        raise guest_limit_problem(
            f"You've used all {settings.guest_message_limit} free messages. "
            "Create an account to keep chatting."
        )


async def enforce_guest_conversation_cap(db: AsyncSession, user: User, settings: Settings) -> None:
    """Limit how many open conversations a guest can accumulate."""
    if not is_guest(user):
        return
    if await guest_conversation_count(db, user) >= settings.guest_max_conversations:
        raise guest_limit_problem(
            "Guest mode is limited to "
            f"{settings.guest_max_conversations} conversations. "
            "Create an account to keep every chat."
        )
