"""Browser and API-client authentication routes."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from jat_api.auth.security import (
    access_token_subject,
    hash_password,
    issue_access_token,
    new_refresh_token,
    token_hash,
    verify_password,
)
from jat_api.config import Settings
from jat_api.db.models import User
from jat_api.db.repositories import (
    active_session_by_token_hash,
    create_session,
    create_user_with_personal_organization,
    find_user,
    find_user_by_email,
    revoke_session_by_token_hash,
    revoke_session_family,
    write_audit_log,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
bearer = HTTPBearer(auto_error=False)


def database_session(request: Request):
    return request.app.state.database.session_factory()


async def get_session(request: Request):
    async with database_session(request) as session:
        yield session


def settings_for(request: Request) -> Settings:
    return request.app.state.settings


def refresh_cookie_is_secure(settings: Settings) -> bool:
    return settings.environment in {"staging", "production"}


async def start_session(
    response: Response, db: AsyncSession, user: User, settings: Settings
) -> None:
    raw_token = new_refresh_token()
    await create_session(
        db,
        user_id=user.id,
        refresh_token_hash=token_hash(raw_token),
        family_id=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
    )
    response.set_cookie(
        "jat_refresh_token",
        raw_token,
        httponly=True,
        secure=refresh_cookie_is_secure(settings),
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 86_400,
        path="/api/v1/auth",
    )


def response_for(user: User, settings: Settings) -> TokenResponse:
    return TokenResponse(
        access_token=issue_access_token(user.id, settings),
        user=UserResponse(id=user.id, email=user.email, display_name=user.display_name),
    )


def slug_for(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workspace"
    return f"{base[:55]}-{uuid4().hex[:8]}"


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    if await find_user_by_email(db, str(payload.email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    try:
        user = await create_user_with_personal_organization(
            db,
            email=str(payload.email),
            password_hash=hash_password(payload.password),
            display_name=payload.display_name.strip(),
            slug=slug_for(payload.display_name),
        )
        await start_session(response, db, user, request.app.state.settings)
        await write_audit_log(
            db,
            action="auth.register",
            resource_type="user",
            actor_user_id=user.id,
            request_id=request.headers.get("X-Request-ID"),
        )
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Unable to create account") from error
    return response_for(user, request.app.state.settings)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    user = await find_user_by_email(db, str(payload.email))
    if (
        user is None
        or user.status != "active"
        or not verify_password(user.password_hash, payload.password)
    ):
        await write_audit_log(
            db,
            action="auth.login_failed",
            resource_type="session",
            request_id=request.headers.get("X-Request-ID"),
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await start_session(response, db, user, request.app.state.settings)
    await write_audit_log(
        db,
        action="auth.login",
        resource_type="session",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
    return response_for(user, request.app.state.settings)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request, response: Response, db: AsyncSession = Depends(get_session)
) -> TokenResponse:
    raw_token = request.cookies.get("jat_refresh_token")
    if not raw_token:
        raise HTTPException(status_code=401, detail="Refresh credential required")
    record = await active_session_by_token_hash(db, token_hash(raw_token))
    if record is None:
        response.delete_cookie("jat_refresh_token", path="/api/v1/auth")
        raise HTTPException(status_code=401, detail="Refresh credential is invalid or expired")
    user = await find_user(db, record.user_id)
    if user is None or user.status != "active":
        await revoke_session_family(db, record.family_id)
        await db.commit()
        raise HTTPException(status_code=401, detail="Authentication required")
    await revoke_session_family(db, record.family_id)
    new_token = new_refresh_token()
    await create_session(
        db,
        user_id=user.id,
        refresh_token_hash=token_hash(new_token),
        family_id=record.family_id,
        expires_at=datetime.now(UTC)
        + timedelta(days=request.app.state.settings.refresh_token_ttl_days),
    )
    await write_audit_log(
        db,
        action="auth.refresh",
        resource_type="session",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
    response.set_cookie(
        "jat_refresh_token",
        new_token,
        httponly=True,
        secure=refresh_cookie_is_secure(request.app.state.settings),
        samesite="lax",
        max_age=request.app.state.settings.refresh_token_ttl_days * 86_400,
        path="/api/v1/auth",
    )
    return response_for(user, request.app.state.settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    raw_token = request.cookies.get("jat_refresh_token")
    if raw_token:
        await revoke_session_by_token_hash(db, token_hash(raw_token))
        await write_audit_log(
            db,
            action="auth.logout",
            resource_type="session",
            request_id=request.headers.get("X-Request-ID"),
        )
        await db.commit()
    logout_response = Response(status_code=status.HTTP_204_NO_CONTENT)
    logout_response.delete_cookie("jat_refresh_token", path="/api/v1/auth")
    return logout_response


@router.get("/me", response_model=UserResponse)
async def me(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_session),
) -> UserResponse:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        subject = access_token_subject(credentials.credentials, request.app.state.settings)
    except Exception as error:
        raise HTTPException(status_code=401, detail="Invalid access token") from error
    user = await find_user(db, subject)
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Authentication required")
    return UserResponse(id=user.id, email=user.email, display_name=user.display_name)
