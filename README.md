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

### Phase 3 — RAG foundation in progress

- provider-neutral embedding and vector-store contracts
- deterministic embedding fixture for tests
- governed `knowledge_bases`, `documents`, and `document_chunks` schema
- organization-scoped knowledge-base CRUD API
- governed document registration with source, license, and SHA-256 hash metadata
- ingestion worker contracts, validation policy, lifecycle states, and local dispatcher fixture

Document parsing, durable queue dispatch, vector indexing, semantic retrieval, citations, and file uploads are **not yet enabled**.

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
apps/api/        FastAPI gateway, migrations, domain routes, provider contracts
apps/web/        React workspace and streaming chat client
services/workers/ Governed ingestion worker contracts
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
git clone <your-repository-url> jat
cd jat
cp .env.example .env
make api-install
make web-install
```

Start PostgreSQL and Redis:

```bash
docker compose up -d postgres redis
```

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

## Quality checks

Run all available checks:

```bash
make verify
```

This runs backend linting, strict typing, tests, frontend linting, frontend type checking, frontend tests, and the production web build.

## Model configuration

Default local development configuration uses the deterministic provider:

```env
JAT_MODEL_PROVIDER=deterministic
JAT_MODEL_NAME=jat-development
```

For a locally running Ollama server:

```env
JAT_MODEL_PROVIDER=ollama
JAT_MODEL_ENDPOINT=http://127.0.0.1:11434
JAT_MODEL_NAME=<installed-model-name>
```

See [Model providers](docs/MODEL.md). Never expose model endpoints, provider credentials, database URLs, or JWT secrets to browser code.

## Important API endpoints

| Area | Endpoints |
|---|---|
| Health | `GET /api/v1/health`, `/live`, `/ready` |
| Authentication | register, login, refresh, logout, current user |
| Conversations | create, list, retrieve, archive, message history |
| Chat | `POST /api/v1/chat`, `POST /api/v1/chat/stream` |
| Knowledge bases | create, list, retrieve, delete, governed document registration |
| Metrics | `GET /metrics` — restrict at the deployment edge |

OpenAPI is available at `/openapi.json` when the API is running.

## Security posture

JaT currently includes strong foundation controls, but requires further operational hardening before production use. In particular, production deployment requires TLS, managed secrets, backups, restore drills, monitoring, dependency review, threat modeling, and security testing.

Read [Security](docs/SECURITY.md) before deployment.

## Documentation

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
