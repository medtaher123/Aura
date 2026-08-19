"""Stored file service: metadata in the DB, bytes in FileStorageProvider."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_config
from src.files.router import FileStorageRouter

from ..models import File, User
from ..repositories import FileRepository
from .conversations import ConversationService


class FileTooLargeError(ValueError):
    """Raised when uploaded bytes exceed ``file_max_bytes``."""


class EmptyFileError(ValueError):
    """Raised when an upload contains no bytes."""


_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class FileService:
    """Owner-scoped file metadata and byte storage."""

    def __init__(self, db: AsyncSession):
        self.files = FileRepository(db)
        self.conversations = ConversationService(db)

    async def save(
        self,
        user: User,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        conversation_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> File:
        """Store bytes in the active backend and insert a ``files`` row."""
        if not data:
            raise EmptyFileError("Uploaded file is empty")
        max_bytes = get_config().file_max_bytes
        if len(data) > max_bytes:
            raise FileTooLargeError(
                f"Uploaded file exceeds the maximum size of {max_bytes} bytes"
            )
        if conversation_id is not None:
            conversation = await self.conversations.get_conversation(
                user, conversation_id
            )
            if conversation is None:
                raise LookupError("Conversation not found")

        provider = FileStorageRouter.get_provider()
        file_id = uuid.uuid4()
        original_filename = self._display_filename(filename)
        storage_key = provider.build_key(
            user.id, str(file_id), self._storage_filename(original_filename)
        )
        await provider.put(storage_key, data, content_type=content_type)
        record = File(
            id=file_id,
            user_id=user.id,
            conversation_id=conversation_id,
            original_filename=original_filename,
            content_type=content_type or "application/octet-stream",
            size_bytes=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            storage_provider=provider.name,
            storage_key=storage_key,
        )
        try:
            return await self.files.add(record, commit=commit)
        except Exception:
            await provider.delete(storage_key)
            raise

    async def get_for_user(self, user: User, file_id: uuid.UUID) -> Optional[File]:
        """Return a file owned by ``user``, or ``None``."""
        return await self.files.get_for_owner(file_id, user.id)

    async def read_bytes(self, user: User, file_id: uuid.UUID) -> Optional[bytes]:
        """Load stored bytes for an owner-scoped file."""
        record = await self.get_for_user(user, file_id)
        if record is None:
            return None
        return await FileStorageRouter.get_provider().get(record.storage_key)

    async def delete(self, user: User, file_id: uuid.UUID) -> bool:
        """Remove the object and the metadata row. Returns False if not found."""
        record = await self.get_for_user(user, file_id)
        if record is None:
            return False
        await FileStorageRouter.get_provider().delete(record.storage_key)
        await self.files.delete(record)
        return True

    @staticmethod
    def _display_filename(filename: str) -> str:
        name = Path(filename or "").name.strip() or "file"
        return name[:255]

    @staticmethod
    def _storage_filename(filename: str) -> str:
        cleaned = _UNSAFE_FILENAME.sub("_", filename).strip("._") or "file"
        return cleaned[:255]
