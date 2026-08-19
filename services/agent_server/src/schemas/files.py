"""Schemas for stored-file HTTP endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from src.db.models.file import File


class FileRead(BaseModel):
    """Public metadata for a stored file."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: str
    conversation_id: Optional[uuid.UUID] = None
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    storage_provider: str
    created_at: datetime

    @classmethod
    def from_model(cls, stored: "File") -> "FileRead":
        """Map an ORM file row to the public API schema."""
        return cls(
            id=stored.id,
            user_id=stored.user_id,
            conversation_id=stored.conversation_id,
            original_filename=stored.original_filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            storage_provider=stored.storage_provider,
            created_at=stored.created_at,
        )
