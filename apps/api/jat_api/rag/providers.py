"""Deterministic CPU-free embedding fixture; not a semantic embedding model."""

import hashlib


class DeterministicEmbeddingProvider:
    name = "deterministic-embedding"
    dimensions = 16

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([byte / 255.0 for byte in digest[: self.dimensions]])
        return vectors
