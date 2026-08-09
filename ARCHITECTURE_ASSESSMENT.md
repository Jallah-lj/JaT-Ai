# JaT — Initial Architecture Assessment & Phase 1 Blueprint

**Status:** Greenfield repository assessment  
**Date:** 2026-08-09  
**Scope:** Architecture only; no application code has been created in this step.

## 1. Repository assessment

The workspace is empty:

- No Git repository exists.
- No existing JaT source code, package manifests, Docker configuration, tests, or documentation exist.
- There is therefore no code to preserve, migrate, or audit.

**Conclusion:** JaT should begin as a deliberately small, documented monorepo rather than a large generated scaffold. The first working vertical slice will be Phase 1: identity, persistence, gateway, UI shell, configuration, observability, local containers, and CI. Chat/model inference deliberately starts in Phase 2.

## 2. Target architecture

JaT is model-provider-neutral. UI and public API never import or invoke a particular LLM SDK. The orchestration layer depends on provider interfaces; adapters implement those interfaces.

```text
React/Vite web application
        |
HTTPS + REST/SSE (/api/v1)
        |
FastAPI gateway: auth, request validation, rate limits, correlation IDs
        |
Application services: conversations | files | knowledge | models | jobs
        |
Future orchestration: context engine + memory + RAG + tool policy + model router
        |
Provider contracts: LLM | embeddings | vector store | vision | STT | TTS | image generation
        |
Adapters: mock/dev | Ollama | vLLM | llama.cpp | Transformers | HF | external APIs
        |
PostgreSQL (+ pgvector later) | Redis | S3-compatible object storage | worker queue
```

### Ownership boundaries

| Boundary | Responsibility | Must not own |
|---|---|---|
| `apps/web` | User interaction, optimistic UI, authenticated API calls | Secrets, authorization decisions, model credentials |
| `apps/api` | Versioned HTTP contract, auth, validation, SSE gateway | Model-specific prompting or direct UI state |
| `packages/core` | Domain types, errors, service contracts, orchestration contracts | Database/vendor implementations |
| `packages/database` | SQLAlchemy models, repositories, Alembic migrations | Business policy or HTTP concerns |
| `packages/security` | Password hashing, JWT/refresh lifecycle, RBAC, API-key primitives | Client-side authorization |
| `services/*` | Replaceable integrations and background work | Public HTTP ownership unless explicitly exposed via gateway |
| `training/*` | Offline governed data and model workflows | Request-path serving |

### Language/runtime decision

Use **Python 3.12 + FastAPI** for the backend, AI orchestration, worker interfaces, migrations, and future training compatibility. Use **React 18 + TypeScript + Vite + Tailwind** for the web application. This avoids an unnecessary second backend language while retaining a typed frontend. Cross-boundary types are generated from the OpenAPI document, not manually duplicated.

## 3. Missing components

All components are currently missing. They are grouped by implementation phase to prevent an unsafe, non-runnable scaffold.

### Phase 1 (build now, incrementally)

- Monorepo and local developer tooling
- FastAPI application with `/api/v1`, OpenAPI, health/readiness endpoints
- PostgreSQL schema/migrations and repository layer
- User registration/login/refresh/logout/current-user flow
- Password hashing, JWT access/refresh rotation, RBAC baseline, audit records
- React application shell, login/register pages, protected workspace, conversation sidebar placeholder
- Structured JSON logging, request/trace IDs, Prometheus-compatible metrics endpoint
- Docker Compose for API, web proxy/dev service, PostgreSQL, Redis, MinIO (optional profile)
- CI checks and a focused test suite

### Later phases (intentionally not implemented in Phase 1)

- Chat orchestration, SSE tokens, model providers, messages (Phase 2)
- Upload parsing, embeddings, pgvector, RAG and citations (Phase 3)
- Long-term memory and consent (Phase 4)
- Tools and isolated runner (Phase 5)
- Multimodal providers (Phase 6)
- Dataset governance UI/services (Phase 7)
- Fine-tuning/job execution/registry (Phase 8)
- Custom foundation-model research/training package (Phase 9)

## 4. Exact Phase 1 implementation plan

### Milestone 1.1 — repository foundation

1. Initialize Git, `.gitignore`, Apache-2.0 license, editor settings, and conventional commit guidance.
2. Create the project tree below with **only necessary files**.
3. Add root `README.md`, `.env.example`, `Makefile`, and pinned dependency manifests.
4. Add typed settings loaded from environment; startup fails clearly for invalid production configuration.
5. Add Docker Compose with non-secret development defaults only; actual `.env` remains ignored.
6. Verify: formatting, lint, type checking, unit smoke tests, compose configuration validation.

### Milestone 1.2 — secure API foundation

1. Build FastAPI application factory and `/api/v1/health/live`, `/ready`, `/health` endpoints.
2. Add request ID middleware, JSON structured logs, error envelope, trusted-host/security headers, CORS allowlist, body-size limit, and rate-limit abstraction.
3. Add SQLAlchemy async engine, Alembic baseline migration, transaction lifecycle, and repository patterns.
4. Define OpenAPI tags and versioned router composition.
5. Verify: API contract tests, invalid configuration tests, security-header tests, migration upgrade on an ephemeral PostgreSQL instance.

### Milestone 1.3 — identity and authorization

1. Implement users, organizations, memberships, sessions, API key metadata, and audit-log persistence.
2. Implement Argon2id password hashing; short-lived signed access token; hashed, rotating, revocable refresh tokens stored server-side.
3. Implement RBAC roles `owner`, `admin`, `member`, `viewer`; enforce organization ownership server-side.
4. Implement registration, login, refresh, logout, and `GET /me`; email verification is represented as an account state but email delivery is deferred.
5. Use secure HttpOnly/SameSite cookies for refresh tokens in browser mode; use bearer access tokens for API clients. Apply CSRF double-submit/origin protection to cookie-authenticated state-changing routes.
6. Verify: registration/login/refresh/logout happy path plus expired, reused, stolen, malformed, unauthorized, and cross-organization negative cases.

### Milestone 1.4 — web foundation

1. Create Vite React TypeScript application with Tailwind and accessible design tokens.
2. Build responsive JaT app shell: sidebar, “New chat” affordance, workspace header, profile/settings menu, auth screens, empty chat state.
3. Add typed API client generated/validated from OpenAPI, protected routing, session refresh handling, and accessible error/loading states.
4. Do not fake an LLM in Phase 1. The chat composer is visibly marked “Chat engine arrives in Phase 2” or disabled with explanatory UX.
5. Verify: frontend lint, TypeScript build, component tests, browser-level auth smoke test.

### Milestone 1.5 — operations and delivery gate

1. Expose `/api/v1/metrics` with request latency/error counters and no sensitive labels.
2. Add GitHub Actions: format/lint, type check, unit/API tests, frontend build, dependency audit, secret scan, Docker build.
3. Document local setup, threat model boundaries, migration workflow, and production gaps.
4. Verify the full critical Phase 1 flow: register → login → protected workspace → refresh → logout. Persist only identity/session/audit data; conversation/chat is Phase 2.

**Definition of done:** every milestone has a runnable command, tests, and documentation. No claim of production readiness is made until deployment-specific secrets, TLS, backing-service operations, load testing, and external security review are complete.

## 5. Dependencies

### Backend (pinned after compatibility verification)

| Need | Recommended dependency |
|---|---|
| HTTP/OpenAPI | `fastapi`, `uvicorn[standard]`, `pydantic-settings` |
| Database/migrations | `sqlalchemy`, `asyncpg`, `alembic` |
| Authentication | `argon2-cffi`, `PyJWT` or `python-jose[cryptography]` |
| HTTP resilience | `httpx` |
| Logging/metrics | `structlog`, `prometheus-client` |
| Rate-limit adapter | `redis`, `limits` (or an in-house narrow adapter over Redis) |
| Tests | `pytest`, `pytest-asyncio`, `httpx`, `testcontainers[postgresql]` (CI/integration) |
| Quality | `ruff`, `mypy` or `pyright`, `pre-commit` |

### Frontend

| Need | Recommended dependency |
|---|---|
| UI | `react`, `react-dom`, `typescript`, `vite` |
| Styling | `tailwindcss` |
| Routing/data | `react-router-dom`, `@tanstack/react-query` |
| Forms/schema | `react-hook-form`, `zod` |
| Tests | `vitest`, `@testing-library/react`, `playwright` |
| API types | `openapi-typescript` (generated from backend OpenAPI) |

### Infrastructure

- PostgreSQL 16 (production source of truth); enable `pgvector` in Phase 3.
- Redis 7 for rate limits, future queue/cache—not authorization source of truth.
- Docker/Compose for local parity.
- MinIO locally / S3-compatible object store later for files and model artifacts.
- GitHub Actions, Trivy (container/dependency scanning), Gitleaks (secret scan).

No LLM package or external model API is required in Phase 1. A deterministic mock provider will be introduced with the Phase 2 provider contract so development does not require a GPU or cloud credentials.

## 6. Initial database schema

PostgreSQL migrations are the only schema-change mechanism. Primary keys use UUIDv7 (or UUID generated in application until native generation is standardized); timestamps are UTC `timestamptz`; user-facing deletes are soft deletes where audit retention requires it.

### Phase 1 tables

| Table | Key columns / constraints | Purpose |
|---|---|---|
| `users` | `id`, unique normalized `email`, `password_hash`, `display_name`, `status`, `email_verified_at`, timestamps | Human accounts |
| `organizations` | `id`, `name`, unique `slug`, timestamps | Tenant boundary |
| `organization_memberships` | `organization_id`, `user_id`, `role`, unique pair | RBAC membership |
| `sessions` | `id`, `user_id`, `refresh_token_hash`, `family_id`, `expires_at`, `revoked_at`, `last_used_at`, IP/user-agent hashes | Rotating refresh lifecycle and reuse detection |
| `api_keys` | `id`, `organization_id`, optional `user_id`, `prefix`, `secret_hash`, `scopes`, `expires_at`, `revoked_at` | API credential metadata; raw secret never stored |
| `audit_logs` | `id`, nullable actor/organization IDs, `action`, `resource_type`, `resource_id`, `request_id`, IP hash, safe metadata JSONB, timestamp | Immutable security/audit events |
| `schema_migrations` | Alembic-managed | Migration history |

Indexes: unique case-insensitive email; memberships by user and organization; active sessions by user/family; API key prefix; audit logs by organization/timestamp and request ID. Encrypt backups and enforce database transport encryption in deployed environments.

### Reserved Phase 2+ schema (not migrated until its phase)

`conversations`, `messages`, `message_parts`, `files`, `documents`, `document_chunks`, `knowledge_bases`, `memories`, `tools`, `tool_calls`, `models`, `model_versions`, `datasets`, `dataset_versions`, `training_jobs`, `training_metrics`, and `evaluations` will be introduced by individually reviewed migrations. All tenant-owned records include `organization_id`; repositories apply tenant scoping by default.

## 7. Initial API contract

All APIs are under `/api/v1`; JSON requests/responses use UTF-8; errors use RFC 9457-style problem objects enriched with `request_id`. OpenAPI is the contract source. Pagination will be cursor-based for collections.

### Phase 1 implemented endpoints

| Method/path | Auth | Contract summary |
|---|---|---|
| `GET /health/live` | Public | Process is alive |
| `GET /health/ready` | Public/internal policy | Database/Redis readiness without leaking details |
| `GET /health` | Public | Version and safe service status |
| `GET /metrics` | Internal/network restricted in production | Prometheus metrics |
| `POST /auth/register` | Public, rate limited | Create user + personal organization; return safe user/session response |
| `POST /auth/login` | Public, rate limited | Verify credentials; issue access token and browser refresh cookie/session |
| `POST /auth/refresh` | Refresh credential | Rotate refresh session; reject reuse |
| `POST /auth/logout` | Auth/refresh credential | Revoke current session and clear cookie |
| `GET /auth/me` | Access token | Current user, memberships, permissions |

Example response envelope:

```json
{
  "data": { "id": "uuid", "email": "user@example.test" },
  "meta": { "request_id": "uuid" }
}
```

Error shape:

```json
{
  "type": "https://jat.ai/problems/validation-error",
  "title": "Request validation failed",
  "status": 422,
  "detail": "One or more fields are invalid.",
  "request_id": "uuid"
}
```

### Contract reserved for later

The requested chat, conversation, file, knowledge base, search, model, dataset, and training routes will be documented as **planned**, not shipped. `POST /chat/stream` will use SSE in Phase 2 with event types such as `message.start`, `token`, `tool.status`, `citation`, `message.complete`, and `error`. It will never expose model-provider internals.

## 8. Project tree (initial target)

```text
jat/
├── apps/
│   ├── api/
│   │   ├── jat_api/
│   │   │   ├── api/v1/
│   │   │   ├── auth/
│   │   │   ├── config/
│   │   │   ├── db/
│   │   │   ├── middleware/
│   │   │   └── main.py
│   │   ├── alembic/
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── web/
│       ├── src/{app,components,features,lib,styles}/
│       ├── tests/
│       ├── package.json
│       └── vite.config.ts
├── packages/
│   ├── core/                 # domain contracts; added as needs become real
│   ├── database/             # shared persistence contracts/migrations support
│   ├── security/             # shared security primitives
│   ├── models/               # Phase 2 provider contracts
│   ├── memory/               # Phase 4
│   ├── tools/                # Phase 5
│   └── evaluation/           # Phase 8
├── services/
│   ├── inference/            # Phase 2
│   ├── rag/                  # Phase 3
│   ├── embeddings/           # Phase 3
│   ├── workers/              # introduced with async jobs
│   ├── speech/               # Phase 6
│   └── training/             # Phase 8
├── training/                 # Phase 9 research/training package
│   ├── datasets/ preprocessing/ tokenizer/ models/ trainers/ evaluation/ configs/
├── infrastructure/
│   ├── docker/
│   ├── deployment/
│   └── terraform/
├── docs/
├── scripts/
├── tests/                    # cross-service/e2e tests
├── .github/workflows/
├── docker-compose.yml
├── .env.example
├── Makefile
├── README.md
├── ARCHITECTURE.md
├── SECURITY.md
└── LICENSE
```

Empty phase directories will not be committed merely to imply functionality. They appear above to establish the final ownership model.

## 9. Security risks and controls

| Risk | Phase 1 control | Future requirement |
|---|---|---|
| Credential theft/password attacks | Argon2id, login rate limiting, generic login failures, TLS deployment | MFA, breach-password checks, anomaly detection |
| Refresh-token replay | Server-side hashed rotating tokens, family revocation, reuse detection, HttpOnly secure cookies | Device/session management UI |
| Tenant data leaks (IDOR) | Organization scope derived from authenticated membership, not a client-supplied ID | Repository-level policy tests on every new resource |
| Secrets in source/logs | `.env` ignored, placeholders only, log redaction, Gitleaks CI | Secret manager and key rotation |
| CORS/CSRF | Explicit origins, no wildcard credential CORS, SameSite cookie + CSRF/origin protection | Deployment-specific CSP review |
| Injection | Pydantic validation, ORM parameters, no dynamic SQL | Prompt/data trust boundaries, tool argument schemas |
| Resource exhaustion | Request/body limits, rate limiting, timeouts | Queue quotas, per-tool/model quotas |
| Malicious uploads/code | No executable upload or code execution in Phase 1 | MIME/content checks, object quarantine, Docker sandbox with no network and strict cgroups |
| Observability leaking PII | Structured allowlisted fields, IP/user-agent hashing, redaction | Retention policy and access-controlled trace viewer |
| Supply chain | Locked dependencies, CI scanning, minimal images | SBOM, signed artifacts, provenance |

## 10. Architectural risks and decisions

1. **Premature microservices:** begin as a modular monolith API with explicit interfaces; split deployment units only when scaling, isolation, or ownership warrants it.
2. **Provider lock-in:** the model router calls only `LLMProvider` contracts. External APIs stay optional adapters, never application architecture.
3. **Context bloat/cost:** introduce token budgeting and summarized history before persistent chat reaches production in Phase 2/4.
4. **RAG poisoning/prompt injection:** retrieved text and tools are typed, attributed untrusted data blocks—not privileged prompts. Tool actions require policy validation independent of model output.
5. **Unsafe execution:** no host code execution. The future runner uses a separately maintained Docker sandbox, non-root user, network deny-by-default, cgroups, seccomp/AppArmor where available, time/output/process limits, and disposal.
6. **Training/data legality:** a dataset registry must reject unknown license/source/governance metadata before training. GPU/cloud work is future infrastructure, not a CPU-local promise.
7. **Schema drift:** Alembic migrations, reviewable rollback/forward plans, and migration tests; never alter deployed schema manually.
8. **False production claims:** Phase 1 is a tested foundation. HA, backups/restore drills, threat modeling, penetration tests, SLOs, key management, and load testing are explicit release gates.

## 11. Quality gates after each milestone

- Backend: `ruff format --check`, `ruff check`, static typing, `pytest`.
- Frontend: lint, TypeScript `tsc --noEmit`, unit tests, production build.
- Integration: migration upgrade, API/auth security cases, compose smoke test.
- Delivery: OpenAPI diff review, dependency/secret scan, container build.

Only after these gates pass do we advance from Phase 1 to Phase 2.
