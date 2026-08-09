"""JaT API application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from jat_api.api.v1 import api_router
from jat_api.config import Settings, get_settings
from jat_api.db import Database, RedisClient
from jat_api.middleware.csrf import CsrfOriginMiddleware
from jat_api.middleware.rate_limit import AuthenticationRateLimitMiddleware
from jat_api.middleware.request_context import RequestContextMiddleware
from jat_api.observability.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a configured application without reaching backing services."""
    active_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(active_settings.log_level)
        app.state.settings = active_settings
        app.state.database = Database(active_settings.database_url)
        app.state.redis = RedisClient(active_settings.redis_url)
        yield
        await app.state.redis.close()
        await app.state.database.close()

    app = FastAPI(
        title="JaT API",
        version=active_settings.service_version,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        RequestContextMiddleware, max_request_bytes=active_settings.request_max_bytes
    )
    app.add_middleware(CsrfOriginMiddleware, allowed_origins=set(active_settings.cors_origins))
    app.add_middleware(
        AuthenticationRateLimitMiddleware,
        limit=active_settings.auth_rate_limit_attempts,
        window_seconds=active_settings.auth_rate_limit_window_seconds,
        fail_closed=active_settings.environment in {"staging", "production"},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
    )
    app.include_router(api_router, prefix=active_settings.api_prefix)
    app.mount("/metrics", make_asgi_app())
    return app


app = create_app()
