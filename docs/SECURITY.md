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

## Explicitly not yet shipped

MFA, email verification delivery, API-key issuance endpoints, RBAC-protected resources, file uploads, tool execution, RAG, and model integrations are not present in Phase 1.
