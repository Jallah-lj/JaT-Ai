"""Vector store adapters.

``PostgresVectorStore`` indexes chunk embeddings in PostgreSQL ``float8[]``
columns and ranks with a pure-SQL cosine similarity. This runs on any supported
PostgreSQL without extensions — deliberate so CI, local development, and vanilla
deployments work identically. When deployment data outgrows sequential scans,
swap the embedding column and search expression for ``pgvector`` (documented in
docs/RAG.md); the ``VectorStore`` contract does not change.

``InMemoryVectorStore`` is a deterministic test/dev fixture.
"""

from __future__ import annotations

import math
from uuid import UUID

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.db.models import DocumentChunk as DocumentChunkRow
from jat_api.rag.contracts import DocumentChunk, RetrievalHit

# Filters are an explicit allowlist — never build filter SQL from request strings.
_FILTER_KEYS = {"organization_id", "knowledge_base_id", "embedding_model"}

_SEARCH_SQL = text(
    """
    SELECT c.id, c.document_id, c.content, c.metadata,
           d.source, d.license,
           s.dot / NULLIF(s.norm_c * s.norm_q, 0) AS score
    FROM document_chunks c
    JOIN documents d ON d.id = c.document_id
    JOIN knowledge_bases kb ON kb.id = d.knowledge_base_id
    CROSS JOIN LATERAL (
        SELECT sum(a * b) AS dot,
               sqrt(sum(a * a)) AS norm_c,
               sqrt(sum(b * b)) AS norm_q
        FROM unnest(c.embedding, CAST(:query AS float8[])) AS pair(a, b)
    ) s
    WHERE kb.organization_id = :organization_id
      AND d.status = 'ready'
      AND c.embedding_model = :embedding_model
      AND c.embedding IS NOT NULL
      AND s.dot IS NOT NULL
      AND (CAST(:knowledge_base_id AS uuid) IS NULL OR kb.id = CAST(:knowledge_base_id AS uuid))
    ORDER BY score DESC NULLS LAST
    LIMIT :limit
    """
)


def cosine_similarity(a: list[float], b: list[float]) -> float | None:
    """Cosine similarity of two vectors; ``None`` when undefined (dim mismatch/zero norm)."""
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return None
    return dot / (norm_a * norm_b)


def validate_filters(filters: dict[str, str] | None) -> dict[str, str]:
    filters = dict(filters or {})
    unknown = set(filters) - _FILTER_KEYS
    if unknown:
        raise ValueError(f"Unsupported retrieval filters: {sorted(unknown)}")
    if "organization_id" not in filters:
        raise ValueError("organization_id is required for tenant-scoped retrieval")
    if "embedding_model" not in filters:
        raise ValueError("embedding_model is required to compare compatible vectors")
    return filters


class PostgresVectorStore:
    """Persists and retrieves chunk embeddings using the request's database session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, chunks: list[DocumentChunk]) -> None:
        for chunk in chunks:
            self._session.add(
                DocumentChunkRow(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    metadata_json=dict(chunk.metadata),
                    embedding=list(chunk.embedding),
                    embedding_model=chunk.metadata.get("embedding_model"),
                )
            )
        await self._session.flush()

    async def search(
        self, query_embedding: list[float], *, limit: int, filters: dict[str, str] | None = None
    ) -> list[RetrievalHit]:
        filters = validate_filters(filters)
        result = await self._session.execute(
            _SEARCH_SQL,
            {
                "query": list(query_embedding),
                "organization_id": filters["organization_id"],
                "embedding_model": filters["embedding_model"],
                "knowledge_base_id": filters.get("knowledge_base_id"),
                "limit": limit,
            },
        )
        hits: list[RetrievalHit] = []
        for row in result.mappings():
            metadata = {str(key): str(value) for key, value in (row["metadata"] or {}).items()}
            metadata["source"] = row["source"]
            if row["license"]:
                metadata["license"] = row["license"]
            hits.append(
                RetrievalHit(
                    chunk_id=row["id"],
                    document_id=row["document_id"],
                    content=row["content"],
                    score=float(row["score"]) if row["score"] is not None else 0.0,
                    metadata=metadata,
                )
            )
        return hits

    async def delete(self, document_id: UUID) -> None:
        await self._session.execute(
            delete(DocumentChunkRow).where(DocumentChunkRow.document_id == document_id)
        )


class InMemoryVectorStore:
    """Deterministic in-memory fixture implementing the VectorStore contract."""

    def __init__(self) -> None:
        self._by_document: dict[UUID, list[DocumentChunk]] = {}

    async def upsert(self, chunks: list[DocumentChunk]) -> None:
        for chunk in chunks:
            self._by_document.setdefault(chunk.document_id, []).append(chunk)

    async def search(
        self, query_embedding: list[float], *, limit: int, filters: dict[str, str] | None = None
    ) -> list[RetrievalHit]:
        filters = validate_filters(filters)
        scored: list[RetrievalHit] = []
        for chunks in self._by_document.values():
            for chunk in chunks:
                metadata = chunk.metadata
                if metadata.get("organization_id") != filters["organization_id"]:
                    continue
                if metadata.get("embedding_model") != filters["embedding_model"]:
                    continue
                if (
                    filters.get("knowledge_base_id")
                    and metadata.get("knowledge_base_id") != filters["knowledge_base_id"]
                ):
                    continue
                score = cosine_similarity(query_embedding, chunk.embedding)
                if score is None:
                    continue
                scored.append(
                    RetrievalHit(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        content=chunk.content,
                        score=score,
                        metadata=dict(metadata),
                    )
                )
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:limit]

    async def delete(self, document_id: UUID) -> None:
        self._by_document.pop(document_id, None)
