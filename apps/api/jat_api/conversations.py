"""Authenticated organization-scoped conversation API."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.auth.dependencies import current_user, get_db_session
from jat_api.db.models import Conversation, Message, MessagePart, OrganizationMembership, User
from jat_api.db.repositories import write_audit_log

router = APIRouter(prefix="/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=200)
    model: str | None = Field(default=None, max_length=120)


class UpdateConversationRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    # Changing the model switches which provider model serves subsequent messages
    # in this conversation without altering its history.
    model: str | None = Field(default=None, min_length=1, max_length=120)


class MessageResponse(BaseModel):
    id: UUID
    role: str
    status: str
    generation_id: UUID | None
    content: str
    created_at: datetime


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    model: str
    created_at: datetime
    updated_at: datetime


async def organization_for_user(db: AsyncSession, user: User) -> UUID:
    organization_id = await db.scalar(
        select(OrganizationMembership.organization_id).where(
            OrganizationMembership.user_id == user.id
        )
    )
    if organization_id is None:
        raise HTTPException(status_code=403, detail="No organization membership")
    return organization_id


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: CreateConversationRequest,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    organization_id = await organization_for_user(db, user)
    conversation = Conversation(
        organization_id=organization_id,
        created_by_user_id=user.id,
        title=payload.title.strip(),
        model=payload.model or request.app.state.settings.model_name,
    )
    db.add(conversation)
    await write_audit_log(
        db,
        action="conversation.create",
        resource_type="conversation",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
    await db.refresh(conversation)
    return ConversationResponse.model_validate(conversation, from_attributes=True)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db_session)
) -> list[ConversationResponse]:
    organization_id = await organization_for_user(db, user)
    records = await db.scalars(
        select(Conversation)
        .where(Conversation.organization_id == organization_id, Conversation.archived_at.is_(None))
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    )
    return [ConversationResponse.model_validate(record, from_attributes=True) for record in records]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    organization_id = await organization_for_user(db, user)
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.organization_id == organization_id,
            Conversation.archived_at.is_(None),
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationResponse.model_validate(conversation, from_attributes=True)


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: UUID,
    payload: UpdateConversationRequest,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    organization_id = await organization_for_user(db, user)
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.organization_id == organization_id,
            Conversation.archived_at.is_(None),
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if payload.title is not None:
        conversation.title = payload.title.strip()
    if payload.model is not None:
        conversation.model = payload.model.strip()
    conversation.updated_at = datetime.now().astimezone()
    await write_audit_log(
        db,
        action="conversation.update",
        resource_type="conversation",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
    await db.refresh(conversation)
    return ConversationResponse.model_validate(conversation, from_attributes=True)


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[MessageResponse]:
    await get_conversation(conversation_id, user, db)
    rows = await db.execute(
        select(
            Message.id,
            Message.role,
            Message.status,
            Message.generation_id,
            MessagePart.content,
            Message.created_at,
        )
        .join(MessagePart, MessagePart.message_id == Message.id)
        .where(Message.conversation_id == conversation_id, MessagePart.kind == "text")
        .order_by(Message.created_at, MessagePart.position)
    )
    return [
        MessageResponse(
            id=row.id,
            role=row.role,
            status=row.status,
            generation_id=row.generation_id,
            content=row.content,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_conversation(
    conversation_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    organization_id = await organization_for_user(db, user)
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.organization_id == organization_id,
            Conversation.archived_at.is_(None),
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation.archived_at = datetime.now().astimezone()
    await write_audit_log(
        db,
        action="conversation.archive",
        resource_type="conversation",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
