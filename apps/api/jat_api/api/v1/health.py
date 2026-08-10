"""Liveness and readiness endpoints."""

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


class ServiceStatus(BaseModel):
    ok: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    services: dict[str, ServiceStatus] | None = None


async def _probe(svc: object, default_name: str) -> tuple[str, ServiceStatus]:
    """Probe a backing service, tolerating both old (ping) and new (ping_detailed) clients."""
    detailed = getattr(svc, "ping_detailed", None)
    if callable(detailed):
        result = await detailed()
        # Supports both PingResult (has .ok/.detail/.name) and plain booleans.
        ok = bool(getattr(result, "ok", result))
        detail = getattr(result, "detail", None)
        svc_name = str(getattr(result, "name", default_name))
        return svc_name, ServiceStatus(ok=ok, detail=detail)
    # Legacy client only exposes ``ping() -> bool``.
    ping = getattr(svc, "ping", None)
    ok = bool(await ping()) if callable(ping) else False
    return default_name, ServiceStatus(ok=ok, detail=None if ok else "unreachable")


async def _service_checks(request: Request) -> dict[str, ServiceStatus]:
    db_name, db_status = await _probe(request.app.state.database, "postgres")
    rd_name, rd_status = await _probe(request.app.state.redis, "redis")
    return {db_name: db_status, rd_name: rd_status}


@router.get("/live", response_model=HealthResponse)
async def live(request: Request) -> HealthResponse:
    # Liveness is intentionally shallow: if the event loop is serving requests,
    # the process is alive. Backing-service health belongs in /ready.
    return HealthResponse(status="ok", version=request.app.state.settings.service_version)


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request, response: Response) -> HealthResponse:
    services = await _service_checks(request)
    healthy = all(s.ok for s in services.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded",
        version=request.app.state.settings.service_version,
        services=services,
    )


@router.get("", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return HealthResponse(status="ok", version=request.app.state.settings.service_version)
