from uuid import uuid4

import jwt
import pytest

from jat_api.auth.security import (
    access_token_subject,
    hash_password,
    issue_access_token,
    new_refresh_token,
    token_hash,
    verify_password,
)
from jat_api.config import Settings


def test_password_hash_never_equals_password_and_rejects_wrong_password() -> None:
    password_hash = hash_password("correct horse battery staple")
    assert password_hash != "correct horse battery staple"
    assert verify_password(password_hash, "correct horse battery staple")
    assert not verify_password(password_hash, "wrong password")


def test_access_token_is_scoped_to_issuer_audience_and_subject() -> None:
    settings = Settings(environment="testing", jwt_secret="a" * 32)
    user_id = uuid4()
    token = issue_access_token(user_id, settings)
    assert access_token_subject(token, settings) == user_id
    with pytest.raises(jwt.InvalidTokenError):
        access_token_subject(token, Settings(environment="testing", jwt_secret="b" * 32))


def test_refresh_tokens_are_unpredictable_and_only_hashes_are_persistable() -> None:
    first, second = new_refresh_token(), new_refresh_token()
    assert first != second
    assert len(first) >= 64
    assert token_hash(first) != first
    assert token_hash(first) != token_hash(second)


class FakeRedis:
    def __init__(self) -> None:
        self.value = 0

    async def incr(self, _: str) -> int:
        self.value += 1
        return self.value

    async def expire(self, _: str, __: int) -> bool:
        return True

    async def ttl(self, _: str) -> int:
        return 42


@pytest.mark.asyncio
async def test_redis_limiter_rejects_attempts_above_limit() -> None:
    from jat_api.security.rate_limit import RedisRateLimiter

    limiter = RedisRateLimiter(FakeRedis(), fail_closed=True)  # type: ignore[arg-type]
    assert (await limiter.consume(key="test", limit=2, window_seconds=60)).allowed
    assert (await limiter.consume(key="test", limit=2, window_seconds=60)).allowed
    result = await limiter.consume(key="test", limit=2, window_seconds=60)
    assert not result.allowed
    assert result.retry_after_seconds == 42
