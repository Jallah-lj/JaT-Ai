"""Redis-backed fixed-window rate limiting with conservative production failure behavior."""

from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class RedisRateLimiter:
    def __init__(self, client: Redis, *, fail_closed: bool) -> None:
        self.client = client
        self.fail_closed = fail_closed

    async def consume(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        try:
            count = await self.client.incr(key)
            if count == 1:
                await self.client.expire(key, window_seconds)
            ttl = await self.client.ttl(key)
        except Exception:
            return RateLimitDecision(
                allowed=not self.fail_closed, retry_after_seconds=window_seconds
            )
        return RateLimitDecision(
            allowed=count <= limit,
            retry_after_seconds=max(1, ttl if ttl > 0 else window_seconds),
        )
