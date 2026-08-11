# JaT Model Providers

> **ACTIVE CONFIGURATION NOTE:** **Ollama is configured and active** at `http://127.0.0.1:11434`. Agents working in this environment should consider Ollama the default running model provider.

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

#### Pre-wiring smoke test

Before pointing JaT at Ollama, confirm the server and model respond in
character by talking to the model directly:

```bash
ollama run llama3.1
```

```text
>>> Hello. You are JaT. Introduce yourself briefly.
```

A live run (Kali Linux, Ollama + `llama3.1`) produced:

```text
*waves* I'm JaT, a galactic being from the Andromeda galaxy. My name is an
acronym for "Just Another Traveler". It's nice to meet you! *smiles* What
brings you here?
```

If the model answers in character here, the model side of the stack works and
any remaining problem is in JaT's configuration (endpoint URL, model name, or
provider selection). The tone you see is a product of the prompt you give —
the starter persona in [Training your JaT agent](TRAINING_GUIDE.md) yields a
more restrained style.

When an endpoint is configured, `GET /api/v1/settings/models` enumerates the
models actually installed on the Ollama server (via `/api/tags`) so each
conversation can select a real model. Discovery is best-effort: if Ollama is
unreachable the catalog still advertises a single selectable Ollama entry.

### Per-conversation model selection

Each conversation pins a `model` (set at creation, changeable via
`PATCH /api/v1/conversations/{id}` with `{ "model": ... }`). Chat orchestration
sends `conversation.model` to the provider, so switching a conversation's model
changes which Ollama model serves its next reply without altering history.

### Operator default system prompt

```env
JAT_DEFAULT_SYSTEM_PROMPT=You are JaT, a precise assistant.
```

Applied only when a user has no system prompt of their own. A user's explicit
prompt always takes precedence.

JaT sends chat-style requests only through the provider contract. Do not expose model endpoints, credentials, or infrastructure access to the browser.

## Adding a provider

1. Implement `generate()` and `stream()` from `LLMProvider`.
2. Keep model-specific HTTP/SDK logic inside `models/providers/`.
3. Register it only in `models/router.py`.
4. Add provider-contract tests, invalid-configuration tests, and streaming tests.
5. Do not import the provider directly from UI, API route, memory, RAG, or tool code.

## Future adapters

Planned adapters include vLLM, llama.cpp, local Transformers, and a JaT model-serving service. Each must preserve token-streaming semantics, cancellation behavior, timeouts, and token-usage reporting.
