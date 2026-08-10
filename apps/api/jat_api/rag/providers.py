"""Embedding providers. Ollama is the default; deterministic is a CPU-free test fixture."""

import hashlib

import httpx

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


class OllamaEmbeddingProvider:
    """Ollama-backed embeddings via ``/api/embed`` (with ``/api/embeddings`` fallback)."""

    name = "ollama"
    # Dimensions depend on the embedding model (e.g. nomic-embed-text -> 768,
    # mxbai-embed-large -> 1024). We expose the actual dimension after first embed.
    dimensions = 768

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:11434",
        model: str = "nomic-embed-text",
        timeout: float = 60.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Prefer the newer /api/embed which accepts a batch.
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.endpoint}/api/embed",
                    json={"model": self.model, "input": texts},
                )
                response.raise_for_status()
                data = response.json()
                # New API: {"embeddings": [[...], [...]]}
                if isinstance(data, dict) and "embeddings" in data:
                    embeddings = data["embeddings"]
                    if isinstance(embeddings, list) and embeddings:
                        # Update dimensions to real model dimension for observability.
                        first = embeddings[0]
                        if isinstance(first, list):
                            self.dimensions = len(first)
                        return [[float(v) for v in vec] for vec in embeddings]
                # Fallback shape: single embedding
                if isinstance(data, dict) and "embedding" in data:
                    return [[float(v) for v in data["embedding"]] for _ in texts]
            except httpx.HTTPStatusError as exc:
                # Ollama returns 404 for unknown endpoint on older versions; fall back.
                if exc.response.status_code != 404:
                    raise
            # Fallback to legacy /api/embeddings per-text (Ollama < 0.1.14)
            vectors: list[list[float]] = []
            for text in texts:
                r = await client.post(
                    f"{self.endpoint}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                r.raise_for_status()
                payload = r.json()
                vec = payload.get("embedding")
                if not isinstance(vec, list):
                    raise ValueError("Ollama embeddings response missing 'embedding'")
                if not vectors:
                    self.dimensions = len(vec)
                vectors.append([float(v) for v in vec])
            return vectors


def create_embedding_provider(
    name: str,
    endpoint: str | None = None,
    model: str | None = None,
) -> EmbeddingProvider:
    """Single embedding-provider selection point; adapters stay replaceable."""
    if name == "ollama":
        return OllamaEmbeddingProvider(
            endpoint=endpoint or "http://127.0.0.1:11434",
            model=model or "nomic-embed-text",
        )
    if name == "deterministic":
        return DeterministicEmbeddingProvider()
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {name}")
