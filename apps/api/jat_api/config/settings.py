"""Strongly typed, environment-backed JaT configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Allow .env in either the working directory or the repository root (two levels
# up from this file) so that `python -m uvicorn jat_api.main:app` works whether it
# is run from apps/api/ or from the repo root. Explicit environment variables
# always take precedence over files; the first file that exists wins among the
# list (env values are not overridden by later files).
_THIS_DIR = Path(__file__).resolve().parent
_ENV_FILE_CANDIDATES = (
    Path(".env"),
    _THIS_DIR / ".env",  # apps/api/jat_api/.env (unlikely)
    _THIS_DIR.parent.parent / ".env",  # apps/api/.env
    _THIS_DIR.parent.parent.parent / ".env",  # repo-root .env (per README)
)
_ENV_FILES = tuple(str(p) for p in _ENV_FILE_CANDIDATES if p.exists())


class Settings(BaseSettings):
    """Settings validated before JaT accepts requests."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        env_prefix="JAT_",
        extra="ignore",
    )

    environment: Literal["development", "testing", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://jat:20064@localhost:5432/jat"
    redis_url: str = "redis://localhost:6379/0"
    jwt_issuer: str = "jat-api"
    jwt_audience: str = "jat-web"
    jwt_secret: SecretStr = SecretStr("replace-with-a-unique-32-character-minimum-secret")
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)
    # NoDecode keeps pydantic-settings from JSON-parsing the raw env value so the
    # documented comma-separated form in .env.example loads correctly.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    request_max_bytes: int = Field(default=1_048_576, ge=1_024, le=52_428_800)
    auth_rate_limit_attempts: int = Field(default=10, ge=1, le=100)
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    # Guest / trial access — visitors can experiment with the LLM before creating
    # an account. Enforce a message budget and a time window; when either is
    # exhausted the client is asked to sign up (guests can convert and keep
    # their conversations).
    guest_enabled: bool = True
    guest_message_limit: int = Field(default=10, ge=1, le=1000)
    guest_ttl_hours: int = Field(default=24, ge=1, le=720)
    guest_max_conversations: int = Field(default=5, ge=1, le=100)
    service_version: str = "0.1.0"
    model_provider: str = "ollama"
    model_name: str = "llama3.1:latest"
    model_endpoint: str | None = "http://127.0.0.1:11434"
    model_context_length: int = Field(default=8192, ge=256, le=1_000_000)
    model_max_tokens: int = Field(default=1024, ge=1, le=16384)
    model_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    # Operator-level baseline persona used only when a user has no system prompt of their own.
    default_system_prompt: str = ""
    # Phase 3: governed ingestion and retrieval.
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_endpoint: str | None = "http://127.0.0.1:11434"
    object_store_dir: str = ".jat-data/objects"
    ingestion_dispatcher: Literal["inline", "redis", "local"] = "inline"
    ingestion_queue: str = "jat:ingestion"
    upload_max_bytes: int = Field(default=26_214_400, ge=1_024, le=52_428_800)
    rag_chunk_max_chars: int = Field(default=1000, ge=100, le=8000)
    rag_chunk_overlap: int = Field(default=200, ge=0, le=4000)
    rag_search_limit: int = Field(default=8, ge=1, le=50)
    rag_max_citations: int = Field(default=5, ge=0, le=20)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        """Accept a comma-separated string or a JSON array of origins."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                import json

                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def secure_deployment_settings(self) -> Settings:
        if self.rag_chunk_overlap >= self.rag_chunk_max_chars:
            raise ValueError("JAT_RAG_CHUNK_OVERLAP must be smaller than JAT_RAG_CHUNK_MAX_CHARS")
        secret = self.jwt_secret.get_secret_value()
        if self.environment in {"staging", "production"}:
            if len(secret) < 32 or secret.startswith("replace-with-"):
                raise ValueError(
                    "JAT_JWT_SECRET must be unique and at least 32 characters outside development"
                )
            if "*" in self.cors_origins:
                raise ValueError("wildcard CORS origins are forbidden outside development")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
