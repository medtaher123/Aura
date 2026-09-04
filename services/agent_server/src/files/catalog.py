"""Lazy owner-scoped lookup for stored file metadata and bytes."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import AsyncSessionLocal
from src.db.models.file import File
from src.db.models.message_attachments import FileAttachment
from src.db.repositories.files import FileRepository
from src.files.router import FileStorageRouter

if TYPE_CHECKING:
    from src.db.models.message import Message

logger = logging.getLogger("src.files.catalog")


class FileCatalog:
    """Load ``files`` rows and bytes on demand, caching each id once per turn."""

    def __init__(self, user_id: str, db: AsyncSession | None = None) -> None:
        self._user_id = user_id
        self._db = db
        self._records: dict[UUID, File | None] = {}
        self._bytes: dict[UUID, bytes | None] = {}

    async def get_record(self, file_id: UUID) -> File | None:
        if file_id not in self._records:
            self._records[file_id] = await self._fetch_record(file_id)
        return self._records[file_id]

    async def read_bytes(self, file_id: UUID) -> bytes | None:
        if file_id in self._bytes:
            return self._bytes[file_id]
        record = await self.get_record(file_id)
        if record is None:
            self._bytes[file_id] = None
            return None
        try:
            payload = await FileStorageRouter.get_provider().get(record.storage_key)
        except Exception:
            logger.warning("Failed to read stored bytes for file %s", file_id, exc_info=True)
            payload = None
        self._bytes[file_id] = payload
        return payload

    async def _fetch_record(self, file_id: UUID) -> File | None:
        if self._db is not None:
            return await FileRepository(self._db).get_for_owner(file_id, self._user_id)
        async with AsyncSessionLocal() as session:
            return await FileRepository(session).get_for_owner(file_id, self._user_id)

    @staticmethod
    def file_ids_from_messages(messages: Sequence["Message"]) -> list[UUID]:
        seen: list[UUID] = []
        found: set[UUID] = set()
        for message in messages:
            for attachment in message.attachments:
                if not isinstance(attachment, FileAttachment):
                    continue
                if attachment.file_id in found:
                    continue
                found.add(attachment.file_id)
                seen.append(attachment.file_id)
        return seen
