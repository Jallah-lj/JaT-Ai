from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from jat_api.config import Settings
from jat_api.main import create_app


class HealthyDependency:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class UnhealthyDependency(HealthyDependency):
    async def ping(self) -> bool:
        return False


def test_liveness_has_request_id_and_security_headers() -> None:
    app = create_app(Settings(environment="testing"))
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_readiness_degrades_without_backing_services() -> None:
    @asynccontextmanager
    async def fake_lifespan(app: object):
        app.state.settings = Settings(environment="testing")  # type: ignore[attr-defined]
        app.state.database = HealthyDependency()  # type: ignore[attr-defined]
        app.state.redis = UnhealthyDependency()  # type: ignore[attr-defined]
        yield

    app = create_app(Settings(environment="testing"))
    app.router.lifespan_context = fake_lifespan
    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_production_rejects_placeholder_secret() -> None:
    try:
        Settings(environment="production")
    except ValueError as error:
        assert "JAT_JWT_SECRET" in str(error)
    else:
        raise AssertionError("production settings accepted insecure secret")


def test_cross_origin_refresh_cookie_is_rejected_before_database_access() -> None:
    app = create_app(Settings(environment="testing", cors_origins=["https://app.jat.test"]))
    with TestClient(app) as client:
        client.cookies.set("jat_refresh_token", "test-token", path="/api/v1/auth")
        response = client.post("/api/v1/auth/refresh", headers={"origin": "https://evil.test"})
    assert response.status_code == 403
    assert response.json()["type"].endswith("csrf-rejected")
