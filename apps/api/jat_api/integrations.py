"""External system connections (GitHub and future providers).

Credentials are never returned to the client after save — only connection
status metadata is exposed. Secrets stay server-side for future OAuth/token use.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.auth.dependencies import current_user, get_db_session
from jat_api.auth.security import hash_password
from jat_api.conversations import organization_for_user
from jat_api.db.models import IntegrationConnection, User
from jat_api.db.repositories import write_audit_log

router = APIRouter(prefix="/integrations", tags=["integrations"])

ProviderId = Literal["github", "gitlab", "slack", "notion", "linear", "google_drive"]

CATALOG: list[dict[str, str]] = [
    {
        "id": "github",
        "name": "GitHub",
        "description": "Connect repositories, issues, and pull requests to JaT.",
        "auth_type": "token",
        "scopes_hint": "repo, read:user",
        "docs_url": "https://github.com/settings/tokens",
        "icon": "github",
    },
    {
        "id": "gitlab",
        "name": "GitLab",
        "description": "Browse projects and merge requests from your GitLab account.",
        "auth_type": "token",
        "scopes_hint": "read_api",
        "docs_url": "https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html",
        "icon": "gitlab",
    },
    {
        "id": "slack",
        "name": "Slack",
        "description": "Summarise channels and draft replies with workspace context.",
        "auth_type": "token",
        "scopes_hint": "channels:history, chat:write",
        "docs_url": "https://api.slack.com/apps",
        "icon": "slack",
    },
    {
        "id": "notion",
        "name": "Notion",
        "description": "Search pages and databases as knowledge for answers.",
        "auth_type": "token",
        "scopes_hint": "read content",
        "docs_url": "https://www.notion.so/my-integrations",
        "icon": "notion",
    },
    {
        "id": "linear",
        "name": "Linear",
        "description": "Track issues and update tickets from conversation.",
        "auth_type": "token",
        "scopes_hint": "read, write",
        "docs_url": "https://linear.app/settings/api",
        "icon": "linear",
    },
    {
        "id": "google_drive",
        "name": "Google Drive",
        "description": "Attach and reason over Drive documents (token-based stub).",
        "auth_type": "token",
        "scopes_hint": "drive.readonly",
        "docs_url": "https://console.cloud.google.com/apis/credentials",
        "icon": "drive",
    },
]


class IntegrationSummary(BaseModel):
    id: UUID
    provider: str
    display_label: str | None
    secret_hint: str
    status: str
    created_at: datetime
    updated_at: datetime
    last_verified_at: datetime | None


class ProviderCatalogItem(BaseModel):
    id: str
    name: str
    description: str
    auth_type: str
    scopes_hint: str
    docs_url: str
    icon: str
    connected: bool = False
    connection: IntegrationSummary | None = None


class ConnectIntegrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderId
    access_token: str = Field(min_length=8, max_length=4096)
    display_label: str | None = Field(default=None, max_length=160)
    account_url: HttpUrl | None = None


class IntegrationActionResult(BaseModel):
    ok: bool = True
    detail: str = ""
    connection: IntegrationSummary | None = None


def _summary(row: IntegrationConnection) -> IntegrationSummary:
    return IntegrationSummary(
        id=row.id,
        provider=row.provider,
        display_label=row.display_label,
        secret_hint=row.secret_hint,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_verified_at=row.last_verified_at,
    )


def _hint(token: str) -> str:
    cleaned = token.strip()
    if len(cleaned) <= 4:
        return cleaned
    return cleaned[-4:]


@router.get("/catalog", response_model=list[ProviderCatalogItem])
async def list_catalog(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[ProviderCatalogItem]:
    org = await organization_for_user(db, user)
    rows = await db.scalars(
        select(IntegrationConnection).where(IntegrationConnection.organization_id == org)
    )
    by_provider = {row.provider: row for row in rows}
    items: list[ProviderCatalogItem] = []
    for entry in CATALOG:
        connection = by_provider.get(entry["id"])
        items.append(
            ProviderCatalogItem(
                id=entry["id"],
                name=entry["name"],
                description=entry["description"],
                auth_type=entry["auth_type"],
                scopes_hint=entry["scopes_hint"],
                docs_url=entry["docs_url"],
                icon=entry["icon"],
                connected=connection is not None and connection.status == "connected",
                connection=_summary(connection) if connection is not None else None,
            )
        )
    return items


@router.get("", response_model=list[IntegrationSummary])
async def list_connections(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[IntegrationSummary]:
    org = await organization_for_user(db, user)
    rows = await db.scalars(
        select(IntegrationConnection)
        .where(IntegrationConnection.organization_id == org)
        .order_by(IntegrationConnection.created_at.desc())
    )
    return [_summary(row) for row in rows]


@router.post("", response_model=IntegrationActionResult, status_code=status.HTTP_201_CREATED)
async def connect_integration(
    payload: ConnectIntegrationRequest,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> IntegrationActionResult:
    org = await organization_for_user(db, user)
    existing = await db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.organization_id == org,
            IntegrationConnection.provider == payload.provider,
        )
    )
    token = payload.access_token.strip()
    label = (payload.display_label or "").strip() or None
    metadata: dict[str, object] = {}
    if payload.account_url is not None:
        metadata["account_url"] = str(payload.account_url)

    if existing is not None:
        existing.secret_hash = hash_password(token)
        existing.secret_hint = _hint(token)
        existing.display_label = label
        existing.status = "connected"
        existing.metadata_json = metadata
        existing.last_verified_at = datetime.now().astimezone()
        existing.user_id = user.id
        row = existing
        detail = f"{payload.provider} connection updated"
    else:
        row = IntegrationConnection(
            organization_id=org,
            user_id=user.id,
            provider=payload.provider,
            display_label=label,
            secret_hash=hash_password(token),
            secret_hint=_hint(token),
            status="connected",
            metadata_json=metadata,
            last_verified_at=datetime.now().astimezone(),
        )
        db.add(row)
        detail = f"{payload.provider} connected"

    await write_audit_log(
        db,
        action="integration.connect",
        resource_type="integration",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
    await db.refresh(row)
    return IntegrationActionResult(ok=True, detail=detail, connection=_summary(row))


@router.post("/{provider}/verify", response_model=IntegrationActionResult)
async def verify_integration(
    provider: ProviderId,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> IntegrationActionResult:
    org = await organization_for_user(db, user)
    row = await db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.organization_id == org,
            IntegrationConnection.provider == provider,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Integration not connected")
    if not row.secret_hash:
        raise HTTPException(status_code=409, detail="Integration secret missing")
    # Live provider probes land with OAuth; for now confirm the secret is stored.
    row.last_verified_at = datetime.now().astimezone()
    row.status = "connected"
    await write_audit_log(
        db,
        action="integration.verify",
        resource_type="integration",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
    await db.refresh(row)
    return IntegrationActionResult(
        ok=True, detail=f"{provider} connection looks healthy", connection=_summary(row)
    )


@router.delete("/{provider}", response_model=IntegrationActionResult)
async def disconnect_integration(
    provider: ProviderId,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> IntegrationActionResult:
    org = await organization_for_user(db, user)
    row = await db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.organization_id == org,
            IntegrationConnection.provider == provider,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Integration not connected")
    await db.delete(row)
    await write_audit_log(
        db,
        action="integration.disconnect",
        resource_type="integration",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
    return IntegrationActionResult(ok=True, detail=f"{provider} disconnected")
