"""Semantic retrieval service backing knowledge-base search and chat citations."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from jat_api.rag.contracts import EmbeddingProvider, VectorStore

_PREVIEW_CHARS = 320


@dataclass(frozen=True)
class Citation:
    chunk_id: UUID
    document_id: UUID
    knowledge_base_id: str
    source: str
    license: str | None
    score: float
    content_preview: str

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "knowledge_base_id": self.knowledge_base_id,
            "source": self.source,
            "license": self.license,
            "score": round(self.score, 6),
            "content_preview": self.content_preview,
        }


async def retrieve(
    *,
    embedder: EmbeddingProvider,
    store: VectorStore,
    organization_id: UUID,
    query: str,
    limit: int,
    knowledge_base_id: UUID | None = None,
) -> list[Citation]:
    """Embed a query and return tenant-scoped, attribution-carrying citations."""
    vectors = await embedder.embed([query])
    filters = {
        "organization_id": str(organization_id),
        "embedding_model": embedder.name,
    }
    if knowledge_base_id is not None:
        filters["knowledge_base_id"] = str(knowledge_base_id)
    hits = await store.search(vectors[0], limit=limit, filters=filters)
    return [
        Citation(
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            knowledge_base_id=hit.metadata.get("knowledge_base_id", ""),
            source=hit.metadata.get("source", "unknown"),
            license=hit.metadata.get("license"),
            score=hit.score,
            content_preview=hit.content[:_PREVIEW_CHARS],
        )
        for hit in hits
    ]
