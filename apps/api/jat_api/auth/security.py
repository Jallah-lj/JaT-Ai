"""Password and signed-token primitives; raw secrets are never persisted."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from jat_api.config import Settings

_PASSWORDS = PasswordHasher()


def hash_password(password: str) -> str:
    return _PASSWORDS.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _PASSWORDS.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_access_token(
    user_id: UUID, settings: Settings, *, session_family_id: UUID | None = None
) -> str:
    """Mint an access token, optionally bound to the refresh-session family it came from."""
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": str(user_id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "type": "access",
    }
    if session_family_id is not None:
        claims["sid"] = str(session_family_id)
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_access_token(token: str, settings: Settings) -> dict[str, object]:
    claims = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )
    if claims.get("type") != "access":
        raise jwt.InvalidTokenError("unexpected token type")
    return dict(claims)


def access_token_subject(token: str, settings: Settings) -> UUID:
    return UUID(str(decode_access_token(token, settings)["sub"]))


def access_token_session_family(token: str, settings: Settings) -> UUID | None:
    """Return the refresh-session family bound to this token, when present."""
    raw = decode_access_token(token, settings).get("sid")
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None
