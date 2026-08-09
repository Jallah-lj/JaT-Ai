# JaT Security Baseline

## Current controls

- Argon2id password hashing
- short-lived signed JWT access tokens
- opaque, hashed, rotating refresh credentials
- cookie `HttpOnly`, `SameSite=Lax`, constrained auth path, and `Secure` outside development
- origin validation for refresh/logout cookie requests
- strict staging/production secret and CORS validation
- Redis-backed auth rate limiter with production fail-closed behavior
- request limits, validation, SQLAlchemy parameter binding, security headers
- structured request IDs and allowlisted audit events

## Deployment requirements

Deploy only behind TLS. Store `JAT_JWT_SECRET`, database credentials, and service credentials in a managed secret store. Restrict `/metrics` to internal monitoring networks. Configure trusted proxies before using forwarded client-IP headers. Run migrations through reviewed deployment automation, not interactive production shells.

## Password policy

Registration and password changes require at least **8 characters** (Argon2id hashed). Prefer longer passphrases in production.

## Integrations

External connections (GitHub, GitLab, Slack, Notion, Linear, Google Drive) accept personal access tokens. Tokens are Argon2id-hashed at rest; only a short hint is returned to the client. Live OAuth and outbound provider calls are not yet enabled — connect/verify/disconnect manage stored credentials only.

## Explicitly not yet shipped

MFA, email verification delivery, API-key issuance endpoints, RBAC-protected resources, durable file uploads, tool execution, full RAG retrieval, and live OAuth provider probes are not present yet.
