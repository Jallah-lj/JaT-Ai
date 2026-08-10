.PHONY: dev-up dev-down dev-reset api-migrate api-install api-format api-lint api-type api-test web-install web-lint web-type web-test web-build verify

# ---- Local development bootstrapping --------------------------------------
# These targets require Docker. They start Postgres and Redis with credentials
# that match .env.example, tear them down, or reset them (useful when you've
# changed credentials or have a stale volume from an old install).
dev-up:
	@if ! command -v docker >/dev/null 2>&1; then \
		echo "error: docker is required for 'make dev-up'. Install Docker Desktop or docker-engine." >&2; \
		exit 1; \
	fi
	@if [ ! -f .env ]; then \
		echo "==> Copying .env.example to .env"; \
		cp .env.example .env; \
	fi
	docker compose up -d postgres redis
	@echo "==> Waiting for Postgres to accept connections on localhost:5432 ..."
	@for i in $$(seq 1 30); do \
		if docker compose exec -T postgres pg_isready -U jat -d jat >/dev/null 2>&1; then \
			echo "==> Postgres is ready."; \
			break; \
		fi; \
		sleep 1; \
	done
	@docker compose exec -T redis redis-cli ping >/dev/null 2>&1 && echo "==> Redis is ready."
	@echo "==> Run 'make api-migrate' to apply migrations, then start the API."

dev-down:
	docker compose down

dev-reset:
	@echo "==> Stopping services and deleting the Postgres volume (ALL DATA WILL BE LOST) ..."
	docker compose down -v
	@$(MAKE) --no-print-directory dev-up

api-migrate:
	set -a; \
	if [ -f .env ]; then . ./.env; fi; \
	if [ -f apps/api/.env ]; then . ./apps/api/.env; fi; \
	cd apps/api && python3 -m alembic upgrade head
api-install:
	python3 -m pip install -e "./apps/api[dev]"
api-format:
	python3 -m ruff format apps/api
api-lint:
	python3 -m ruff check apps/api
api-type:
	python3 -m mypy apps/api/jat_api
api-test:
	python3 -m pytest apps/api/tests
web-install:
	npm --prefix apps/web install
web-lint:
	npm --prefix apps/web run lint
web-type:
	npm --prefix apps/web run typecheck
web-test:
	npm --prefix apps/web run test
web-build:
	npm --prefix apps/web run build
verify: api-lint api-type api-test web-lint web-type web-test web-build
