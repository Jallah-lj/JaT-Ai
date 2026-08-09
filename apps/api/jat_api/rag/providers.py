"""Embedding providers. The deterministic provider is a CPU-free test/dev fixture."""

import hashlib

from jat_api.rag.contracts import EmbeddingProvider


class DeterministicEmbeddingProvider:
    """Hash-derived vectors; exercises the retrieval pipeline without a model."""

    name = "deterministic-embedding"
    dimensions = 16

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([byte / 255.0 for byte in digest[: self.dimensions]])
        return vectors


def create_embedding_provider(name: str) -> EmbeddingProvider:
    """Single embedding-provider selection point; adapters stay replaceable."""
    if name == "deterministic":
        return DeterministicEmbeddingProvider()
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {name}")
