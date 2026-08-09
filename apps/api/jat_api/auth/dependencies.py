"""Reusable authenticated identity dependencies."""

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.auth.security import access_token_subject
from jat_api.db.models import User
from jat_api.db.repositories import find_user

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
    try:
        user_id = access_token_subject(credentials.credentials, request.app.state.settings)
    except Exception as error:
        raise HTTPException(status_code=401, detail="Invalid access token") from error
    user = await find_user(db, user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
