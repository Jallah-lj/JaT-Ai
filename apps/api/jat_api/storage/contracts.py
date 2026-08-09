"""Quarantined object storage contract.

Uploaded objects are written under caller-generated namespaced keys and are only
ever read back for governed worker processing. The API never exposes object
contents directly to clients; browsers receive metadata, not bytes.
"""

from __future__ import annotations

from typing import Protocol


class ObjectStoreKeyError(ValueError):
    """A key is malformed or escapes its namespace."""


class ObjectNotFoundError(KeyError):
    """The requested object does not exist in the store."""


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
