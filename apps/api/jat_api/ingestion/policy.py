"""Metadata validation before parser workers consume untrusted objects."""

ALLOWED_TYPES = {"text/plain", "text/markdown", "application/pdf", "application/json", "text/csv"}

# Content types the current parsing milestone can turn into text safely.
# PDF/JSON/CSV parsing is a later milestone and fails ingestion explicitly.
PARSEABLE_TYPES = {"text/plain", "text/markdown"}

MAX_BYTES = 25 * 1024 * 1024

# Hard cap on chunks per document so a hostile or pathological document cannot
# exhaust embedding or storage budgets.
MAX_CHUNKS = 200


def validate_upload_metadata(content_type: str, size: int) -> None:
    if content_type not in ALLOWED_TYPES:
        raise ValueError("Unsupported content type")
    if not 0 < size <= MAX_BYTES:
        raise ValueError("Invalid upload size")
