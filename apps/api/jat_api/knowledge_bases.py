"""Organization-scoped knowledge bases, governed uploads, and semantic search."""

import hashlib
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jat_api.auth.dependencies import current_user, get_db_session
from jat_api.conversations import organization_for_user
from jat_api.db.models import Document, KnowledgeBase, User
from jat_api.db.repositories import write_audit_log
from jat_api.ingestion.jobs import IngestionJob
from jat_api.ingestion.policy import ALLOWED_TYPES, MAX_BYTES
from jat_api.rag.retrieval import retrieve
from jat_api.rag.store import PostgresVectorStore

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge bases"])

_UPLOAD_READ_CHUNK = 1024 * 1024


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
    content_type: str | None = None
    size_bytes: int | None = None
    original_filename: str | None = None
    failure_reason: str | None = None


@router.get("/{kb_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    kb_id: UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db_session)
) -> list[DocumentResponse]:
    kb = await owned(db, user, kb_id)
    rows = await db.scalars(
        select(Document)
        .where(Document.knowledge_base_id == kb.id)
        .order_by(Document.source, Document.id)
    )
    return [DocumentResponse.model_validate(row, from_attributes=True) for row in rows]


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


@router.post(
    "/{kb_id}/documents/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    kb_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    source: str = Form(min_length=1, max_length=512),
    license: str = Form(min_length=1, max_length=256),
    language: str | None = Form(default=None, max_length=24),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DocumentResponse:
    """Quarantine an upload, hash it, register governance metadata, and dispatch ingestion."""
    kb = await owned(db, user, kb_id)
    organization_id = kb.organization_id
    content_type = (file.content_type or "application/octet-stream").split(";")[0].strip().lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported content type")

    hasher = hashlib.sha256()
    buffer = bytearray()
    while chunk := await file.read(_UPLOAD_READ_CHUNK):
        buffer.extend(chunk)
        hasher.update(chunk)
        if len(buffer) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="Upload exceeds the 25 MiB limit")
    if not buffer:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    content_hash = hasher.hexdigest()

    duplicate = await db.scalar(
        select(Document).where(
            Document.knowledge_base_id == kb.id,
            Document.content_hash == content_hash,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Document content already registered")

    object_key = f"quarantine/{organization_id}/{uuid4()}"
    await request.app.state.object_store.put(object_key, bytes(buffer))

    document = Document(
        knowledge_base_id=kb.id,
        source=source.strip(),
        license=license.strip(),
        content_hash=content_hash,
        language=language,
        status="pending",
        object_key=object_key,
        content_type=content_type,
        size_bytes=len(buffer),
        original_filename=(file.filename or "")[:256] or None,
    )
    db.add(document)
    await write_audit_log(
        db,
        action="document.upload",
        resource_type="document",
        actor_user_id=user.id,
        request_id=request.headers.get("X-Request-ID"),
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        await request.app.state.object_store.delete(object_key)  # never orphan objects
        raise HTTPException(status_code=409, detail="Document content already registered") from None
    await db.refresh(document)

    # Dispatch only after commit so workers always see committed registration state.
    await request.app.state.ingestion_dispatcher.dispatch(
        IngestionJob(
            document_id=document.id,
            organization_id=organization_id,
            object_key=object_key,
            declared_content_type=content_type,
            source=document.source,
            license=document.license or "",
        )
    )
    await db.refresh(document)  # inline dispatch may have advanced the status already
    return DocumentResponse.model_validate(document, from_attributes=True)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8_000)
    limit: int = Field(default=8, ge=1, le=50)


@router.post("/{kb_id}/search")
async def search_knowledge_base(
    kb_id: UUID,
    payload: SearchRequest,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[dict[str, object]]:
    kb = await owned(db, user, kb_id)
    citations = await retrieve(
        embedder=request.app.state.embedding_provider,
        store=PostgresVectorStore(db),
        organization_id=kb.organization_id,
        query=payload.query,
        limit=payload.limit,
        knowledge_base_id=kb.id,
    )
    return [citation.to_dict() for citation in citations]
