"""File storage provider contracts."""

from abc import ABC, abstractmethod


class FileStorageError(Exception):
    """Raised when a storage backend cannot complete an operation."""

    def __init__(self, message: str = "File storage operation failed"):
        super().__init__(message)
        self.message = message


class FileStorageConfigurationError(RuntimeError):
    """Raised when a file storage provider is selected but not configured."""


class InvalidStorageKeyError(FileStorageError):
    """Raised when a storage key is absolute, empty, or escapes the root."""


class FileStorageProvider(ABC):
    """Base class for pluggable file-byte backends."""

    name: str = NotImplemented

    def build_key(self, *parts: str) -> str:
        """Join path parts into a provider storage key."""
        chunks = [part.strip("/") for part in parts if part and part.strip("/")]
        return "/".join(chunks)

    @abstractmethod
    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        """Write bytes at ``key``, replacing any existing object."""

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Return the bytes stored at ``key``."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove ``key`` if it exists; missing keys are not an error."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return whether ``key`` is present in this backend."""
