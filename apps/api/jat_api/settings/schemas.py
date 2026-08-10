"""User-facing preference, profile, and account-control contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Theme = Literal["light", "dark", "system"]
Accent = Literal["evergreen", "citrus", "ocean", "violet", "ember"]
FontScale = Literal["small", "medium", "large"]
Density = Literal["comfortable", "compact"]

MAX_MEMORIES = 50
MAX_MEMORY_LENGTH = 500


class Preferences(BaseModel):
    """Complete, always-defaulted preference document persisted per user."""

    model_config = ConfigDict(extra="ignore")

    # Appearance
    theme: Theme = "system"
    accent: Accent = "evergreen"
    font_scale: FontScale = "medium"
    density: Density = "comfortable"
    reduced_motion: bool = False

    # Chat behaviour
    default_model: str = Field(default="jat-development", min_length=1, max_length=120)
    stream_responses: bool = True
    send_on_enter: bool = True
    show_timestamps: bool = False
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=64, le=16384)
    system_prompt: str = Field(default="", max_length=4000)

    # Memory
    memory_enabled: bool = True
    memories: list[str] = Field(default_factory=list, max_length=MAX_MEMORIES)

    # Data controls
    chat_history_enabled: bool = True
    analytics_enabled: bool = False

    # Notifications
    sound_on_response: bool = False
    email_product_updates: bool = False


class PreferencesUpdate(BaseModel):
    """Partial preference patch. Omitted fields keep their stored value."""

    model_config = ConfigDict(extra="forbid")

    theme: Theme | None = None
    accent: Accent | None = None
    font_scale: FontScale | None = None
    density: Density | None = None
    reduced_motion: bool | None = None

    default_model: str | None = Field(default=None, min_length=1, max_length=120)
    stream_responses: bool | None = None
    send_on_enter: bool | None = None
    show_timestamps: bool | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=64, le=16384)
    system_prompt: str | None = Field(default=None, max_length=4000)

    memory_enabled: bool | None = None
    memories: list[str] | None = Field(default=None, max_length=MAX_MEMORIES)

    chat_history_enabled: bool | None = None
    analytics_enabled: bool | None = None

    sound_on_response: bool | None = None
    email_product_updates: bool | None = None


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_MEMORY_LENGTH)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None


class ProfileResponse(BaseModel):
    id: UUID
    # Plain string: guest identities carry opaque reserved-domain addresses.
    email: str
    display_name: str
    created_at: datetime


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class AccountDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256)
    confirmation: str = Field(min_length=1, max_length=64)


class ModelOption(BaseModel):
    id: str
    label: str
    description: str
    provider: str
    available: bool
    context_length: int


class SessionSummary(BaseModel):
    id: UUID
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    current: bool


class UsageStats(BaseModel):
    conversations: int
    messages: int
    input_tokens: int
    output_tokens: int
    first_activity_at: datetime | None
    last_activity_at: datetime | None


class OperationResult(BaseModel):
    ok: bool = True
    removed: int = 0
    detail: str = ""
