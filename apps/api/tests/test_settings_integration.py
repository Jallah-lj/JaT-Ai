"""End-to-end settings API tests.

Skipped unless JAT_TEST_DATABASE_URL points at a disposable PostgreSQL database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

from jat_api.config import Settings
from jat_api.main import create_app

DATABASE_URL = os.environ.get("JAT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="JAT_TEST_DATABASE_URL is not configured")


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        environment="testing",
        database_url=str(DATABASE_URL),
        redis_url=os.environ.get("JAT_TEST_REDIS_URL", "redis://127.0.0.1:6379/1"),
        jwt_secret="integration-test-secret-value-32-characters",
        # Every test registers from the same client IP; the limiter is exercised
        # separately in the auth suite.
        auth_rate_limit_attempts=100,
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def register(http: httpx.AsyncClient) -> tuple[str, dict[str, str]]:
    email = f"settings-{uuid.uuid4().hex[:12]}@example.com"
    response = await http.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": "Ada Lovelace",
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return email, {"Authorization": f"Bearer {token}"}


async def test_settings_require_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/settings")).status_code == 401


async def test_defaults_are_returned_before_anything_is_saved(
    client: httpx.AsyncClient,
) -> None:
    _, headers = await register(client)
    body = (await client.get("/api/v1/settings", headers=headers)).json()
    assert body["theme"] == "system"
    assert body["memories"] == []


async def test_patch_persists_and_preserves_unrelated_fields(
    client: httpx.AsyncClient,
) -> None:
    _, headers = await register(client)
    await client.patch(
        "/api/v1/settings", headers=headers, json={"theme": "dark", "accent": "ocean"}
    )
    body = (
        await client.patch("/api/v1/settings", headers=headers, json={"temperature": 0.75})
    ).json()
    assert body["temperature"] == 0.75
    assert body["theme"] == "dark"
    assert body["accent"] == "ocean"

    # A fresh read returns the same document.
    reread = (await client.get("/api/v1/settings", headers=headers)).json()
    assert reread == body


async def test_invalid_values_are_rejected(client: httpx.AsyncClient) -> None:
    _, headers = await register(client)
    assert (
        await client.patch("/api/v1/settings", headers=headers, json={"theme": "neon"})
    ).status_code == 422
    assert (
        await client.patch("/api/v1/settings", headers=headers, json={"is_admin": True})
    ).status_code == 422


async def test_reset_restores_defaults(client: httpx.AsyncClient) -> None:
    _, headers = await register(client)
    await client.patch("/api/v1/settings", headers=headers, json={"theme": "dark"})
    body = (await client.post("/api/v1/settings/reset", headers=headers)).json()
    assert body["theme"] == "system"


async def test_memory_lifecycle(client: httpx.AsyncClient) -> None:
    _, headers = await register(client)
    await client.post("/api/v1/settings/memories", headers=headers, json={"text": "first"})
    body = (
        await client.post("/api/v1/settings/memories", headers=headers, json={"text": "second"})
    ).json()
    assert body["memories"] == ["first", "second"]

    body = (await client.delete("/api/v1/settings/memories/0", headers=headers)).json()
    assert body["memories"] == ["second"]

    assert (await client.delete("/api/v1/settings/memories/9", headers=headers)).status_code == 404

    body = (await client.delete("/api/v1/settings/memories", headers=headers)).json()
    assert body["memories"] == []


async def test_profile_update_and_duplicate_email_conflict(
    client: httpx.AsyncClient,
) -> None:
    first_email, _ = await register(client)
    _, headers = await register(client)

    body = (
        await client.patch(
            "/api/v1/settings/profile", headers=headers, json={"display_name": "Ada L."}
        )
    ).json()
    assert body["display_name"] == "Ada L."

    conflict = await client.patch(
        "/api/v1/settings/profile", headers=headers, json={"email": first_email}
    )
    assert conflict.status_code == 409


async def test_password_change_requires_the_current_password(
    client: httpx.AsyncClient,
) -> None:
    _, headers = await register(client)
    wrong = await client.post(
        "/api/v1/settings/password",
        headers=headers,
        json={"current_password": "nope", "new_password": "a-brand-new-password"},
    )
    assert wrong.status_code == 401

    correct = await client.post(
        "/api/v1/settings/password",
        headers=headers,
        json={
            "current_password": "correct horse battery staple",
            "new_password": "a-brand-new-password",
        },
    )
    assert correct.status_code == 200


async def test_current_session_is_identified_and_preserved(
    client: httpx.AsyncClient,
) -> None:
    _, headers = await register(client)
    sessions = (await client.get("/api/v1/settings/sessions", headers=headers)).json()
    assert len(sessions) == 1
    assert sessions[0]["current"] is True

    result = (await client.post("/api/v1/settings/sessions/revoke-others", headers=headers)).json()
    assert result["removed"] == 0
    still_valid = (await client.get("/api/v1/settings/sessions", headers=headers)).json()
    assert len(still_valid) == 1


async def test_models_reflect_server_configuration(client: httpx.AsyncClient) -> None:
    _, headers = await register(client)
    models = (await client.get("/api/v1/settings/models", headers=headers)).json()
    assert models[0]["available"] is True
    # Ollama is unavailable without a configured endpoint.
    assert any(model["id"] == "ollama" and not model["available"] for model in models)


async def test_export_contains_account_and_preferences(
    client: httpx.AsyncClient,
) -> None:
    email, headers = await register(client)
    await client.patch("/api/v1/settings", headers=headers, json={"theme": "dark"})
    export = (await client.get("/api/v1/settings/export", headers=headers)).json()
    assert export["account"]["email"] == email
    assert export["preferences"]["theme"] == "dark"
    assert export["conversations"] == []


async def test_usage_starts_empty(client: httpx.AsyncClient) -> None:
    _, headers = await register(client)
    usage = (await client.get("/api/v1/settings/usage", headers=headers)).json()
    assert usage == {
        "conversations": 0,
        "messages": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "first_activity_at": None,
        "last_activity_at": None,
    }


async def test_account_deletion_requires_confirmation_then_blocks_access(
    client: httpx.AsyncClient,
) -> None:
    _, headers = await register(client)
    assert (
        await client.post(
            "/api/v1/settings/delete-account",
            headers=headers,
            json={"password": "correct horse battery staple", "confirmation": "nope"},
        )
    ).status_code == 422
    assert (
        await client.post(
            "/api/v1/settings/delete-account",
            headers=headers,
            json={"password": "wrong", "confirmation": "DELETE"},
        )
    ).status_code == 401

    deleted = await client.post(
        "/api/v1/settings/delete-account",
        headers=headers,
        json={"password": "correct horse battery staple", "confirmation": "DELETE"},
    )
    assert deleted.status_code == 204
    # The access token must no longer resolve to an active user.
    assert (await client.get("/api/v1/settings", headers=headers)).status_code == 401


async def test_revoking_a_session_invalidates_its_access_token_immediately(
    client: httpx.AsyncClient,
) -> None:
    email, first_headers = await register(client)
    second = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct horse battery staple"},
    )
    second_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}

    # Both sessions work before revocation.
    assert (await client.get("/api/v1/settings", headers=first_headers)).status_code == 200
    assert (await client.get("/api/v1/settings", headers=second_headers)).status_code == 200

    revoked = await client.post("/api/v1/settings/sessions/revoke-others", headers=second_headers)
    assert revoked.json()["removed"] == 1

    # The revoked device loses access at once; the caller keeps working.
    assert (await client.get("/api/v1/settings", headers=first_headers)).status_code == 401
    assert (await client.get("/api/v1/settings", headers=second_headers)).status_code == 200
