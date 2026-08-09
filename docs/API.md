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
