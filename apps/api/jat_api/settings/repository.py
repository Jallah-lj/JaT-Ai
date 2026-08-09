"""Persistence for user preferences, isolated from HTTP concerns."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.db.models import UserPreference
from jat_api.settings.schemas import Preferences, PreferencesUpdate


async def load_preferences(db: AsyncSession, user_id: UUID) -> Preferences:
    """Return stored preferences, filling any missing key with its default."""
    record = await db.get(UserPreference, user_id)
    stored = record.data if record is not None and isinstance(record.data, dict) else {}
    return Preferences.model_validate(stored)


async def save_preferences(
    db: AsyncSession, user_id: UUID, preferences: Preferences
) -> Preferences:
    """Upsert the full preference document for a user."""
    payload = preferences.model_dump(mode="json")
    statement = (
        insert(UserPreference)
        .values(user_id=user_id, data=payload)
        .on_conflict_do_update(index_elements=[UserPreference.user_id], set_={"data": payload})
    )
    await db.execute(statement)
    return preferences


async def apply_patch(db: AsyncSession, user_id: UUID, patch: PreferencesUpdate) -> Preferences:
    """Merge a partial update onto the stored document and persist the result."""
    current = await load_preferences(db, user_id)
    changes = patch.model_dump(exclude_unset=True, exclude_none=True)
    merged = Preferences.model_validate({**current.model_dump(mode="json"), **changes})
    return await save_preferences(db, user_id, merged)
