"""Narrow infrastructure clients. Repositories will be added with migrations."""

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


class Database:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:  # readiness intentionally fails closed without exposing internals
            return False
        return True

    async def close(self) -> None:
        await self.engine.dispose()


class RedisClient:
    def __init__(self, url: str) -> None:
        self.client: Redis = Redis.from_url(url, decode_responses=True)

    async def ping(self) -> bool:
        try:
            return bool(await self.client.ping())
        except Exception:  # readiness intentionally fails closed without exposing internals
            return False

    async def close(self) -> None:
        await self.client.aclose()
