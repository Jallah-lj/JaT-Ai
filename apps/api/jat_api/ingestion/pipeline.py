"""Governed ingestion pipeline: validate → parse → chunk → embed → index.

Every stage transition follows the finite state model in ``transitions``.
Failures mark the document ``failed`` with a user-comprehensible reason and are
audited; unexpected errors are logged without leaking internals into the record.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import uuid4

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from jat_api.config import Settings
from jat_api.db.models import Document, KnowledgeBase
from jat_api.db.repositories import write_audit_log
from jat_api.ingestion.chunking import chunk_text
from jat_api.ingestion.extraction import IngestionError, extract_text
from jat_api.ingestion.jobs import IngestionJob
from jat_api.ingestion.policy import validate_upload_metadata
from jat_api.ingestion.transitions import can_transition
from jat_api.rag.contracts import DocumentChunk, EmbeddingProvider
from jat_api.rag.store import PostgresVectorStore
from jat_api.storage import ObjectNotFoundError, ObjectStore

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IngestionOutcome:
    document_id: str
    status: str
    chunks: int = 0
    failure_reason: str | None = None


def validate_object(document: Document, job: IngestionJob, data: bytes) -> None:
    """Verify the quarantined object against governed registration metadata."""
    if document.object_key != job.object_key:
        raise IngestionError("Stored object does not match the registered document")
    if document.content_type is None:
        raise IngestionError("Document has no declared content type")
    try:
        validate_upload_metadata(document.content_type, len(data))
    except ValueError as error:
        raise IngestionError(str(error)) from error
    digest = hashlib.sha256(data).hexdigest()
    if digest != document.content_hash.lower():
        raise IngestionError("Stored object does not match the registered content hash")


def _transition(document: Document, target: str) -> None:
    if not can_transition(document.status, target):
        raise RuntimeError(f"Illegal ingestion transition {document.status} -> {target}")
    document.status = target


async def process_ingestion_job(
    job: IngestionJob,
    *,
    session_factory: async_sessionmaker,
    object_store: ObjectStore,
    embedder: EmbeddingProvider,
    settings: Settings,
) -> IngestionOutcome:
    """Process one ingestion job to a terminal state; safe to retry (idempotent)."""
    async with session_factory() as session:
        document = await session.get(Document, job.document_id)
        if document is None:
            logger.warning("ingestion_document_missing", document_id=str(job.document_id))
            return IngestionOutcome(str(job.document_id), "failed", failure_reason="Deleted")
        knowledge_base = await session.get(KnowledgeBase, document.knowledge_base_id)
        if knowledge_base is None or knowledge_base.organization_id != job.organization_id:
            # A job must never move data across the tenant boundary.
            logger.error("ingestion_tenant_mismatch", document_id=str(job.document_id))
            return IngestionOutcome(str(job.document_id), "failed", failure_reason="Rejected")
        if document.status == "ready":
            return IngestionOutcome(str(document.id), "ready")

        try:
            _transition(document, "validating")
            try:
                data = await object_store.get(job.object_key)
            except ObjectNotFoundError as error:
                raise IngestionError("Stored object is missing or was removed") from error
            validate_object(document, job, data)

            _transition(document, "parsing")
            text = extract_text(document.content_type, data)

            _transition(document, "chunking")
            chunks = chunk_text(text, settings.rag_chunk_max_chars, settings.rag_chunk_overlap)

            _transition(document, "embedding")
            embeddings = await embedder.embed(chunks)

            store = PostgresVectorStore(session)
            await store.delete(document.id)  # re-ingestion replaces any prior index
            await store.upsert(
                [
                    DocumentChunk(
                        id=uuid4(),
                        document_id=document.id,
                        chunk_index=index,
                        content=chunk,
                        embedding=embedding,
                        metadata={
                            "knowledge_base_id": str(document.knowledge_base_id),
                            "organization_id": str(knowledge_base.organization_id),
                            "embedding_model": embedder.name,
                            "source": document.source,
                            **({"license": document.license} if document.license else {}),
                        },
                    )
                    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True))
                ]
            )

            _transition(document, "ready")
            document.failure_reason = None
            await write_audit_log(
                session,
                action="document.ready",
                resource_type="document",
                resource_id=str(document.id),
            )
            await session.commit()
            logger.info("ingestion_complete", document_id=str(document.id), chunks=len(chunks))
            return IngestionOutcome(str(document.id), "ready", chunks=len(chunks))
        except IngestionError as error:
            document.status = "failed"
            document.failure_reason = str(error)
            await write_audit_log(
                session,
                action="document.failed",
                resource_type="document",
                resource_id=str(document.id),
            )
            await session.commit()
            logger.info("ingestion_failed", document_id=str(document.id), reason=str(error))
            return IngestionOutcome(str(document.id), "failed", failure_reason=str(error))
        except Exception:
            document.status = "failed"
            document.failure_reason = "Internal ingestion error"
            await session.commit()
            logger.exception("ingestion_error", document_id=str(document.id))
            return IngestionOutcome(
                str(document.id), "failed", failure_reason="Internal ingestion error"
            )
