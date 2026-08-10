"""Settings API: preferences, profile, security, data controls, and usage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.auth.dependencies import current_session_family, current_user, get_db_session
from jat_api.auth.security import hash_password, verify_password
from jat_api.db.models import (
    Conversation,
    Message,
    MessagePart,
    Session,
    User,
    UserPreference,
)
from jat_api.db.repositories import (
    find_user_by_email,
    revoke_session_family,
    write_audit_log,
)
from jat_api.models.providers.ollama import list_ollama_models
from jat_api.settings.repository import apply_patch, load_preferences, save_preferences
from jat_api.settings.schemas import (
    MAX_MEMORIES,
    AccountDeletion,
    MemoryCreate,
    ModelOption,
    OperationResult,
    PasswordChange,
    Preferences,
    PreferencesUpdate,
    ProfileResponse,
    ProfileUpdate,
    SessionSummary,
    UsageStats,
)

router = APIRouter(prefix="/settings", tags=["settings"])


def request_id_of(request: Request) -> str | None:
    return request.headers.get("X-Request-ID")


# --------------------------------------------------------------------------- preferences


@router.get("", response_model=Preferences)
async def get_settings(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db_session)
) -> Preferences:
    return await load_preferences(db, user.id)


@router.patch("", response_model=Preferences)
async def update_settings(
    payload: PreferencesUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Preferences:
    """Partially update preferences. Unspecified fields are preserved."""
    preferences = await apply_patch(db, user.id, payload)
    await write_audit_log(
        db,
        action="settings.update",
        resource_type="user_preferences",
        actor_user_id=user.id,
        request_id=request_id_of(request),
    )
    await db.commit()
    return preferences


@router.post("/reset", response_model=Preferences)
async def reset_settings(
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Preferences:
    """Restore every preference to its documented default."""
    defaults = await save_preferences(db, user.id, Preferences())
    await write_audit_log(
        db,
        action="settings.reset",
        resource_type="user_preferences",
        actor_user_id=user.id,
        request_id=request_id_of(request),
    )
    await db.commit()
    return defaults


# --------------------------------------------------------------------------- memories


@router.post("/memories", response_model=Preferences, status_code=status.HTTP_201_CREATED)
async def add_memory(
    payload: MemoryCreate,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Preferences:
    current = await load_preferences(db, user.id)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Memory text cannot be blank")
    if text in current.memories:
        return current
    if len(current.memories) >= MAX_MEMORIES:
        raise HTTPException(
            status_code=409, detail=f"Memory limit of {MAX_MEMORIES} entries reached"
        )
    current.memories = [*current.memories, text]
    saved = await save_preferences(db, user.id, current)
    await write_audit_log(
        db,
        action="settings.memory_add",
        resource_type="user_preferences",
        actor_user_id=user.id,
        request_id=request_id_of(request),
    )
    await db.commit()
    return saved


@router.delete("/memories/{index}", response_model=Preferences)
async def delete_memory(
    index: int,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Preferences:
    current = await load_preferences(db, user.id)
    if index < 0 or index >= len(current.memories):
        raise HTTPException(status_code=404, detail="Memory not found")
    current.memories = [item for position, item in enumerate(current.memories) if position != index]
    saved = await save_preferences(db, user.id, current)
    await write_audit_log(
        db,
        action="settings.memory_delete",
        resource_type="user_preferences",
        actor_user_id=user.id,
        request_id=request_id_of(request),
    )
    await db.commit()
    return saved


@router.delete("/memories", response_model=Preferences)
async def clear_memories(
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Preferences:
    current = await load_preferences(db, user.id)
    current.memories = []
    saved = await save_preferences(db, user.id, current)
    await write_audit_log(
        db,
        action="settings.memory_clear",
        resource_type="user_preferences",
        actor_user_id=user.id,
        request_id=request_id_of(request),
    )
    await db.commit()
    return saved


# --------------------------------------------------------------------------- profile


def profile_of(user: User) -> ProfileResponse:
    return ProfileResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
    )


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(user: User = Depends(current_user)) -> ProfileResponse:
    return profile_of(user)


@router.patch("/profile", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    if payload.display_name is not None:
        display_name = payload.display_name.strip()
        if not display_name:
            raise HTTPException(status_code=422, detail="Display name cannot be blank")
        user.display_name = display_name
    if payload.email is not None:
        email = str(payload.email).lower()
        if email != user.email:
            existing = await find_user_by_email(db, email)
            if existing is not None:
                raise HTTPException(
                    status_code=409, detail="An account with this email already exists"
                )
            user.email = email
    db.add(user)
    await write_audit_log(
        db,
        action="settings.profile_update",
        resource_type="user",
        actor_user_id=user.id,
        request_id=request_id_of(request),
    )
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Unable to update profile") from error
    await db.refresh(user)
    return profile_of(user)


# --------------------------------------------------------------------------- security


@router.post("/password", response_model=OperationResult)
async def change_password(
    payload: PasswordChange,
    request: Request,
    user: User = Depends(current_user),
    family_id: UUID | None = Depends(current_session_family),
    db: AsyncSession = Depends(get_db_session),
) -> OperationResult:
    """Rotate the password and revoke every other refresh session."""
    if not verify_password(user.password_hash, payload.current_password):
        await write_audit_log(
            db,
            action="settings.password_change_failed",
            resource_type="user",
            actor_user_id=user.id,
            request_id=request_id_of(request),
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=422, detail="New password must differ from the current password"
        )
    user.password_hash = hash_password(payload.new_password)
    db.add(user)

    sessions = await db.scalars(
        select(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None))
    )
    revoked = 0
    for record in sessions:
        if family_id is not None and record.family_id == family_id:
            continue
        record.revoked_at = datetime.now(UTC)
        revoked += 1
    await write_audit_log(
        db,
        action="settings.password_change",
        resource_type="user",
        actor_user_id=user.id,
        request_id=request_id_of(request),
    )
    await db.commit()
    return OperationResult(
        ok=True, removed=revoked, detail="Password updated and other sessions signed out"
    )


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    user: User = Depends(current_user),
    family_id: UUID | None = Depends(current_session_family),
    db: AsyncSession = Depends(get_db_session),
) -> list[SessionSummary]:
    records = await db.scalars(
        select(Session)
        .where(
            Session.user_id == user.id,
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC),
        )
        .order_by(Session.created_at.desc())
        .limit(50)
    )
    return [
        SessionSummary(
            id=record.id,
            created_at=record.created_at,
            last_used_at=record.last_used_at,
            expires_at=record.expires_at,
            current=family_id is not None and record.family_id == family_id,
        )
        for record in records
    ]


@router.post("/sessions/revoke-others", response_model=OperationResult)
async def revoke_other_sessions(
    request: Request,
    user: User = Depends(current_user),
    family_id: UUID | None = Depends(current_session_family),
    db: AsyncSession = Depends(get_db_session),
) -> OperationResult:
    records = await db.scalars(
        select(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None))
    )
    revoked = 0
    for record in records:
        if family_id is not None and record.family_id == family_id:
            continue
        record.revoked_at = datetime.now(UTC)
        revoked += 1
    await write_audit_log(
        db,
        action="settings.sessions_revoked",
        resource_type="session",
        actor_user_id=user.id,
        request_id=request_id_of(request),
    )
    await db.commit()
    return OperationResult(ok=True, removed=revoked, detail="Other sessions signed out")


@router.delete("/sessions/{session_id}", response_model=OperationResult)
async def revoke_session(
    session_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> OperationResult:
    record = await db.scalar(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user.id,
            Session.revoked_at.is_(None),
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await revoke_session_family(db, record.family_id)
    await write_audit_log(
        db,
        action="settings.session_revoked",
        resource_type="session",
        actor_user_id=user.id,
        request_id=request_id_of(request),
    )
    await db.commit()
    return OperationResult(ok=True, removed=1, detail="Session signed out")


# --------------------------------------------------------------------------- models


@router.get("/models", response_model=list[ModelOption])
async def list_models(request: Request, user: User = Depends(current_user)) -> list[ModelOption]:
    """Advertise selectable models based on server configuration, never client claims."""
    settings = request.app.state.settings
    context_length = settings.model_context_length
    is_deterministic = settings.model_provider == "deterministic"
    options = [
        ModelOption(
            id=settings.model_name,
            label="JaT development" if is_deterministic else settings.model_name,
            description=(
                "Deterministic development provider for testing the pipeline."
                if is_deterministic
                else f"Default {settings.model_provider} model configured by the operator."
            ),
            provider=settings.model_provider,
            available=True,
            context_length=context_length,
        )
    ]
    if settings.model_endpoint:
        # Enumerate the models actually installed on the Ollama server so each
        # conversation can select a real model. Discovery is best-effort: if the
        # server is unreachable we still advertise one selectable Ollama entry.
        try:
            installed = await list_ollama_models(settings.model_endpoint)
        except Exception:  # discovery must never break the catalog
            installed = []
        if installed:
            for name in dict.fromkeys(installed):
                options.append(
                    ModelOption(
                        id=name,
                        label=name,
                        description="Self-hosted Ollama model from the configured endpoint.",
                        provider="ollama",
                        available=True,
                        context_length=context_length,
                    )
                )
        else:
            options.append(
                ModelOption(
                    id="ollama",
                    label="Local Ollama",
                    description="Self-hosted Ollama model from the configured endpoint.",
                    provider="ollama",
                    available=True,
                    context_length=context_length,
                )
            )
    else:
        options.append(
            ModelOption(
                id="ollama",
                label="Local Ollama",
                description="Set JAT_MODEL_ENDPOINT to enable a self-hosted Ollama model.",
                provider="ollama",
                available=False,
                context_length=context_length,
            )
        )
    return options


# --------------------------------------------------------------------------- data controls


async def conversation_ids_for(db: AsyncSession, user: User) -> list[UUID]:
    from jat_api.conversations import organization_for_user

    organization_id = await organization_for_user(db, user)
    rows = await db.scalars(
        select(Conversation.id).where(Conversation.organization_id == organization_id)
    )
    return list(rows)


@router.get("/usage", response_model=UsageStats)
async def usage(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db_session)
) -> UsageStats:
    ids = await conversation_ids_for(db, user)
    if not ids:
        return UsageStats(
            conversations=0,
            messages=0,
            input_tokens=0,
            output_tokens=0,
            first_activity_at=None,
            last_activity_at=None,
        )
    row = (
        await db.execute(
            select(
                func.count(Message.id),
                func.coalesce(func.sum(Message.input_tokens), 0),
                func.coalesce(func.sum(Message.output_tokens), 0),
                func.min(Message.created_at),
                func.max(Message.created_at),
            ).where(Message.conversation_id.in_(ids))
        )
    ).one()
    return UsageStats(
        conversations=len(ids),
        messages=int(row[0] or 0),
        input_tokens=int(row[1] or 0),
        output_tokens=int(row[2] or 0),
        first_activity_at=row[3],
        last_activity_at=row[4],
    )


@router.get("/export")
async def export_data(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db_session)
) -> dict[str, Any]:
    """Return a portable copy of the account's own data."""
    preferences = await load_preferences(db, user.id)
    ids = await conversation_ids_for(db, user)
    conversations: list[dict[str, Any]] = []
    if ids:
        records = await db.scalars(
            select(Conversation).where(Conversation.id.in_(ids)).order_by(Conversation.created_at)
        )
        rows = await db.execute(
            select(
                Message.conversation_id,
                Message.role,
                Message.status,
                MessagePart.content,
                Message.created_at,
            )
            .join(MessagePart, MessagePart.message_id == Message.id)
            .where(Message.conversation_id.in_(ids), MessagePart.kind == "text")
            .order_by(Message.created_at, MessagePart.position)
        )
        grouped: dict[UUID, list[dict[str, Any]]] = {}
        for conversation_id, role, message_status, content, created_at in rows:
            grouped.setdefault(conversation_id, []).append(
                {
                    "role": role,
                    "status": message_status,
                    "content": content,
                    "created_at": created_at.isoformat(),
                }
            )
        for record in records:
            conversations.append(
                {
                    "id": str(record.id),
                    "title": record.title,
                    "model": record.model,
                    "archived": record.archived_at is not None,
                    "created_at": record.created_at.isoformat(),
                    "messages": grouped.get(record.id, []),
                }
            )
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "account": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat(),
        },
        "preferences": preferences.model_dump(mode="json"),
        "conversations": conversations,
    }


@router.delete("/conversations", response_model=OperationResult)
async def delete_all_conversations(
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> OperationResult:
    """Permanently delete every conversation the account can see."""
    ids = await conversation_ids_for(db, user)
    if ids:
        await db.execute(delete(Conversation).where(Conversation.id.in_(ids)))
    await write_audit_log(
        db,
        action="settings.conversations_deleted",
        resource_type="conversation",
        actor_user_id=user.id,
        request_id=request_id_of(request),
    )
    await db.commit()
    return OperationResult(ok=True, removed=len(ids), detail="Conversations deleted")


@router.post("/delete-account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    payload: AccountDeletion,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Irreversibly deactivate the account after re-authentication."""
    if payload.confirmation.strip().upper() != "DELETE":
        raise HTTPException(status_code=422, detail="Type DELETE to confirm account deletion")
    if not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=401, detail="Password is incorrect")

    ids = await conversation_ids_for(db, user)
    if ids:
        await db.execute(delete(Conversation).where(Conversation.id.in_(ids)))
    await db.execute(delete(UserPreference).where(UserPreference.user_id == user.id))
    sessions = await db.scalars(
        select(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None))
    )
    for record in sessions:
        record.revoked_at = datetime.now(UTC)
    user.status = "deleted"
    user.email = f"deleted+{user.id}@invalid.local"
    user.display_name = "Deleted account"
    db.add(user)
    await write_audit_log(
        db,
        action="settings.account_deleted",
        resource_type="user",
        actor_user_id=user.id,
        request_id=request_id_of(request),
    )
    await db.commit()
    deletion_response = Response(status_code=status.HTTP_204_NO_CONTENT)
    deletion_response.delete_cookie("jat_refresh_token", path="/api/v1/auth")
    return deletion_response
