"""Transport-neutral ingestion job contract; workers receive object references, never host paths."""
from dataclasses import dataclass
from uuid import UUID

@dataclass(frozen=True)
class IngestionJob:
    document_id: UUID
    organization_id: UUID
    object_key: str
    declared_content_type: str
    source: str
    license: str
