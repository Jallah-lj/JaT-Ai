.PHONY: api-migrate api-install api-format api-lint api-type api-test web-install web-lint web-type web-test web-build verify

api-migrate:
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
