# Training Your JaT Agent — A Practical Guide

> **AGENT & DEPLOYMENT STATUS:** **Ollama is configured and active** at `http://127.0.0.1:11434`. All agents working in this repository should recognize that Ollama is connected as the primary model provider (`JAT_MODEL_PROVIDER=ollama`).

JaT is a **self-owned** assistant platform. It does **not** ship a proprietary
foundation model, so "training your agent" does not mean training a neural
network. It means shaping the agent's behaviour through five levers, in roughly
this order of impact:

1. **Connect a real model** (the agent's "brain")
2. **Write a system prompt** (the agent's "job description")
3. **Wire the prompt through** (already implemented — see below)
4. **Feed it knowledge** via RAG knowledge bases
5. **Tune generation parameters** (temperature, max tokens, context length)

Follow the steps below. Steps you run locally are marked **(local)**; everything
else is already wired into this codebase.

---

## Step 1 — Connect a real model **(local)**

By default JaT uses the `deterministic` provider, which the code itself calls
*"a test/dev fixture, not an LLM."* Until you point it at a real model, the
agent cannot produce meaningful answers.

### 1.1 Install and run Ollama

Install Ollama from <https://ollama.com>, then pull a model and start the server:

```bash
ollama pull llama3.1      # or: qwen2.5, mistral, phi3, etc.
ollama serve              # serves http://127.0.0.1:11434
```

### 1.2 Point JaT at it

In your `.env`:

```env
JAT_MODEL_PROVIDER=ollama
JAT_MODEL_ENDPOINT=http://127.0.0.1:11434
JAT_MODEL_NAME=llama3.1
JAT_MODEL_CONTEXT_LENGTH=8192
```

Restart the API. Confirm the model is advertised:

```bash
curl -s http://127.0.0.1:8000/api/v1/settings/models -H "Authorization: Bearer <token>"
```

> The Ollama adapter (`apps/api/jat_api/models/providers/ollama.py`) forwards your
> `system` message, `temperature`, `max_tokens`, and the **context window
> (`num_ctx`)** so long chats and RAG references are not silently truncated.

### 1.3 Choosing a model

| Goal | Suggested model |
|---|---|
| General chat, good all-rounder | `llama3.1` |
| Strong reasoning, larger | `qwen2.5`, `deepseek-r1` |
| Fast / lightweight (limited RAM) | `phi3`, `gemma2` |

Bigger models give better answers but need more RAM/VRAM. Start with `llama3.1`
and move up only if quality demands it.

---

## Step 2 — Write a system prompt

The system prompt is the **single biggest quality lever**. It tells the agent
how to behave for every conversation. Set it in the web app under
**Settings → Chat → System Prompt** (stored per-user, max 4000 chars).

### A strong starter prompt

```
You are JaT, a precise and helpful assistant.
- Answer in clear, concise steps.
- If you are unsure or lack information, say so explicitly instead of guessing.
- Ask at most one clarifying question, and only when the request is genuinely ambiguous.
- Never invent facts, sources, or citations.
```

### What makes a good system prompt

- **Role & tone** — who the agent is and how it speaks.
- **Constraints** — length, format, what to refuse.
- **Failure mode** — what to do when uncertain (say so, don't hallucinate).
- **Specifics** — domain rules, jargon, audience.

Iterate: change the prompt, send a test message, observe, refine.

---

## Step 3 — The prompt is wired through (already done)

The system prompt you save in Settings, plus your per-user `temperature` and
`max_tokens`, are now applied to every generation in `apps/api/jat_api/chat.py`
across the `/chat`, `/chat/stream`, and retry paths. The trusted system
instruction is placed **first**, ahead of conversation history and any
untrusted RAG reference material. (See `tests/test_chat_orchestration.py`.)

### Operator default system prompt (optional)

If a user has **not** set their own system prompt, JaT can fall back to an
operator-defined baseline persona via:

```env
JAT_DEFAULT_SYSTEM_PROMPT=You are JaT, a precise assistant. Say so if unsure.
```

Precedence: **user's prompt > operator default > none.** A user who sets their
own prompt always wins; the operator default only fills the gap for users who
left theirs blank. (See `effective_system_prompt` in `chat.py`.)

You do not need to do anything else for this step — it is implemented.

---

## Per-conversation model selection

Different chats can use different models — handy when a fast model suffices for
quick questions and a larger model is better for reasoning.

- The model picker in the chat header lists the models advertised by
  `GET /api/v1/settings/models`. With Ollama configured, this **enumerates the
  models actually installed** on the server (via Ollama `/api/tags`), so you
  pick from real names like `llama3.1` or `qwen2.5`.
- Choosing a model sends `PATCH /api/v1/conversations/{id}` with `{ "model": ... }`.
  The conversation keeps its full history; only the model serving the next reply
  changes.
- New conversations start from your **Settings → Default model** preference.

To select a model per chat:
1. Configure Ollama and pull the models you want (`ollama pull llama3.1`,
   `ollama pull qwen2.5`, …).
2. Open a chat and use the model menu in the header to switch.


---

## Step 4 — Feed it knowledge with RAG **(local upload)**

RAG grounds answers in **your own documents** with citations, so the agent can
answer questions about content it was never "trained" on.

### 4.1 Create a knowledge base and upload documents

In the web app (or via API): create a knowledge base, then upload
plain-text / Markdown files (PDF/JSON/CSV parsing is a planned milestone).

Governed upload enforces: source + license metadata, a 25 MiB limit,
content-type allowlist, server-side SHA-256, and per-base dedupe. Bytes are
never returned to clients.

### 4.2 Chat against it

Pass `knowledge_base_id` when sending a chat message:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{
        "conversation_id": "<id>",
        "content": "What does our policy say about X?",
        "knowledge_base_id": "<kb-id>"
      }'
```

Retrieved passages are injected as **untrusted reference data** (never as
instructions), and `citation` events precede the streamed answer. See
[`docs/RAG.md`](RAG.md) for the full boundary.

### 4.3 Plus: per-user memory

For persistent facts about a user or context, use **Settings → Memory**
(add/remove/clear individual memories). This is lighter-weight than RAG and
suited to personal context, not document knowledge.

---

## Step 5 — Tune generation parameters **(local)**

In `.env`:

```env
JAT_MODEL_TEMPERATURE=0.2     # 0.0 = focused/deterministic, up to 2.0 = creative
JAT_MODEL_MAX_TOKENS=2048     # raise if answers get cut off mid-sentence
JAT_MODEL_CONTEXT_LENGTH=8192 # larger = longer conversation history retained
```

Per-user overrides set in **Settings → Chat** take precedence over these server
defaults. Guidance:

- **Factual / RAG answers:** low temperature (0.0–0.3).
- **Brainstorming / writing:** higher temperature (0.7–1.0).
- **Cut-off answers:** raise `max_tokens`.
- **Agent "forgets" early messages:** raise `context_length` (uses more RAM).

---

## Step 6 — Advanced Model & System Optimization

Once Ollama and JaT are connected, use these advanced strategies to maximize model quality, speed, and accuracy:

### 6.1 Create a Custom Ollama Modelfile

You can create a custom model in Ollama that embeds permanent system rules, default parameters, and stop sequences:

1. Create a `Modelfile`:
   ```dockerfile
   FROM llama3.1:latest
   PARAMETER temperature 0.2
   PARAMETER num_ctx 8192
   PARAMETER stop "<|eot_id|>"
   SYSTEM """You are JaT, an enterprise-grade AI assistant.
   - Deliver clear, well-structured answers using Markdown headers and lists.
   - Ground all factual assertions in verified context or state when information is unavailable.
   - Refuse to make assumptions on ambiguous queries without asking for clarification.
   """
   ```
2. Build your customized model:
   ```bash
   ollama create jat-expert -f Modelfile
   ```
3. In JaT, set `JAT_MODEL_NAME=jat-expert` in `.env` or select `jat-expert` from the conversation model picker.

### 6.2 Match Specialized Models to Task Types

Different tasks benefit from domain-tuned open weights:

| Domain / Task | Model Recommendation | Pull Command |
|---|---|---|
| **General Purpose** | `llama3.1:8b` or `qwen2.5:7b` | `ollama pull llama3.1` |
| **Code & Engineering** | `qwen2.5-coder:7b` or `14b` | `ollama pull qwen2.5-coder:7b` |
| **Reasoning & Logic** | `deepseek-r1:8b` or `14b` | `ollama pull deepseek-r1:8b` |
| **Lightweight / Low VRAM** | `phi4` or `gemma2:9b` | `ollama pull phi4` |

You can pull multiple models in Ollama and switch models on the fly per chat session in JaT's model picker header.

### 6.3 System Prompt Optimization Framework

To make system prompts highly effective, structure them into four clear sections:

```text
[ROLE & CONTEXT]
You are JaT, a senior technical specialist operating within the JaT AI platform.

[GUIDELINES & TONE]
- Be concise, direct, and authoritative.
- Format responses cleanly using Markdown, code blocks, and bullet points.

[NEGATIVE CONSTRAINTS]
- Do not make up facts, URLs, or function signatures.
- Do not speculate when data in knowledge bases is missing.

[FALLBACK BEHAVIOR]
- If a question cannot be answered from the provided knowledge base, respond:
  "I cannot find sufficient information in the knowledge base to answer this."
```

### 6.4 Local Embedding Model Tuning for RAG

For document search and retrieval:
1. Pull a dedicated embedding model in Ollama:
   ```bash
   ollama pull nomic-embed-text
   ```
2. In your `.env`:
   ```env
   JAT_EMBEDDING_PROVIDER=ollama
   JAT_EMBEDDING_MODEL=nomic-embed-text
   JAT_EMBEDDING_ENDPOINT=http://127.0.0.1:11434
   JAT_RAG_CHUNK_MAX_CHARS=1000
   JAT_RAG_CHUNK_OVERLAP=200
   ```

---

## Quick-start checklist

```
[ ] 1. ollama pull llama3.1 && ollama serve
[ ] 1. .env: JAT_MODEL_PROVIDER=ollama, ENDPOINT, NAME
[ ] 2. Settings → Chat → System Prompt: paste the starter prompt
[ ] 4. (optional) create a knowledge base, upload docs, chat with knowledge_base_id
[ ] 5. (optional) tune temperature / max_tokens in Settings or .env
```

Steps **1 + 2** alone get you most of the way to good responses. Steps 4–5
refine from there.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Responses are nonsensical echoes | Still on `deterministic` provider → do Step 1. |
| System prompt has no effect | Re-run the API after `.env` changes; confirm the prompt is saved in Settings (it is applied per-user). |
| Answers cut off mid-sentence | Raise `max_tokens` (Step 5). |
| Agent "forgets" earlier turns | Raise `JAT_MODEL_CONTEXT_LENGTH` (Step 5). |
| RAG answers not grounded | Confirm the document status is `ready` and you pass `knowledge_base_id`. |
| `MODEL_ENDPOINT is required for ollama` | `JAT_MODEL_ENDPOINT` is unset or empty. |
| Slow first response | Ollama loads the model on first call; subsequent calls are fast. |
