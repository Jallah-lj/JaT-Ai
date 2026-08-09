from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.auth.dependencies import current_user, get_db_session
from jat_api.settings.schemas import Preferences

router = APIRouter(prefix="/settings", tags=["settings"])


async def read(db: AsyncSession, user_id):
    row = await db.execute(
        text("select data from user_preferences where user_id=:id"), {"id": user_id}
    )
    value = row.scalar_one_or_none() or {}
    return Preferences.model_validate(value)


@router.get("", response_model=Preferences)
async def get_settings(user=Depends(current_user), db: AsyncSession = Depends(get_db_session)):
    return await read(db, user.id)


@router.patch("", response_model=Preferences)
async def update_settings(
    payload: Preferences, user=Depends(current_user), db: AsyncSession = Depends(get_db_session)
):
    await db.execute(
        text(
            "insert into user_preferences(user_id,data) values(:id,:data) "
            "on conflict(user_id) do update set data=excluded.data,updated_at=now()"
        ),
        {"id": user.id, "data": payload.model_dump_json()},
    )
    await db.commit()
    return payload
