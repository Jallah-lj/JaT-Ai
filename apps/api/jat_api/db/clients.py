"""Narrow infrastructure clients. Repositories will be added with migrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


@dataclass(frozen=True)
class PingResult:
    """The outcome of pinging a backing service, suitable for operator diagnostics."""

    name: str
    ok: bool
    # A short, operator-facing hint (no secrets / no raw DSN).
    detail: str | None = None

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self.ok


_SAFE_HINTS = (
    # Map recognisable exception substrings to actionable, non-secret diagnostic hints.
    # We never include the DSN, password, or host/port in order to avoid leaking
    # credentials into logs or HTTP responses.
    ("password authentication failed", "credentials rejected by server"),
    ("no password supplied", "server requires a password"),
    ("database .* does not exist", "target database does not exist"),
    ("connection refused", "server is not reachable on the configured host/port"),
    ("Name or service not known", "configured hostname cannot be resolved"),
    ("Temporary failure in name resolution", "DNS resolution failed for configured host"),
    ("SSL is required", "server requires SSL/TLS"),
    ("certificate verify failed", "TLS certificate verification failed"),
    ("timeout expired", "connect timed out"),
    ("connection reset by peer", "connection was reset by the server"),
    ("too many clients", "server rejected connection due to connection limit"),
    ("role .* does not exist", "configured database user does not exist"),
    ("AUTH", "Redis authentication failed"),
    ("NOAUTH", "Redis requires authentication"),
    ("WRONGPASS", "Redis password is incorrect"),
    ("Connection refused", "server is not reachable on the configured host/port"),
    ("EOFError", "server closed the connection during handshake"),
)


def _safe_hint(exc: BaseException) -> str:
    """Translate a driver exception into a credential-safe operator hint."""
    message = str(exc).replace("\n", " ").strip()
    import re

    for needle, hint in _SAFE_HINTS:
        if re.search(needle, message, flags=re.IGNORECASE):
            return hint
    # Fall back to the exception type name only — never raw DSNs or query text.
    return type(exc).__name__


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def ping(self) -> bool:
        return (await self.ping_detailed()).ok

    async def ping_detailed(self) -> PingResult:
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:  # readiness intentionally fails closed
            return PingResult(name="postgres", ok=False, detail=_safe_hint(exc))
        return PingResult(name="postgres", ok=True)

    async def close(self) -> None:
        await self.engine.dispose()


class RedisClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self.client: Redis = Redis.from_url(url, decode_responses=True)

    async def ping(self) -> bool:
        return (await self.ping_detailed()).ok

    async def ping_detailed(self) -> PingResult:
        try:
            if not await self.client.ping():
                return PingResult(name="redis", ok=False, detail="non-PONG response")
        except Exception as exc:  # readiness intentionally fails closed
            return PingResult(name="redis", ok=False, detail=_safe_hint(exc))
        return PingResult(name="redis", ok=True)

    async def close(self) -> None:
        await self.client.aclose()


def _collect_asyncpg_errors() -> tuple[type[BaseException], ...]:
    """Collect asyncpg connection/auth error classes defensively.

    asyncpg organises exceptions across modules; not every class is exported at
    the top-level ``asyncpg`` namespace in every version, so we resolve each by
    hand and silently skip any that aren't present. We always include at least
    ``PostgresConnectionError`` (the documented connection-error base) and the
    built-in transport errors.
    """
    classes: list[type[BaseException]] = [ConnectionRefusedError, TimeoutError, OSError]
    try:
        import asyncpg  # type: ignore[import-untyped]
    except Exception:  # pragma: no cover - asyncpg missing (unusual)
        return tuple(classes)
    names = (
        ("PostgresConnectionError",),
        ("InvalidPasswordError",),
        ("InvalidAuthorizationSpecificationError",),
        ("InvalidCatalogNameError",),
        ("CannotConnectNowError",),
        # asyncpg >= 0.29 splits some errors into submodules
        ("exceptions", "PostgresConnectionError"),
        ("exceptions", "InvalidPasswordError"),
        ("exceptions", "InvalidAuthorizationSpecificationError"),
        ("exceptions", "InvalidCatalogNameError"),
        ("exceptions", "CannotConnectNowError"),
        ("exceptions", "ClientConfigurationError"),
        ("exceptions", "BackendKeyError"),  # not connection-related, ignore
    )
    seen: set[str] = set()
    for spec in names:
        try:
            obj: Any = asyncpg
            for attr in spec:
                obj = getattr(obj, attr)
            if isinstance(obj, type) and issubclass(obj, BaseException):
                qual = ".".join(spec)
                if qual not in seen:
                    classes.append(obj)
                    seen.add(qual)
        except AttributeError:
            continue
    return tuple(dict.fromkeys(classes))  # de-dupe by identity


_ASYNCPG_ERRORS: tuple[type[BaseException], ...] | None = None


def is_database_unavailable_error(exc: BaseException) -> bool:
    """Return True if ``exc`` is a DB connection/authentication error.

    Used by the global exception handler to translate these into 503s instead
    of leaking a 500 with a driver stack trace.
    """
    global _ASYNCPG_ERRORS
    if _ASYNCPG_ERRORS is None:
        _ASYNCPG_ERRORS = _collect_asyncpg_errors()

    from sqlalchemy.exc import OperationalError

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, _ASYNCPG_ERRORS):
            return True
        # SQLAlchemy OperationalError wraps driver-level connect/auth failures;
        # IntegrityError/DataError etc. are real application errors and must
        # not become 503s.
        if isinstance(current, SQLAlchemyError) and isinstance(current, OperationalError):
            return True
        current = current.__cause__ or current.__context__
    return False


_REDIS_ERRORS: tuple[type[BaseException], ...] | None = None


def _collect_redis_errors() -> tuple[type[BaseException], ...]:
    classes: list[type[BaseException]] = [ConnectionRefusedError, TimeoutError, OSError]
    try:
        import redis.exceptions as rex
    except Exception:  # pragma: no cover
        return tuple(classes)
    names = (
        "ConnectionError",
        "TimeoutError",
        "AuthenticationError",
        "AuthenticationWrongNumberOfArgsError",
        "NoPermissionError",
        "BusyLoadingError",
        "ReadOnlyError",
        "ClusterDownError",
    )
    for name in names:
        cls = getattr(rex, name, None)
        if isinstance(cls, type) and issubclass(cls, BaseException):
            classes.append(cls)
    # ``redis.exceptions.ConnectionError`` also inherits from the built-in
    # ``ConnectionError``/``OSError`` in recent redis-py releases; de-dupe.
    return tuple(dict.fromkeys(classes))


def is_redis_unavailable_error(exc: BaseException) -> bool:
    """Return True if ``exc`` is a Redis connection/authentication error."""
    global _REDIS_ERRORS
    if _REDIS_ERRORS is None:
        _REDIS_ERRORS = _collect_redis_errors()

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, _REDIS_ERRORS):
            return True
        current = current.__cause__ or current.__context__
    return False


def any_backing_service_error(exc: BaseException) -> str | None:
    """Return ``"postgres"``/``"redis"`` if ``exc`` is a connectivity error, else ``None``."""
    if is_database_unavailable_error(exc):
        # Prefer a specific hint so the 503 response is actionable.
        return "postgres"
    if is_redis_unavailable_error(exc):
        return "redis"
    return None
