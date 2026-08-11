# JaT

**JaT** is an extensible, self-owned AI assistant platform. It separates the web experience, API gateway, orchestration, model providers, retrieval, memory, and tools so the underlying model can change without rewriting the application.

> **Current status:** active foundation development. JaT is not yet production-ready and does not claim a proprietary foundation model.

## What works today

### Phase 1 — platform foundation

- FastAPI API gateway with versioned `/api/v1` routes and OpenAPI
- React + TypeScript + Vite workspace
- PostgreSQL migrations and Redis-backed auth rate limiting
- Argon2id passwords, JWT access tokens, rotating hashed refresh sessions
- organization membership boundary, audit logging, CORS, CSRF-origin protection
- structured request logs, health/readiness endpoints, Prometheus metrics
- Dockerfiles, Compose backing services, GitHub Actions CI

### Phase 2 — chat engine

- provider-neutral `LLMProvider` contract
- deterministic development provider and slow streaming-test provider
- Ollama adapter implementation
- persistent organization-scoped conversations, messages, and message parts
- standard chat and SSE token-streaming endpoints
- browser streaming UI, stop-generation control, persistence of terminal states
- generation IDs, cancelled/failed/complete statuses, retry branches

### Phase 3 — governed RAG (text documents)

- governed multipart uploads: source/license metadata, content-type allowlist, 25 MiB limit, server-side SHA-256, per-base dedupe
- quarantined object storage contract with a local dev adapter; bytes never returned to clients
- ingestion pipeline (`validating → parsing → chunking → embedding → ready`, explicit `failed` states with reasons)
- deterministic paragraph-aware chunker and provider-neutral embeddings
- dispatch modes: synchronous `inline` (dev default) and durable Redis queue with `python -m jat_api.ingestion.worker`
- plain-text/Markdown parsing (PDF/JSON/CSV accepted for governance but parse failed-by-design until parsers land)
- portable PostgreSQL vector indexing (pure-SQL cosine; pgvector swap documented in [RAG](docs/RAG.md))
- organization-scoped semantic search with attributed citations
- chat grounding via `knowledge_base_id`: untrusted delimited reference injection, `citation` SSE events before tokens, citation message parts persisted
- ingestion audit trail and tenant-isolated retrieval paths

What Phase 3 still lacks: PDF/JSON/CSV and binary parsers, at-least-once queue semantics with re-dispatch, model-backed embedding providers, pgvector indexing, hybrid ranking, and the knowledge-base management UI.

### Settings and preferences

- persistent per-user preferences with partial (`PATCH`) updates and server-side validation
- appearance controls — light/dark/system theme, five accent colours, text size, density, reduced motion
- chat controls — default model, temperature, max tokens, custom system prompt, streaming, send-on-Enter
- memory management — enable/disable plus add, remove, and clear individual memories
- account security — profile editing, password rotation (min 8 characters), active-session list with immediate revocation
- data controls — usage statistics, JSON export, bulk conversation deletion, account deletion
- integrations — connect GitHub and other systems with hashed access tokens
- responsive settings UI (desktop, tablet, and full-screen mobile) with keyboard and screen-reader support

### Workspace UX

- JaT brand logo across auth, sidebar, empty state, assistant messages, and favicon
- every chat gets a title (auto from first message, rename anytime)
- search chats, delete chats, and open a per-chat options menu
- attach files from the composer (text contents inlined into the prompt when readable)
- working send control (↑) with clear ready/disabled states and stop-while-streaming
- rich model picker in the chat header — searchable, grouped by provider, showing
  context window, description, and availability, with a shortcut into Settings → Chat
- Settings → Chat lists the model catalog grouped by provider with context windows,
  descriptions, and availability for the default-model choice

### Guest (trial) access — try the LLM before signing up

Visitors can experiment with the LLM without creating an account, in the same
flow most AI platforms offer:

- **Try it free** CTA on the auth screen starts an anonymous trial session in
  one click — no email, no password.
- Guests get a message budget and a time window (`JAT_GUEST_MESSAGE_LIMIT`,
  `JAT_GUEST_TTL_HOURS`) with a live usage banner, a header chip, and a lock
  screen when the trial is spent.
- **Conversion keeps everything**: signing up mid-trial transfers the guest's
  conversations into the new account, then retires the guest identity and its
  sessions (`POST /auth/register` with `guest_token`).
- Guests are sandboxed in their own organization; account-management endpoints
  (`/settings/password`, sessions, profile, delete-account, …) reject guests.
- Toggle the whole feature with `JAT_GUEST_ENABLED`; cap open conversations
  with `JAT_GUEST_MAX_CONVERSATIONS`.
- A DB-free demo harness (`node mock-api.mjs`) serves the web app with an
  in-memory guest quota so the flow can be walked without Postgres/Redis/Ollama.

## Architecture

```text
React / TypeScript web app
        │
/api/v1 REST + SSE gateway
        │
Auth · tenancy · validation · audit · rate limits
        │
Chat orchestration · future context/RAG/memory/tools
        │
LLMProvider / EmbeddingProvider / VectorStore contracts
        │
Deterministic · Ollama · future vLLM / llama.cpp / Transformers / JaT model
        │
PostgreSQL · Redis · future object storage / pgvector / worker queue
```

## Repository layout

```text
apps/api/        FastAPI gateway, migrations, domain routes, provider/retrieval contracts,
                 ingestion pipeline and worker (`python -m jat_api.ingestion.worker`)
apps/web/        React workspace and streaming chat client
services/workers/ Ownership boundary for a future standalone ingestion worker service
infrastructure/  Future deployment/IaC ownership boundary
docs/            Architecture, security, API, model, RAG, deployment guides
```

## Local prerequisites

- Python 3.12 or 3.13
- Node.js 20+
- npm 10+
- Docker for PostgreSQL and Redis integration work

## Local setup

```bash
git clone https://github.com/Jallah-lj/JaT-Ai.git
cd jat
cp .env.example .env
make api-install
make web-install
```

Start PostgreSQL and Redis:

```bash
docker compose up -d postgres redis
```

> `JAT_DATABASE_URL` and `JAT_REDIS_URL` in `.env` must use `localhost` (the shipped
> `.env.example` already does). The `postgres`/`redis` names in `docker-compose.yml`
> only resolve inside the Compose network; `make api-migrate` and the dev server run
> on the host, where Compose publishes both services on `localhost`. The credentials
> must also match `POSTGRES_USER`/`POSTGRES_PASSWORD` in `docker-compose.yml`.

Apply migrations:

```bash
make api-migrate
```

Start the API:

```bash
cd apps/api
python -m uvicorn jat_api.main:app --host 0.0.0.0 --port 8000
```

Start the web application in another terminal:

```bash
cd apps/web
npm run dev
```

To process uploads asynchronously (instead of the default synchronous `inline`
dispatch), set `JAT_INGESTION_DISPATCHER=redis` and start the ingestion worker:

```bash
cd apps/api
python -m jat_api.ingestion.worker
```

## Quality checks

Run all available checks:

```bash
make verify
```

This runs backend linting, strict typing, tests, frontend linting, frontend type checking, frontend tests, and the production web build.

## Model configuration

> **Active Environment Status:** Ollama is configured and active (`http://127.0.0.1:11434`).

Default local development configuration can use either Ollama or the CPU deterministic provider:

```env
JAT_MODEL_PROVIDER=ollama
JAT_MODEL_ENDPOINT=http://127.0.0.1:11434
JAT_MODEL_NAME=llama3.1
JAT_MODEL_CONTEXT_LENGTH=8192
```

See [Model providers](docs/MODEL.md). Never expose model endpoints, provider credentials, database URLs, or JWT secrets to browser code.

### Sample dialogue

With `llama3.1` served by a local Ollama install and a JaT system prompt
applied, the first exchange looks like this:

```text
> Hello. You are JaT. Introduce yourself briefly.

*waves* I'm JaT, a galactic being from the Andromeda galaxy. My name is an
acronym for "Just Another Traveler". It's nice to meet you! *smiles* What
brings you here?
```

The exact personality depends on your system prompt — see
[Training your JaT agent](docs/TRAINING_GUIDE.md) and the smoke test in
[Model providers](docs/MODEL.md#pre-wiring-smoke-test).

## Important API endpoints

| Area | Endpoints |
|---|---|
| Health | `GET /api/v1/health`, `/live`, `/ready` |
| Authentication | register, login, refresh, logout, current user |
| Conversations | create, list, retrieve, archive, message history |
| Chat | `POST /api/v1/chat`, `POST /api/v1/chat/stream` (citations when `knowledge_base_id` is set) |
| Knowledge bases | CRUD, governed document registration, multipart upload, semantic search |
| Metrics | `GET /metrics` — restrict at the deployment edge |

OpenAPI is available at `/openapi.json` when the API is running.

## Security posture

JaT currently includes strong foundation controls, but requires further operational hardening before production use. In particular, production deployment requires TLS, managed secrets, backups, restore drills, monitoring, dependency review, threat modeling, and security testing.

Read [Security](docs/SECURITY.md) before deployment.

## Documentation

- [Training your JaT agent](docs/TRAINING_GUIDE.md)
- [Architecture assessment](ARCHITECTURE_ASSESSMENT.md)
- [API contract](docs/API.md)
- [Security baseline](docs/SECURITY.md)
- [Model providers](docs/MODEL.md)
- [RAG boundary](docs/RAG.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Contributing](docs/CONTRIBUTING.md)

## Contribution rules

- Never commit `.env`, API keys, private keys, credentials, datasets, or model artifacts.
- Use Alembic migrations for every database schema change.
- Keep providers replaceable and external integrations isolated.
- Add tests for security-sensitive behavior.
- Run `make verify` before submitting changes.
- Do not claim production readiness without deployment and security validation.

## License

Apache-2.0. See [LICENSE](LICENSE).
