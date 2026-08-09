"""Provider-neutral retrieval contracts for Phase 3 RAG."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class DocumentChunk:
    id: UUID
    document_id: UUID
    content: str
    embedding: list[float]
    chunk_index: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: UUID
    document_id: UUID
    content: str
    score: float
    metadata: dict[str, str]


class EmbeddingProvider(Protocol):
    name: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    async def upsert(self, chunks: list[DocumentChunk]) -> None: ...

    async def search(
        self, query_embedding: list[float], *, limit: int, filters: dict[str, str] | None = None
    ) -> list[RetrievalHit]: ...

    async def delete(self, document_id: UUID) -> None: ...
