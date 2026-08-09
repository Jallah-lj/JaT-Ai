"""Turn quarantined object bytes into text for supported content types.

Extracted text is untrusted reference data. It must never be concatenated into
privileged instruction channels; chat orchestration wraps it in an explicitly
delimited untrusted block.
"""

from jat_api.ingestion.policy import PARSEABLE_TYPES


class IngestionError(Exception):
    """An expected, user-comprehensible ingestion failure (recorded on the document)."""


def extract_text(content_type: str | None, data: bytes) -> str:
    """Extract text from a validated object or raise :class:`IngestionError`."""
    if content_type not in PARSEABLE_TYPES:
        raise IngestionError(
            f"Parsing for content type {content_type or 'unknown'} is not enabled yet"
        )
    # Guard against mislabeled binary payloads before trusting the decode.
    sample = data[:8192]
    if sample and data[:1024].count(b"\x00") > len(data[:1024]) // 100:
        raise IngestionError("Object bytes do not look like text")
    text = data.decode("utf-8", errors="replace").lstrip("\ufeff")
    if not text.strip():
        raise IngestionError("Document contains no extractable text")
    return text
