"""Phase 2 chat orchestration over provider-neutral model contracts."""

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.auth.dependencies import current_user, get_db_session
from jat_api.conversations import organization_for_user
from jat_api.db.models import Conversation, Message, MessagePart, User
from jat_api.generations import finalize_generation
from jat_api.models import ChatMessage, GenerationRequest, create_provider

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    conversation_id: UUID
    content: str = Field(min_length=1, max_length=100_000)


class ChatResponse(BaseModel):
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    content: str
    model: str


async def owned_conversation(db: AsyncSession, user: User, conversation_id: UUID) -> Conversation:
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
    return conversation


async def history_for(db: AsyncSession, conversation_id: UUID) -> list[ChatMessage]:
    rows = await db.execute(
        select(Message.role, MessagePart.content)
        .join(MessagePart, MessagePart.message_id == Message.id)
        .where(Message.conversation_id == conversation_id, MessagePart.kind == "text")
        .order_by(Message.created_at, MessagePart.position)
    )
    return [ChatMessage(role=role, content=content) for role, content in rows]


async def store_message(
    db: AsyncSession, *, conversation_id: UUID, role: str, content: str, model: str | None = None
) -> Message:
    message = Message(conversation_id=conversation_id, role=role, model=model)
    db.add(message)
    await db.flush()
    db.add(MessagePart(message_id=message.id, position=0, kind="text", content=content))
    return message


def generation_request(
    request: Request, conversation: Conversation, history: list[ChatMessage]
) -> GenerationRequest:
    settings = request.app.state.settings
    return GenerationRequest(
        messages=history,
        model=conversation.model,
        max_tokens=settings.model_max_tokens,
        temperature=settings.model_temperature,
        context_length=settings.model_context_length,
    )


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatResponse:
    conversation = await owned_conversation(db, user, payload.conversation_id)
    user_message = await store_message(
        db, conversation_id=conversation.id, role="user", content=payload.content
    )
    history = await history_for(db, conversation.id)
    provider = create_provider(
        request.app.state.settings.model_provider, request.app.state.settings.model_endpoint
    )
    result = await provider.generate(generation_request(request, conversation, history))
    assistant_message = await store_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content=result.text,
        model=result.model,
    )
    assistant_message.input_tokens = result.input_tokens
    assistant_message.output_tokens = result.output_tokens
    await db.commit()
    return ChatResponse(
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        content=result.text,
        model=result.model,
    )


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    conversation = await owned_conversation(db, user, payload.conversation_id)
    await store_message(db, conversation_id=conversation.id, role="user", content=payload.content)
    history = await history_for(db, conversation.id)
    provider = create_provider(
        request.app.state.settings.model_provider, request.app.state.settings.model_endpoint
    )
    generation_id = uuid4()
    assistant = Message(
        conversation_id=conversation.id,
        role="assistant",
        status="streaming",
        model=conversation.model,
        generation_id=generation_id,
    )
    db.add(assistant)
    await db.commit()
    await db.refresh(assistant)

    async def events() -> AsyncIterator[str]:
        text = ""
        try:
            async for token in provider.stream(generation_request(request, conversation, history)):
                text += token.text
                data = json.dumps({"text": token.text, "index": token.index})
                yield f"event: token\ndata: {data}\n\n"
        except asyncio.CancelledError:
            # The request session is being cancelled; finalization must own a fresh session.
            finalization_task = asyncio.create_task(
                finalize_generation(
                    request.app.state.database.session_factory,
                    generation_id=generation_id,
                    status="cancelled",
                )
            )
            tasks: set[asyncio.Task[None]] = getattr(request.app.state, "generation_tasks", set())
            tasks.add(finalization_task)
            request.app.state.generation_tasks = tasks
            finalization_task.add_done_callback(tasks.discard)
            raise
        except Exception:
            await finalize_generation(
                request.app.state.database.session_factory,
                generation_id=generation_id,
                status="failed",
            )
            raise
        await finalize_generation(
            request.app.state.database.session_factory,
            generation_id=generation_id,
            status="complete",
            text=text,
        )
        complete_data = json.dumps(
            {"message_id": str(assistant.id), "generation_id": str(generation_id)}
        )
        yield f"event: complete\ndata: {complete_data}\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@router.post("/messages/{message_id}/retry", response_model=ChatResponse)
async def retry_message(
    message_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatResponse:
    original = await db.get(Message, message_id)
    if original is None or original.role != "assistant":
        raise HTTPException(status_code=404, detail="Assistant message not found")
    conversation = await owned_conversation(db, user, original.conversation_id)
    if original.status not in {"cancelled", "failed"}:
        raise HTTPException(
            status_code=409, detail="Only cancelled or failed messages can be retried"
        )
    previous_user = await db.scalar(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.role == "user",
            Message.created_at <= original.created_at,
        )
        .order_by(Message.created_at.desc())
    )
    if previous_user is None:
        raise HTTPException(status_code=409, detail="No preceding user message")
    history = await history_for(db, conversation.id)
    provider = create_provider(
        request.app.state.settings.model_provider, request.app.state.settings.model_endpoint
    )
    result = await provider.generate(generation_request(request, conversation, history))
    replacement = await store_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content=result.text,
        model=result.model,
    )
    replacement.parent_message_id = original.id
    replacement.input_tokens, replacement.output_tokens = result.input_tokens, result.output_tokens
    await db.commit()
    return ChatResponse(
        conversation_id=conversation.id,
        user_message_id=previous_user.id,
        assistant_message_id=replacement.id,
        content=result.text,
        model=result.model,
    )
