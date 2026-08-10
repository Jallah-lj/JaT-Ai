"""Reusable authenticated identity dependencies."""

from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.auth.security import access_token_session_family, access_token_subject
from jat_api.db.models import User
from jat_api.db.repositories import find_user, session_family_is_active

bearer = HTTPBearer(auto_error=False)


async def get_db_session(request: Request):
    async with request.app.state.database.session_factory() as session:
        yield session


async def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    settings = request.app.state.settings
    try:
        user_id = access_token_subject(credentials.credentials, settings)
        family_id = access_token_session_family(credentials.credentials, settings)
    except Exception as error:
        raise HTTPException(status_code=401, detail="Invalid access token") from error
    user = await find_user(db, user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Authentication required")
    # Revoking a session must take effect immediately, not when the access token expires.
    if family_id is not None and not await session_family_is_active(db, user.id, family_id):
        raise HTTPException(status_code=401, detail="Session has been signed out")
    return user


async def require_person(user: User = Depends(current_user)) -> User:
    """Reject guest identities on account-management endpoints."""
    from jat_api.guest import is_guest

    if is_guest(user):
        raise HTTPException(
            status_code=403,
            detail="Guest accounts cannot change account settings. "
            "Create an account to unlock them.",
        )
    return user


async def current_session_family(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> UUID | None:
    """Identify which refresh-session family issued the presented access token."""
    if credentials is None:
        return None
    try:
        return access_token_session_family(credentials.credentials, request.app.state.settings)
    except Exception:
        return None
