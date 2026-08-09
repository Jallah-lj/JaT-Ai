"""Route-specific API abuse protection."""

import hashlib

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from jat_api.security.rate_limit import RedisRateLimiter


class AuthenticationRateLimitMiddleware(BaseHTTPMiddleware):
    """Limit credential endpoints per client IP without logging the raw address."""

    def __init__(self, app: object, *, limit: int, window_seconds: int, fail_closed: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.limit = limit
        self.window_seconds = window_seconds
        self.fail_closed = fail_closed

    async def dispatch(self, request: Request, call_next: object) -> Response:
        protected = request.url.path.endswith("/auth/register") or request.url.path.endswith(
            "/auth/login"
        )
        if not protected or request.method != "POST":
            return await call_next(request)  # type: ignore[operator]
        client_ip = request.client.host if request.client else "unknown"
        key_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
        limiter = RedisRateLimiter(request.app.state.redis.client, fail_closed=self.fail_closed)
        decision = await limiter.consume(
            key=f"jat:ratelimit:auth:{key_hash}",
            limit=self.limit,
            window_seconds=self.window_seconds,
        )
        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(decision.retry_after_seconds)},
                content={
                    "type": "https://jat.ai/problems/rate-limited",
                    "title": "Too many authentication attempts",
                    "status": 429,
                },
            )
        return await call_next(request)  # type: ignore[operator]
