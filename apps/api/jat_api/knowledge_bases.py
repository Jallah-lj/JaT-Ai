from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.auth.dependencies import current_user, get_db_session
from jat_api.conversations import organization_for_user
from jat_api.db.models import KnowledgeBase, User
from jat_api.db.repositories import write_audit_log

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge bases"])


class CreateKnowledgeBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=10_000)


class KnowledgeBaseResponse(BaseModel):
    id: UUID
    name: str
    description: str | None


async def owned(db: AsyncSession, user: User, kb_id: UUID) -> KnowledgeBase:
    org = await organization_for_user(db, user)
    kb = await db.scalar(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.organization_id == org)
    )
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


@router.post("", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create(
    payload: CreateKnowledgeBase,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeBaseResponse:
    kb = KnowledgeBase(
        organization_id=await organization_for_user(db, user),
        name=payload.name.strip(),
        description=payload.description,
    )
    db.add(kb)
    await write_audit_log(
        db,
        action="knowledge_base.create",
        resource_type="knowledge_base",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
    await db.refresh(kb)
    return KnowledgeBaseResponse.model_validate(kb, from_attributes=True)


@router.get("", response_model=list[KnowledgeBaseResponse])
async def list_all(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db_session)
) -> list[KnowledgeBaseResponse]:
    org = await organization_for_user(db, user)
    rows = await db.scalars(
        select(KnowledgeBase)
        .where(KnowledgeBase.organization_id == org)
        .order_by(KnowledgeBase.name)
    )
    return [KnowledgeBaseResponse.model_validate(row, from_attributes=True) for row in rows]


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_one(
    kb_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db_session)
) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse.model_validate(await owned(db, user, kb_id), from_attributes=True)


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    kb_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    kb = await owned(db, user, kb_id)
    await db.delete(kb)
    await write_audit_log(
        db,
        action="knowledge_base.delete",
        resource_type="knowledge_base",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()


class RegisterDocument(BaseModel):
    source: str = Field(min_length=1, max_length=512)
    license: str = Field(min_length=1, max_length=256)
    content_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-fA-F0-9]{64}$")
    language: str | None = Field(default=None, max_length=24)


class DocumentResponse(BaseModel):
    id: UUID
    source: str
    license: str | None
    content_hash: str
    status: str


@router.post(
    "/{kb_id}/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED
)
async def register_document(
    kb_id: UUID,
    payload: RegisterDocument,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DocumentResponse:
    from jat_api.db.models import Document

    kb = await owned(db, user, kb_id)
    duplicate = await db.scalar(
        select(Document).where(
            Document.knowledge_base_id == kb.id,
            Document.content_hash == payload.content_hash.lower(),
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Document content already registered")
    document = Document(
        knowledge_base_id=kb.id,
        source=payload.source.strip(),
        license=payload.license.strip(),
        content_hash=payload.content_hash.lower(),
        language=payload.language,
        status="pending",
    )
    db.add(document)
    await write_audit_log(
        db,
        action="document.register",
        resource_type="document",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    await db.commit()
    await db.refresh(document)
    return DocumentResponse.model_validate(document, from_attributes=True)
