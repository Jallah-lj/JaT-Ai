"""Finite state transitions for governed document ingestion."""

ALLOWED = {
    "pending": {"validating", "failed"},
    "validating": {"parsing", "failed"},
    "parsing": {"chunking", "failed"},
    "chunking": {"embedding", "failed"},
    "embedding": {"ready", "failed"},
    "ready": set(),
    "failed": set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED.get(current, set())
