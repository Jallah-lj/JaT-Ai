"""Browser and API-client authentication routes."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.auth.schemas import (
    GuestStatus,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from jat_api.auth.security import (
    access_token_subject,
    hash_password,
    issue_access_token,
    new_refresh_token,
    token_hash,
    verify_password,
)
from jat_api.config import Settings
from jat_api.conversations import organization_for_user
from jat_api.db.models import User
from jat_api.db.repositories import (
    active_session_by_token_hash,
    create_guest_user,
    create_session,
    create_user_with_personal_organization,
    find_user,
    find_user_by_email,
    revoke_all_sessions_for_user,
    revoke_session_by_token_hash,
    revoke_session_family,
    transfer_conversations_to_user,
    write_audit_log,
)
from jat_api.guest import (
    guest_conversation_count,
    guest_expires_at,
    guest_message_usage,
    is_guest,
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
) -> UUID:
    """Create a refresh session and return its family id for access-token binding."""
    raw_token = new_refresh_token()
    family_id = uuid4()
    await create_session(
        db,
        user_id=user.id,
        refresh_token_hash=token_hash(raw_token),
        family_id=family_id,
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
    return family_id


def response_for(
    user: User, settings: Settings, session_family_id: UUID | None = None
) -> TokenResponse:
    return TokenResponse(
        access_token=issue_access_token(user.id, settings, session_family_id=session_family_id),
        user=UserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            kind=user.kind,
        ),
    )


def slug_for(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workspace"
    return f"{base[:55]}-{uuid4().hex[:8]}"


def random_credential_hash() -> str:
    """Opaque, unusable credential for guest identities (never a real password)."""
    return f"guest:{hashlib.sha256(secrets.token_urlsafe(48).encode()).hexdigest()}"


async def guest_user_from_token(db: AsyncSession, request: Request, token: str) -> User | None:
    """Resolve an access token to an active guest identity, or None."""
    try:
        guest_id = access_token_subject(token, request.app.state.settings)
    except Exception:
        return None
    guest = await find_user(db, guest_id)
    if guest is None or not is_guest(guest) or guest.status != "active":
        return None
    return guest


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    if await find_user_by_email(db, str(payload.email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    guest = (
        await guest_user_from_token(db, request, payload.guest_token)
        if payload.guest_token
        else None
    )
    if payload.guest_token and guest is None:
        raise HTTPException(
            status_code=400,
            detail="Guest session token is invalid or expired. Create your account and your "
            "trial chats will be saved to it.",
        )
    try:
        user = await create_user_with_personal_organization(
            db,
            email=str(payload.email),
            password_hash=hash_password(payload.password),
            display_name=payload.display_name.strip(),
            slug=slug_for(payload.display_name),
        )
        organization_id = await organization_for_user(db, user)
        if guest is not None:
            # The new account inherits the guest's chats, then the trial
            # identity and its sessions are retired for good.
            await transfer_conversations_to_user(
                db,
                from_user_id=guest.id,
                to_user_id=user.id,
                to_organization_id=organization_id,
            )
            guest.status = "disabled"
            await revoke_all_sessions_for_user(db, guest.id)
            await write_audit_log(
                db,
                action="auth.guest_converted",
                resource_type="user",
                actor_user_id=user.id,
                resource_id=str(guest.id),
                request_id=request.headers.get("X-Request-ID"),
            )
        family_id = await start_session(response, db, user, request.app.state.settings)
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
    return response_for(user, request.app.state.settings, family_id)


@router.post("/guest", response_model=TokenResponse)
async def guest_session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Start an anonymous trial session that can be converted into an account."""
    settings = request.app.state.settings
    if not settings.guest_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guest mode is currently disabled. Create an account to continue.",
        )
    user = await create_guest_user(
        db,
        email=f"guest-{uuid4().hex}@guest.jat.local",
        password_hash=random_credential_hash(),
    )
    family_id = await start_session(response, db, user, settings)
    await write_audit_log(
        db,
        action="auth.guest_start",
        resource_type="user",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
    return response_for(user, settings, family_id)


@router.get("/guest/status", response_model=GuestStatus)
async def guest_status(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_session),
) -> GuestStatus:
    """Trial budget for the guest banner, or the global guest switch when anonymous.

    Exposing the switch publicly is deliberate: the landing/auth page uses it
    to decide whether to offer the “try it free” path at all.
    """
    settings = request.app.state.settings
    if not settings.guest_enabled:
        return GuestStatus(enabled=False)
    anonymous = GuestStatus(
        enabled=True,
        kind="anonymous",
        message_limit=settings.guest_message_limit,
        conversation_limit=settings.guest_max_conversations,
    )
    if credentials is None:
        return anonymous
    try:
        user_id = access_token_subject(credentials.credentials, settings)
    except Exception:
        return anonymous
    user = await find_user(db, user_id)
    if user is None or user.kind != "guest":
        return GuestStatus(enabled=True, kind="person")
    return GuestStatus(
        enabled=True,
        kind="guest",
        message_limit=settings.guest_message_limit,
        messages_used=await guest_message_usage(db, user),
        conversation_limit=settings.guest_max_conversations,
        conversations=await guest_conversation_count(db, user),
        expires_at=guest_expires_at(user, settings),
    )


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
    family_id = await start_session(response, db, user, request.app.state.settings)
    await write_audit_log(
        db,
        action="auth.login",
        resource_type="session",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
    return response_for(user, request.app.state.settings, family_id)


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
    return response_for(user, request.app.state.settings, record.family_id)


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
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        kind=user.kind,
    )
