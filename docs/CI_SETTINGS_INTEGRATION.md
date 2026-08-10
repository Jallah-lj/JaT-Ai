# Enabling the settings integration suite in CI

`apps/api/tests/test_settings_integration.py` exercises the settings endpoints against a
real PostgreSQL database. It **skips automatically** unless `JAT_TEST_DATABASE_URL` is set,
so CI stays green without this change — but the 14 integration tests will not run.

This repository's CI workflow could not be updated automatically, because GitHub refuses
workflow edits from an app without the `workflows` permission. Apply the patch below to
`.github/workflows/ci.yml` to enable the suite.

Replace the `backend` job with:

```yaml
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: jat_test
          POSTGRES_USER: jat
          POSTGRES_PASSWORD: jat_ci_password
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U jat -d jat_test"
          --health-interval 5s --health-timeout 5s --health-retries 10
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      JAT_TEST_DATABASE_URL: postgresql+asyncpg://jat:jat_ci_password@localhost:5432/jat_test
      JAT_TEST_REDIS_URL: redis://localhost:6379/1
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -e "./apps/api[dev]"
      - run: make api-lint api-type
      - name: Apply migrations to the test database
        run: cd apps/api && python -m alembic upgrade head
        env:
          JAT_DATABASE_URL: postgresql+asyncpg://jat:jat_ci_password@localhost:5432/jat_test
      - run: make api-test
      - run: cd apps/api && python -m alembic upgrade head --sql > /dev/null
```

## Running the suite locally

```bash
docker compose up -d postgres redis
cd apps/api && JAT_DATABASE_URL=postgresql+asyncpg://jat:20064@localhost:5432/jat \
  python -m alembic upgrade head
JAT_TEST_DATABASE_URL=postgresql+asyncpg://jat:20064@localhost:5432/jat \
  python -m pytest apps/api/tests
```
