"""Unit tests for ingestion policy, parsing, chunking, storage, dispatch, and retrieval."""

from __future__ import annotations

import hashlib
import itertools
import json
import uuid
from pathlib import Path

import pytest

from jat_api.ingestion.chunking import chunk_text
from jat_api.ingestion.dispatch import LocalIngestionDispatcher, RedisIngestionDispatcher
from jat_api.ingestion.extraction import IngestionError, extract_text
from jat_api.ingestion.jobs import IngestionJob, job_from_json, job_from_payload, job_to_payload
from jat_api.ingestion.policy import MAX_BYTES, validate_upload_metadata
from jat_api.ingestion.transitions import can_transition
from jat_api.rag.contracts import DocumentChunk
from jat_api.rag.retrieval import retrieve
from jat_api.rag.store import InMemoryVectorStore, cosine_similarity
from jat_api.storage import LocalObjectStore, ObjectNotFoundError, ObjectStoreKeyError


class FakeEmbedder:
    name = "fake-embedding"

    def __init__(self, vector: list[float]) -> None:
        self.vector = vector

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vector for _ in texts]


# --- policy -----------------------------------------------------------------


def test_policy_rejects_unsupported_type_and_bad_size() -> None:
    with pytest.raises(ValueError, match="Unsupported content type"):
        validate_upload_metadata("application/x-msdownload", 100)
    with pytest.raises(ValueError, match="Invalid upload size"):
        validate_upload_metadata("text/plain", 0)
    with pytest.raises(ValueError, match="Invalid upload size"):
        validate_upload_metadata("text/plain", MAX_BYTES + 1)
    validate_upload_metadata("text/markdown", 1024)


def test_status_transitions_follow_the_finite_model() -> None:
    assert can_transition("pending", "validating")
    assert can_transition("embedding", "ready")
    assert can_transition("parsing", "failed")
    assert not can_transition("ready", "parsing")
    assert not can_transition("failed", "validating")
    assert not can_transition("pending", "embedding")


# --- job payloads -----------------------------------------------------------


def test_job_payload_roundtrip_and_validation() -> None:
    job = IngestionJob(
        document_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        object_key="quarantine/org/obj",
        declared_content_type="text/plain",
        source="handbook.md",
        license="CC-BY-4.0",
    )
    assert job_from_json(json.dumps(job_to_payload(job))) == job
    with pytest.raises(ValueError, match="must be an object"):
        job_from_payload(["not", "a", "dict"])
    with pytest.raises(ValueError, match="missing field"):
        job_from_payload({"document_id": str(uuid.uuid4())})
    with pytest.raises(ValueError):
        job_from_payload({**job_to_payload(job), "document_id": "not-a-uuid"})


# --- extraction -------------------------------------------------------------


def test_extract_text_decodes_supported_types() -> None:
    assert extract_text("text/plain", "héllo wörld".encode()) == "héllo wörld"
    assert extract_text("text/markdown", b"\xef\xbb\xbf# Title") == "# Title"


def test_extract_text_rejects_unparseable_types_and_binary() -> None:
    with pytest.raises(IngestionError, match="not enabled yet"):
        extract_text("application/pdf", b"%PDF-1.4")
    with pytest.raises(IngestionError, match="do not look like text"):
        extract_text("text/plain", b"\x00" * 128)
    with pytest.raises(IngestionError, match="no extractable text"):
        extract_text("text/plain", b"   \n  ")


# --- chunking ---------------------------------------------------------------


def test_chunking_keeps_small_documents_whole() -> None:
    assert chunk_text("alpha beta gamma", 1000, 200) == ["alpha beta gamma"]


def test_chunking_packs_paragraphs_and_overlaps() -> None:
    paragraphs = "\n\n".join(f"paragraph-{index} " + "x" * 280 for index in range(8))
    chunks = chunk_text(paragraphs, 1000, 200)
    assert len(chunks) >= 3
    assert all(len(chunk) <= 1000 for chunk in chunks)
    # Overlap: the tail of one chunk reappears at the head of the next.
    for previous, following in itertools.pairwise(chunks):
        assert following[:80] in previous or previous[-80:] in following


def test_chunking_hard_wraps_oversized_paragraphs() -> None:
    wall_of_text = "word " * 900  # single paragraph ~4.5k chars
    chunks = chunk_text(wall_of_text, 1000, 200)
    assert len(chunks) >= 5
    assert all(len(chunk) <= 1000 for chunk in chunks)


def test_chunking_enforces_limit_and_rejects_empty() -> None:
    with pytest.raises(IngestionError, match="chunk ingestion limit"):
        chunk_text("\n\n".join("p" * 800 for _ in range(600)), 1000, 200)
    with pytest.raises(IngestionError, match="no extractable text"):
        chunk_text("   ", 1000, 200)
    with pytest.raises(ValueError, match="smaller than the chunk size"):
        chunk_text("hello", 200, 200)


# --- cosine + in-memory vector store ----------------------------------------


def test_cosine_similarity_math_and_edge_cases() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([1.0], [1.0, 2.0]) is None
    assert cosine_similarity([], []) is None
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) is None


def _chunk(document_id: uuid.UUID, vector: list[float], metadata: dict[str, str]) -> DocumentChunk:
    return DocumentChunk(
        id=uuid.uuid4(),
        document_id=document_id,
        content="text",
        embedding=vector,
        metadata=metadata,
    )


async def test_in_memory_store_filters_and_ranks() -> None:
    store = InMemoryVectorStore()
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    doc = uuid.uuid4()
    metadata_a = {"organization_id": str(org_a), "embedding_model": "m1", "source": "a.md"}
    await store.upsert([_chunk(doc, [1.0, 0.0], metadata_a)])
    await store.upsert([_chunk(doc, [0.0, 1.0], metadata_a)])
    await store.upsert(
        [_chunk(doc, [1.0, 0.0], {"organization_id": str(org_b), "embedding_model": "m1"})]
    )
    await store.upsert(
        [_chunk(doc, [1.0, 0.0], {"organization_id": str(org_a), "embedding_model": "m2"})]
    )

    hits = await store.search(
        [0.9, 0.1], limit=5, filters={"organization_id": str(org_a), "embedding_model": "m1"}
    )
    assert [score_hit.score for score_hit in hits] == sorted(
        (score_hit.score for score_hit in hits), reverse=True
    )
    assert len(hits) == 2  # other org and other embedding model excluded

    await store.delete(doc)
    assert (
        await store.search(
            [1.0, 0.0], limit=5, filters={"organization_id": str(org_a), "embedding_model": "m1"}
        )
        == []
    )


async def test_in_memory_store_fails_closed_on_filters() -> None:
    store = InMemoryVectorStore()
    with pytest.raises(ValueError, match="Unsupported retrieval filters"):
        await store.search([1.0], limit=1, filters={"organization_id": "x", "tenant_id": "y"})
    with pytest.raises(ValueError, match="organization_id is required"):
        await store.search([1.0], limit=1, filters={"embedding_model": "m"})
    with pytest.raises(ValueError, match="embedding_model is required"):
        await store.search([1.0], limit=1, filters={"organization_id": "x"})


async def test_retrieve_maps_hits_to_attributed_citations() -> None:
    org = uuid.uuid4()
    doc = uuid.uuid4()
    store = InMemoryVectorStore()
    await store.upsert(
        [
            DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc,
                chunk_index=0,
                content="JaT keeps providers replaceable. " * 20,
                embedding=[1.0, 0.0],
                metadata={
                    "organization_id": str(org),
                    "knowledge_base_id": str(uuid.uuid4()),
                    "embedding_model": "fake-embedding",
                    "source": "ARCHITECTURE.md",
                    "license": "Apache-2.0",
                },
            )
        ]
    )
    citations = await retrieve(
        embedder=FakeEmbedder([1.0, 0.0]),
        store=store,
        organization_id=org,
        query="architecture",
        limit=5,
    )
    assert len(citations) == 1
    citation = citations[0]
    assert citation.source == "ARCHITECTURE.md"
    assert citation.license == "Apache-2.0"
    assert len(citation.content_preview) <= 320
    payload = citation.to_dict()
    assert payload["document_id"] == str(doc)
    assert 0.5 <= float(str(payload["score"])) <= 1.0


# --- object storage ---------------------------------------------------------


async def test_local_object_store_roundtrip_and_missing(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    await store.put("quarantine/org/object-1", b"payload")
    assert await store.get("quarantine/org/object-1") == b"payload"
    await store.delete("quarantine/org/object-1")
    await store.delete("quarantine/org/object-1")  # idempotent
    with pytest.raises(ObjectNotFoundError):
        await store.get("quarantine/org/object-1")


async def test_local_object_store_rejects_evil_keys(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    for key in ("../escape", "quarantine/../../etc/passwd", "/absolute/path", "a" * 600, "sp ace"):
        with pytest.raises(ObjectStoreKeyError):
            await store.put(key, b"x")
    outside = tmp_path / "secret"
    outside.write_bytes(b"secret")
    with pytest.raises(ObjectStoreKeyError):
        await store.get("../secret")
    # The traversal was blocked entirely, not just the read.
    assert outside.read_bytes() == b"secret"


# --- dispatchers ------------------------------------------------------------


async def test_local_dispatcher_records_jobs() -> None:
    dispatcher = LocalIngestionDispatcher()
    job = IngestionJob(uuid.uuid4(), uuid.uuid4(), "k", "text/plain", "s", "l")
    await dispatcher.dispatch(job)
    assert dispatcher.jobs == [job]


class RecordingRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.calls.append((key, value))


async def test_redis_dispatcher_serializes_onto_list() -> None:
    client = RecordingRedis()
    dispatcher = RedisIngestionDispatcher(client, "jat:ingestion")  # type: ignore[arg-type]
    job = IngestionJob(uuid.uuid4(), uuid.uuid4(), "key", "text/plain", "s", "l")
    await dispatcher.dispatch(job)
    assert client.calls[0][0] == "jat:ingestion"
    assert job_from_json(client.calls[0][1]) == job


# --- hashing helpers used by the upload route --------------------------------


def test_sha256_matches_upload_contract() -> None:
    digest = hashlib.sha256(b"content").hexdigest()
    assert len(digest) == 64 and digest.islower()
