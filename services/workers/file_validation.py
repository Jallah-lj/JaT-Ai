"""Metadata validation before parser workers consume untrusted objects."""
ALLOWED_TYPES = {"text/plain", "text/markdown", "application/pdf", "application/json", "text/csv"}
MAX_BYTES = 25 * 1024 * 1024

def validate_upload_metadata(content_type: str, size: int) -> None:
    if content_type not in ALLOWED_TYPES: raise ValueError("Unsupported content type")
    if not 0 < size <= MAX_BYTES: raise ValueError("Invalid upload size")
