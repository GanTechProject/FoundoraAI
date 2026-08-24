from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Protocol

from foundora.config import get_settings


class KnowledgeStorageError(RuntimeError):
    pass


class KnowledgeStorage(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...

    async def delete(self, key: str) -> None: ...


class LocalKnowledgeStorage:
    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root or get_settings().knowledge_storage_path).resolve()

    def _path(self, key: str) -> Path:
        candidate = (self._root / key).resolve()
        if self._root not in candidate.parents:
            raise KnowledgeStorageError("The storage key is outside the configured root")
        return candidate

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def write() -> None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(f"{path.suffix}.tmp")
                temporary.write_bytes(data)
                os.replace(temporary, path)
            except OSError as error:
                raise KnowledgeStorageError("The uploaded file could not be stored") from error

        await asyncio.to_thread(write)

    async def delete(self, key: str) -> None:
        path = self._path(key)

        def remove() -> None:
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                raise KnowledgeStorageError("The stored file could not be removed") from error

        await asyncio.to_thread(remove)


def get_knowledge_storage() -> KnowledgeStorage:
    settings = get_settings()
    if settings.knowledge_storage_backend == "local":
        return LocalKnowledgeStorage(settings.knowledge_storage_path)
    raise KnowledgeStorageError("The configured knowledge storage backend is unavailable")
