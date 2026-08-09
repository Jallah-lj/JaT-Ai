# JaT API

The API contract is versioned under `/api/v1`; the machine-readable OpenAPI document is `/openapi.json`.

## Phase 1 endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health/live` | Process liveness |
| `GET /api/v1/health/ready` | PostgreSQL and Redis readiness |
| `POST /api/v1/auth/register` | Create user and personal organization |
| `POST /api/v1/auth/login` | Authenticate and start a refresh session |
| `POST /api/v1/auth/refresh` | Rotate refresh cookie and mint access token |
| `POST /api/v1/auth/logout` | Revoke refresh-token family |
| `GET /api/v1/auth/me` | Fetch bearer-token authenticated user |
| `GET /metrics` | Prometheus metrics; restrict at deployment edge |

Access tokens are bearer JWTs. Refresh credentials are `HttpOnly` cookies and must never be exposed to frontend JavaScript.

## Settings endpoints

All settings routes require an `Authorization: Bearer <access token>` header and act only on
the authenticated user's own data.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/settings` | Read the full preference document (defaults fill missing keys) |
| `PATCH /api/v1/settings` | Partially update preferences; omitted fields are preserved |
| `POST /api/v1/settings/reset` | Restore every preference to its default |
| `POST /api/v1/settings/memories` | Append a memory (max 50 entries, 500 chars each) |
| `DELETE /api/v1/settings/memories/{index}` | Forget a single memory |
| `DELETE /api/v1/settings/memories` | Forget all memories |
| `GET /api/v1/settings/profile` | Read display name, email, and creation date |
| `PATCH /api/v1/settings/profile` | Update display name and/or email (409 on duplicate email) |
| `POST /api/v1/settings/password` | Rotate password; revokes all other refresh sessions |
| `GET /api/v1/settings/sessions` | List active sessions, flagging the current device |
| `DELETE /api/v1/settings/sessions/{id}` | Revoke one session family |
| `POST /api/v1/settings/sessions/revoke-others` | Revoke every session except the caller's |
| `GET /api/v1/settings/models` | Selectable models, derived from server configuration |
| `GET /api/v1/settings/usage` | Conversation, message, and token counts |
| `GET /api/v1/settings/export` | Portable JSON export of account, preferences, conversations |
| `DELETE /api/v1/settings/conversations` | Permanently delete all conversations |
| `POST /api/v1/settings/delete-account` | Deactivate the account (requires password + `DELETE`) |

## Conversation and chat endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/conversations` | Create a conversation (default title `New conversation`) |
| `GET /api/v1/conversations` | List recent non-archived conversations |
| `GET /api/v1/conversations/{id}` | Fetch one conversation |
| `PATCH /api/v1/conversations/{id}` | Rename a conversation |
| `DELETE /api/v1/conversations/{id}` | Archive (soft-delete) a conversation |
| `GET /api/v1/conversations/{id}/messages` | Message history |
| `POST /api/v1/chat` | Non-streaming chat turn; auto-titles untitled chats |
| `POST /api/v1/chat/stream` | SSE token stream; auto-titles untitled chats |
| `POST /api/v1/chat/messages/{id}/retry` | Retry a cancelled or failed assistant message |

## Integration endpoints

Connect external systems (GitHub, GitLab, Slack, Notion, Linear, Google Drive). Access tokens are hashed at rest; only a short hint is returned.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/integrations/catalog` | Provider catalog with connection status |
| `GET /api/v1/integrations` | Connected integrations for the organization |
| `POST /api/v1/integrations` | Connect or update a provider token |
| `POST /api/v1/integrations/{provider}/verify` | Mark a stored connection as verified |
| `DELETE /api/v1/integrations/{provider}` | Disconnect a provider |

### Validation and safety

- `PATCH /settings` rejects unknown fields (`extra="forbid"`), so clients cannot smuggle
  privileged attributes into the preference document.
- Stored documents ignore unknown keys on read, so preferences saved by older versions
  still load after the schema changes.
- Enumerated fields (`theme`, `accent`, `font_scale`, `density`) and numeric ranges
  (`temperature` 0–2, `max_tokens` 64–16384) are validated server-side.
- Access tokens carry the refresh-session family (`sid`). Revoking a session invalidates
  its access tokens immediately rather than at expiry.

## Chat citations and grounding (Phase 3)

The chat endpoints above gain optional retrieval grounding: passing `knowledge_base_id`
grounds the request in that knowledge base. Passages are retrieved with the configured
embedding provider, injected as delimited **untrusted** reference data (never as
instructions), and returned as citations. Streaming sends `citation` SSE events before
`token` events. Citations are persisted as `citation` message parts on the assistant
message. The knowledge base must belong to the caller's organization (404 otherwise).

## Knowledge base endpoints (Phase 3)

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/knowledge-bases` | Create a knowledge base |
| `GET /api/v1/knowledge-bases` | List the organization knowledge bases |
| `GET /api/v1/knowledge-bases/{id}` | Retrieve one knowledge base |
| `DELETE /api/v1/knowledge-bases/{id}` | Delete a knowledge base and its documents/chunks |
| `GET /api/v1/knowledge-bases/{id}/documents` | List documents with ingestion status |
| `POST /api/v1/knowledge-bases/{id}/documents` | Register governed metadata (source, license, SHA-256) |
| `POST /api/v1/knowledge-bases/{id}/documents/upload` | Multipart upload: quarantine, hash, register, dispatch ingestion |
| `POST /api/v1/knowledge-bases/{id}/search` | Semantic search; returns attributed citations |

### Upload contract

- Multipart form: `file` (required), `source` (required, ≤512 chars), `license`
  (required, ≤256 chars), optional `language`.
- Allowed content types: `text/plain`, `text/markdown`, `application/pdf`,
  `application/json`, `text/csv`. Only plain text and Markdown are parsed at this
  milestone; other accepted types ingest to an explicit `failed` status with a
  `failure_reason` until their parsers land.
- File bytes must be non-empty and ≤ 25 MiB; the hash is computed server-side and
  verified again by the worker before parsing. Duplicate content in the same knowledge
  base returns 409.
- Uploaded bytes are written to quarantined object storage under a server-generated
  key — browser/clients never receive object contents back.

### Ingestion lifecycle

`pending → validating → parsing → chunking → embedding → ready` (any stage can land in
`failed` with a `failure_reason`). With `JAT_INGESTION_DISPATCHER=inline` the pipeline
runs synchronously in the upload request; with `redis` it is processed by workers
started via `python -m jat_api.ingestion.worker`.
