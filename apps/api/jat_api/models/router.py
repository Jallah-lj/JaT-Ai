"""Single model-selection point. Application services never instantiate vendors directly."""

from jat_api.models.contracts import LLMProvider
from jat_api.models.providers.deterministic import DeterministicProvider
from jat_api.models.providers.ollama import OllamaProvider
from jat_api.models.providers.slow import SlowTestProvider


def create_provider(provider_name: str, endpoint: str | None = None) -> LLMProvider:
    if provider_name == "deterministic":
        return DeterministicProvider()
    if provider_name == "slow-test":
        return SlowTestProvider()
    if provider_name == "ollama":
        if not endpoint:
            raise ValueError("MODEL_ENDPOINT is required for ollama")
        return OllamaProvider(endpoint)
    raise ValueError(f"Unsupported MODEL_PROVIDER: {provider_name}")
