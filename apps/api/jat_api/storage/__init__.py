"""Object-storage boundary for quarantined document content."""

from jat_api.storage.contracts import ObjectNotFoundError, ObjectStore, ObjectStoreKeyError
from jat_api.storage.local import LocalObjectStore

__all__ = [
    "LocalObjectStore",
    "ObjectNotFoundError",
    "ObjectStore",
    "ObjectStoreKeyError",
]
