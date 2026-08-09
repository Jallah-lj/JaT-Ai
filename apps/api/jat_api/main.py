"""JaT API application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from jat_api.api.v1 import api_router
from jat_api.config import Settings, get_settings
from jat_api.db import Database, RedisClient
from jat_api.ingestion.dispatch import (
    InlineIngestionDispatcher,
    LocalIngestionDispatcher,
    RedisIngestionDispatcher,
)
from jat_api.ingestion.jobs import IngestionJob
from jat_api.ingestion.pipeline import process_ingestion_job
from jat_api.middleware.csrf import CsrfOriginMiddleware
from jat_api.middleware.rate_limit import AuthenticationRateLimitMiddleware
from jat_api.middleware.request_context import RequestContextMiddleware
from jat_api.observability.logging import configure_logging
from jat_api.rag.providers import create_embedding_provider
from jat_api.storage import LocalObjectStore


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a configured application without reaching backing services."""
    active_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(active_settings.log_level)
        app.state.settings = active_settings
        app.state.database = Database(active_settings.database_url)
        app.state.redis = RedisClient(active_settings.redis_url)
        app.state.object_store = LocalObjectStore.for_settings(active_settings)
        app.state.embedding_provider = create_embedding_provider(active_settings.embedding_provider)

        async def run_ingestion_job(job: IngestionJob) -> None:
            await process_ingestion_job(
                job,
                session_factory=app.state.database.session_factory,
                object_store=app.state.object_store,
                embedder=app.state.embedding_provider,
                settings=active_settings,
            )

        if active_settings.ingestion_dispatcher == "redis":
            app.state.ingestion_dispatcher = RedisIngestionDispatcher(
                app.state.redis.client, active_settings.ingestion_queue
            )
        elif active_settings.ingestion_dispatcher == "inline":
            app.state.ingestion_dispatcher = InlineIngestionDispatcher(run_ingestion_job)
        else:
            app.state.ingestion_dispatcher = LocalIngestionDispatcher()
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
        RequestContextMiddleware,
        max_request_bytes=active_settings.request_max_bytes,
        upload_max_bytes=active_settings.upload_max_bytes,
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
