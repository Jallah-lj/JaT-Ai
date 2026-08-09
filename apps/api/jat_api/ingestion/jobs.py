"""Transport-neutral ingestion job contract; workers receive object references, never host paths."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class IngestionJob:
    document_id: UUID
    organization_id: UUID
    object_key: str
    declared_content_type: str
    source: str
    license: str


def job_to_payload(job: IngestionJob) -> dict[str, str]:
    """Serialize a job for queue transport. Only safe, typed fields cross the boundary."""
    return {
        "document_id": str(job.document_id),
        "organization_id": str(job.organization_id),
        "object_key": job.object_key,
        "declared_content_type": job.declared_content_type,
        "source": job.source,
        "license": job.license,
    }


def job_from_json(payload: str) -> IngestionJob:
    """Deserialize and validate a queued job; rejects malformed payloads loudly."""
    return job_from_payload(json.loads(payload))


def job_from_payload(payload: Any) -> IngestionJob:
    """Validate a decoded queue payload into a typed job."""
    if not isinstance(payload, dict):
        raise ValueError("Ingestion job payload must be an object")
    try:
        return IngestionJob(
            document_id=UUID(str(payload["document_id"])),
            organization_id=UUID(str(payload["organization_id"])),
            object_key=str(payload["object_key"]),
            declared_content_type=str(payload["declared_content_type"]),
            source=str(payload["source"]),
            license=str(payload["license"]),
        )
    except KeyError as error:
        raise ValueError(f"Ingestion job payload missing field: {error}") from error
