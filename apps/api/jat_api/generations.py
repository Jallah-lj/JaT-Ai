"""Independent, idempotent persistence for terminal generation states."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from jat_api.db.models import Message, MessagePart


async def finalize_generation(
    session_factory: async_sessionmaker,
    *,
    generation_id: UUID,
    status: str,
    text: str | None = None,
) -> None:
    """Finalize only streaming messages using a session independent of request cancellation."""
    async with session_factory() as session:
        message = await session.scalar(
            select(Message).where(Message.generation_id == generation_id).with_for_update()
        )
        if message is None or message.status != "streaming":
            return
        if status == "complete" and text is not None:
            session.add(MessagePart(message_id=message.id, position=0, kind="text", content=text))
            message.output_tokens = len(text.split())
        message.status = status
        await session.commit()
