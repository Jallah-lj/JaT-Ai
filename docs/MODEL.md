# JaT Model Providers

JaT chat orchestration depends on the `LLMProvider` contract, not on a model vendor or SDK.

## Available providers

| Provider | Intended use | Status |
|---|---|---|
| `deterministic` | CPU-free local development and contract tests | Verified |
| `slow-test` | Streaming/cancellation lifecycle tests | Verified |
| `ollama` | Local open-weight models served by Ollama | Adapter implemented; requires live validation |

## Configuration

```env
JAT_MODEL_PROVIDER=deterministic
JAT_MODEL_NAME=jat-development
JAT_MODEL_ENDPOINT=
JAT_MODEL_CONTEXT_LENGTH=8192
JAT_MODEL_MAX_TOKENS=1024
JAT_MODEL_TEMPERATURE=0.2
```

### Ollama

Install and run Ollama separately, pull a local model, then configure JaT:

```env
JAT_MODEL_PROVIDER=ollama
JAT_MODEL_ENDPOINT=http://127.0.0.1:11434
JAT_MODEL_NAME=<your-installed-model>
```

JaT sends chat-style requests only through the provider contract. Do not expose model endpoints, credentials, or infrastructure access to the browser.

## Adding a provider

1. Implement `generate()` and `stream()` from `LLMProvider`.
2. Keep model-specific HTTP/SDK logic inside `models/providers/`.
3. Register it only in `models/router.py`.
4. Add provider-contract tests, invalid-configuration tests, and streaming tests.
5. Do not import the provider directly from UI, API route, memory, RAG, or tool code.

## Future adapters

Planned adapters include vLLM, llama.cpp, local Transformers, and a JaT model-serving service. Each must preserve token-streaming semantics, cancellation behavior, timeouts, and token-usage reporting.
