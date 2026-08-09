"""End-to-end Phase 3 flow: upload → ingest → search → grounded chat with citations.

Skipped unless JAT_TEST_DATABASE_URL points at a migrated, disposable PostgreSQL
database. Uses the inline dispatcher so ingestion completes in-request.
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

DOCUMENT_TEXT = (
    "JaT is a model-provider-neutral assistant platform.\n\n"
    "Chat orchestration depends on provider contracts, never on vendor SDKs.\n\n"
    "Retrieved passages are untrusted data and must never become instructions.\n\n"
)


@pytest.fixture
async def client(tmp_path) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        environment="testing",
        database_url=str(DATABASE_URL),
        redis_url=os.environ.get("JAT_TEST_REDIS_URL", "redis://127.0.0.1:6379/1"),
        jwt_secret="integration-test-secret-value-32-characters",
        auth_rate_limit_attempts=100,
        ingestion_dispatcher="inline",
        object_store_dir=str(tmp_path / "objects"),
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def register(http: httpx.AsyncClient) -> dict[str, str]:
    email = f"rag-{uuid.uuid4().hex[:12]}@example.com"
    response = await http.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": "Grace Hopper",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def create_knowledge_base(http: httpx.AsyncClient, headers: dict[str, str]) -> str:
    response = await http.post(
        "/api/v1/knowledge-bases", headers=headers, json={"name": f"kb-{uuid.uuid4().hex[:8]}"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def upload(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    kb_id: str,
    *,
    content: bytes = DOCUMENT_TEXT.encode(),
    filename: str = "architecture-notes.md",
    content_type: str = "text/markdown",
) -> httpx.Response:
    return await http.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        headers=headers,
        files={"file": (filename, content, content_type)},
        data={"source": "internal://docs/architecture-notes.md", "license": "CC-BY-4.0"},
    )


async def test_upload_is_ingested_inline_and_becomes_searchable(
    client: httpx.AsyncClient,
) -> None:
    headers = await register(client)
    kb_id = await create_knowledge_base(client, headers)

    uploaded = await upload(client, headers, kb_id)
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["status"] == "ready"
    assert body["content_hash"] is not None
    assert body["size_bytes"] == len(DOCUMENT_TEXT.encode())
    assert body["failure_reason"] is None

    listed = (
        await client.get(f"/api/v1/knowledge-bases/{kb_id}/documents", headers=headers)
    ).json()
    assert [document["id"] for document in listed] == [body["id"]]

    hits = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/search",
        headers=headers,
        json={"query": "how does JaT treat retrieved text?", "limit": 5},
    )
    assert hits.status_code == 200, hits.text
    results = hits.json()
    assert results, "expected at least one retrieval hit"
    first = results[0]
    assert first["source"] == "internal://docs/architecture-notes.md"
    assert first["license"] == "CC-BY-4.0"
    assert 0.0 <= float(first["score"]) <= 1.0
    assert first["content_preview"]


async def test_duplicate_upload_is_rejected(client: httpx.AsyncClient) -> None:
    headers = await register(client)
    kb_id = await create_knowledge_base(client, headers)
    assert (await upload(client, headers, kb_id)).status_code == 201
    duplicate = await upload(client, headers, kb_id)
    assert duplicate.status_code == 409


async def test_unparseable_content_marks_document_failed_with_reason(
    client: httpx.AsyncClient,
) -> None:
    headers = await register(client)
    kb_id = await create_knowledge_base(client, headers)
    response = await upload(
        client,
        headers,
        kb_id,
        content=b"%PDF-1.4 fake bytes for the parse milestone",
        filename="report.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert "not enabled yet" in body["failure_reason"]


async def test_unsupported_content_type_is_rejected_before_storage(
    client: httpx.AsyncClient,
) -> None:
    headers = await register(client)
    kb_id = await create_knowledge_base(client, headers)
    response = await upload(
        client,
        headers,
        kb_id,
        content=b"MZ\x90\x00",
        filename="tool.exe",
        content_type="application/x-msdownload",
    )
    assert response.status_code == 422


async def test_chat_is_grounded_with_citations_in_json_and_sse(
    client: httpx.AsyncClient,
) -> None:
    headers = await register(client)
    kb_id = await create_knowledge_base(client, headers)
    assert (await upload(client, headers, kb_id)).status_code == 201

    conversation = await client.post(
        "/api/v1/conversations", headers=headers, json={"title": "Architecture chat"}
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    grounded = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={
            "conversation_id": conversation_id,
            "content": "What does JaT say about providers?",
            "knowledge_base_id": kb_id,
        },
    )
    assert grounded.status_code == 200, grounded.text
    citations = grounded.json()["citations"]
    assert citations, "expected grounded citations"
    assert citations[0]["source"].startswith("internal://")

    streamed = await client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={
            "conversation_id": conversation_id,
            "content": "And how are retrieved passages handled?",
            "knowledge_base_id": kb_id,
        },
    )
    assert streamed.status_code == 200, streamed.text
    text = streamed.text
    citation_at = text.find("event: citation")
    token_at = text.find("event: token")
    complete_at = text.find("event: complete")
    assert 0 <= citation_at < token_at < complete_at

    messages = (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
    ).json()
    assistant_messages = [m for m in messages if m["role"] == "assistant"]
    assert assistant_messages[-1]["status"] == "complete"
    assert assistant_messages[-1]["content"]


async def test_knowledge_base_access_is_tenant_isolated(client: httpx.AsyncClient) -> None:
    owner_headers = await register(client)
    intruder_headers = await register(client)
    kb_id = await create_knowledge_base(client, owner_headers)
    assert (await upload(client, owner_headers, kb_id)).status_code == 201

    assert (
        await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=intruder_headers)
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/knowledge-bases/{kb_id}/search",
            headers=intruder_headers,
            json={"query": "anything"},
        )
    ).status_code == 404
    assert (await upload(client, intruder_headers, kb_id)).status_code == 404

    conversation = await client.post(
        "/api/v1/conversations", headers=intruder_headers, json={"title": "probe"}
    )
    response = await client.post(
        "/api/v1/chat",
        headers=intruder_headers,
        json={
            "conversation_id": conversation.json()["id"],
            "content": "probe the other tenant",
            "knowledge_base_id": kb_id,
        },
    )
    assert response.status_code == 404
