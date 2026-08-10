"""JaT API application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException

from jat_api.api.v1 import api_router
from jat_api.config import Settings, get_settings
from jat_api.db import Database, RedisClient
from jat_api.db.clients import PingResult, any_backing_service_error
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

log = structlog.get_logger(__name__)


def _service_unavailable_response(service: str, detail: str | None) -> JSONResponse:
    """Build a 503 body that points the operator at the problem without leaking secrets."""
    message = f"Backing service '{service}' is unavailable"
    if detail:
        message += f": {detail}"
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": message,
            "service": service,
            "hint": (
                "Start the required services (see README: `docker compose up -d postgres redis`) "
                "and apply migrations with `make api-migrate`. Verify JAT_DATABASE_URL / "
                "JAT_REDIS_URL and credentials match docker-compose.yml."
            ),
        },
    )


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

        # ---- Backing service startup probe ---------------------------------
        # In staging/production hard-fail so the process exits and the process
        # supervisor/container orchestrator can restart it instead of serving
        # broken traffic. In development/test we allow startup to complete so
        # the developer can hit /live and /ready and inspect the hint.
        probes: list[PingResult] = [
            await app.state.database.ping_detailed(),
            await app.state.redis.ping_detailed(),
        ]
        failed = [p for p in probes if not p.ok]
        if failed:
            parts = ", ".join(f"{p.name}={p.detail or 'unreachable'}" for p in failed)
            if active_settings.environment in {"staging", "production"}:
                log.error(
                    "backing_services_unavailable",
                    services=parts,
                    env=active_settings.environment,
                )
                # Close what we opened before raising.
                await app.state.redis.close()
                await app.state.database.close()
                raise RuntimeError(
                    f"JaT cannot start: backing services unavailable ({parts}). "
                    "Check JAT_DATABASE_URL / JAT_REDIS_URL credentials and that "
                    "Postgres/Redis are running."
                )
            log.warning(
                "backing_services_unavailable",
                services=parts,
                env=active_settings.environment,
                ready_hint="GET /api/v1/health/ready for status; "
                "`docker compose up -d postgres redis` then `make api-migrate`.",
            )
        else:
            log.info("backing_services_ready", services=[p.name for p in probes])

        try:
            yield
        finally:
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

    # ---- Global exception handlers -----------------------------------------
    # Translate uncaught DB/Redis connection and authentication failures into
    # 503 responses with an actionable hint rather than leaking a stack trace
    # and a generic 500 to the client. We install a focused handler rather than
    # overriding the default HTTP/validation handlers so OpenAPI, 422, and
    # explicit HTTPException responses keep their documented shape.
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        # FastAPI/Starlette HTTPException and RequestValidationError are handled
        # by the framework's default handlers; re-raising from a custom handler
        # would not invoke them, so pass through known cases explicitly.
        if isinstance(exc, (StarletteHTTPException, HTTPException)):
            return JSONResponse(
                status_code=exc.status_code,
                headers=getattr(exc, "headers", None),
                content={"detail": exc.detail},
            )
        if isinstance(exc, RequestValidationError):
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"detail": exc.errors()},
            )
        service = any_backing_service_error(exc)
        if service is not None:
            log.warning(
                "backing_service_request_failure",
                service=service,
                path=request.url.path,
                method=request.method,
                error_type=type(exc).__name__,
            )
            detail: str | None = None
            if service == "postgres":
                detail = (await request.app.state.database.ping_detailed()).detail
            elif service == "redis":
                detail = (await request.app.state.redis.ping_detailed()).detail
            return _service_unavailable_response(service, detail)
        # Unknown errors: let them bubble to Starlette's 500 handler (which
        # honors debug mode and produces the usual traceback in development).
        raise exc

    return app


app = create_app()
