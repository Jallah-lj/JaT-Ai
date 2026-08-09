"""Governed document ingestion: policy, dispatch, parsing, chunking, and pipeline.

This package is the current runtime home of the ingestion contracts that previously
lived under ``services/workers``. The worker entry point is
``python -m jat_api.ingestion.worker``; the standalone worker service documented in
``services/workers`` becomes relevant again when background work is split into its
own deployment unit.
"""

from jat_api.ingestion.chunking import chunk_text
from jat_api.ingestion.dispatch import (
    IngestionDispatcher,
    InlineIngestionDispatcher,
    LocalIngestionDispatcher,
    RedisIngestionDispatcher,
)
from jat_api.ingestion.extraction import IngestionError, extract_text
from jat_api.ingestion.jobs import IngestionJob, job_from_payload, job_to_payload
from jat_api.ingestion.pipeline import IngestionOutcome, process_ingestion_job
from jat_api.ingestion.policy import (
    ALLOWED_TYPES,
    MAX_BYTES,
    PARSEABLE_TYPES,
    validate_upload_metadata,
)
from jat_api.ingestion.transitions import can_transition

__all__ = [
    "ALLOWED_TYPES",
    "MAX_BYTES",
    "PARSEABLE_TYPES",
    "IngestionDispatcher",
    "IngestionError",
    "IngestionJob",
    "IngestionOutcome",
    "InlineIngestionDispatcher",
    "LocalIngestionDispatcher",
    "RedisIngestionDispatcher",
    "can_transition",
    "chunk_text",
    "extract_text",
    "job_from_payload",
    "job_to_payload",
    "process_ingestion_job",
    "validate_upload_metadata",
]
