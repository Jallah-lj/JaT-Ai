"""Persistence operations for the authentication boundary."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.db.models import Organization, OrganizationMembership, Session, User


async def find_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email.lower()))


async def find_user(session: AsyncSession, user_id: UUID) -> User | None:
    return await session.get(User, user_id)


async def create_user_with_personal_organization(
    session: AsyncSession, *, email: str, password_hash: str, display_name: str, slug: str
) -> User:
    user = User(email=email.lower(), password_hash=password_hash, display_name=display_name)
    organization = Organization(name=f"{display_name}'s workspace", slug=slug)
    session.add_all([user, organization])
    await session.flush()
    session.add(
        OrganizationMembership(organization_id=organization.id, user_id=user.id, role="owner")
    )
    return user


async def create_session(
    session: AsyncSession,
    *,
    user_id: UUID,
    refresh_token_hash: str,
    family_id: UUID,
    expires_at: datetime,
) -> Session:
    record = Session(
        user_id=user_id,
        refresh_token_hash=refresh_token_hash,
        family_id=family_id,
        expires_at=expires_at,
    )
    session.add(record)
    return record


async def active_session_by_token_hash(
    session: AsyncSession, refresh_token_hash: str
) -> Session | None:
    return await session.scalar(
        select(Session).where(
            Session.refresh_token_hash == refresh_token_hash,
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC),
        )
    )


async def revoke_session_family(session: AsyncSession, family_id: UUID) -> None:
    await session.execute(
        update(Session)
        .where(Session.family_id == family_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_session_by_token_hash(session: AsyncSession, refresh_token_hash: str) -> None:
    record = await active_session_by_token_hash(session, refresh_token_hash)
    if record is not None:
        await revoke_session_family(session, record.family_id)


async def write_audit_log(
    session: AsyncSession,
    *,
    action: str,
    resource_type: str,
    actor_user_id: UUID | None = None,
    request_id: str | None = None,
    resource_id: str | None = None,
) -> None:
    """Persist an allowlisted audit event; never pass raw credentials or request bodies."""
    from jat_api.db.models import AuditLog

    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            request_id=request_id,
            resource_id=resource_id,
        )
    )


async def session_family_is_active(session: AsyncSession, user_id: UUID, family_id: UUID) -> bool:
    """Report whether a refresh-session family is still usable for the given user."""
    record = await session.scalar(
        select(Session.id).where(
            Session.user_id == user_id,
            Session.family_id == family_id,
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC),
        )
    )
    return record is not None
