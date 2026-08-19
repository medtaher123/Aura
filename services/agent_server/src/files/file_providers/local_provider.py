"""Local filesystem storage backend."""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.config import get_config

from ..provider import (
    FileStorageError,
    FileStorageProvider,
    InvalidStorageKeyError,
)


class LocalFileStorageProvider(FileStorageProvider):
    """Store file bytes under a configured local directory."""

    name = "local"

    def __init__(self, root: str | Path | None = None) -> None:
        config = get_config()
        configured = Path(root if root is not None else config.file_storage_local_root)
        self._root = configured.expanduser()
        if not self._root.is_absolute():
            self._root = Path.cwd() / self._root
        self._root = self._root.resolve()

    def _resolve_key(self, key: str) -> Path:
        if not key or not key.strip():
            raise InvalidStorageKeyError("Storage key is empty")
        candidate = Path(key)
        if candidate.is_absolute() or key.startswith("/") or key.startswith("\\"):
            raise InvalidStorageKeyError("Storage key must be a relative path")
        if ".." in candidate.parts:
            raise InvalidStorageKeyError("Storage key must not contain '..'")
        full = (self._root / candidate).resolve()
        try:
            full.relative_to(self._root)
        except ValueError as exc:
            raise InvalidStorageKeyError("Storage key escapes the local root") from exc
        return full

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        path = self._resolve_key(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        path = self._resolve_key(key)

        def _read() -> bytes:
            if not path.is_file():
                raise FileStorageError("Stored file was not found on disk")
            return path.read_bytes()

        return await asyncio.to_thread(_read)

    async def delete(self, key: str) -> None:
        path = self._resolve_key(key)

        def _unlink() -> None:
            if path.is_file():
                path.unlink()

        await asyncio.to_thread(_unlink)

    async def exists(self, key: str) -> bool:
        path = self._resolve_key(key)
        return await asyncio.to_thread(path.is_file)
