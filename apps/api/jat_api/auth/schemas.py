from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    # When a guest signs up mid-trial, this access token lets the new account
    # claim the guest's conversations instead of starting from a blank slate.
    guest_token: str | None = Field(default=None, max_length=4096)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    id: UUID
    # Plain string: guest identities carry opaque addresses on a reserved
    # domain (e.g. guest-<id>@guest.jat.local) that EmailStr rejects.
    email: str
    display_name: str
    kind: str = "person"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class GuestStatus(BaseModel):
    """Trial-budget snapshot shown by the web client's guest banner."""

    enabled: bool
    # "guest" for an active anonymous session, "person" for signed-up accounts,
    # "anonymous" when no identity is presented.
    kind: str = "anonymous"
    message_limit: int = 0
    messages_used: int = 0
    conversation_limit: int = 0
    conversations: int = 0
    expires_at: datetime | None = None
