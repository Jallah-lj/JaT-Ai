# Deploying JaT Foundation

## Local services

Docker Compose defines PostgreSQL and Redis. Once Docker is available:

```bash
cp .env.example .env
docker compose up -d postgres redis
make api-migrate
```

Run API and web separately during development:

```bash
cd apps/api && python -m uvicorn jat_api.main:app --host 0.0.0.0 --port 8000
cd apps/web && npm run dev
```

## Container images

```bash
docker build -t jat-api apps/api
docker build -t jat-web apps/web
```

The web container is static output. In production, route `/api` through a gateway to the API and apply TLS, host allowlists, secret injection, database backups, and metrics network restrictions.
