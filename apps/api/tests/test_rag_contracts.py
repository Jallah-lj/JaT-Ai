import pytest

from jat_api.rag import DeterministicEmbeddingProvider


@pytest.mark.asyncio
async def test_deterministic_embedding_is_stable_and_dimensioned() -> None:
    provider = DeterministicEmbeddingProvider()
    first, second = await provider.embed(["JaT retrieval", "JaT retrieval"])
    assert first == second
    assert len(first) == provider.dimensions
