"""Strongly typed, environment-backed JaT configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Settings validated before JaT accepts requests."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="JAT_", extra="ignore")

    environment: Literal["development", "testing", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://jat:jat_dev_password@localhost:5432/jat"
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
    service_version: str = "0.1.0"
    model_provider: str = "deterministic"
    model_name: str = "jat-development"
    model_endpoint: str | None = None
    model_context_length: int = Field(default=8192, ge=256, le=1_000_000)
    model_max_tokens: int = Field(default=1024, ge=1, le=16384)
    model_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

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
