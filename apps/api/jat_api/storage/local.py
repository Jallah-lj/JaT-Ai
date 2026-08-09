"""Local filesystem object store for development and tests.

Production deployments replace this with an S3-compatible adapter; the key
contract and quarantine semantics stay identical.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING

from jat_api.storage.contracts import ObjectNotFoundError, ObjectStoreKeyError

if TYPE_CHECKING:
    from jat_api.config import Settings

_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_\-.]{0,511}$")


def validate_key(key: str) -> None:
    if not _KEY_PATTERN.match(key) or ".." in key.split("/") or key.startswith("/"):
        raise ObjectStoreKeyError("Invalid object key")


class LocalObjectStore:
    """Stores objects below a root directory with path-escape protection."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_settings(cls, settings: Settings) -> LocalObjectStore:
        return cls(settings.object_store_dir)

    def _resolve(self, key: str) -> Path:
        validate_key(key)
        candidate = (self.root / key).resolve()
        if self.root.resolve() not in candidate.parents:
            raise ObjectStoreKeyError("Invalid object key")
        return candidate

    async def put(self, key: str, data: bytes) -> None:
        path = self._resolve(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{path.name}.tmp")
            temporary.write_bytes(data)
            temporary.replace(path)  # atomic rename; never a torn object

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as error:
            raise ObjectNotFoundError(key) from error

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            return
