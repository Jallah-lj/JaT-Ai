import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context
from jat_api.db.models import Base


def _load_dotenv_file(path: Path) -> None:
    """Minimal .env loader that doesn't override existing env vars."""
    if not path.is_file():
        return
    try:
        with path.open() as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and (
                    (value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")
                ):
                    value = value[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        # Never fail migrations because .env couldn't be read
        pass


def _load_project_env() -> None:
    """Load JAT_DATABASE_URL from .env if not already set.

    This makes `make api-migrate` and direct `alembic` invocations work
    even when the shell hasn't exported variables from the project .env file.
    """
    if os.environ.get("JAT_DATABASE_URL"):
        return

    # Prefer python-dotenv if available - it handles quoting/expansion better.
    try:
        from dotenv import load_dotenv

        candidates = [
            Path.cwd() / ".env",
            Path.cwd().parent / ".env",
            Path.cwd().parent.parent / ".env",
            Path(__file__).resolve().parent.parent / ".env",  # apps/api/.env
            Path(__file__).resolve().parents[3] / ".env",  # repo root .env
        ]
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            if resolved in seen:
                continue
            seen.add(resolved)
            if resolved.is_file():
                load_dotenv(resolved, override=False)
                if os.environ.get("JAT_DATABASE_URL"):
                    return
    except ImportError:
        pass

    # Fallback to our minimal parser
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parents[3] / ".env",
    ]
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        _load_dotenv_file(resolved)
        if os.environ.get("JAT_DATABASE_URL"):
            return


_load_project_env()

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

database_url = os.environ.get("JAT_DATABASE_URL", config.get_main_option("sqlalchemy.url"))
# Alembic executes synchronously; application traffic uses asyncpg separately.
config.set_main_option("sqlalchemy.url", database_url.replace("+asyncpg", "+psycopg"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
