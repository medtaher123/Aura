"""Stored file repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Optional

from sqlalchemy import select

from ..models import File
from .base import BaseRepository


class FileRepository(BaseRepository[File]):
    """Repository for owner-scoped stored files."""

    model = File

    async def get_for_owner(
        self,
        file_id: uuid.UUID,
        owner_id: str,
    ) -> Optional[File]:
        """Fetch one file while enforcing ownership."""
        stmt = select(File).where(File.id == file_id, File.user_id == owner_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_owner(
        self,
        file_ids: Sequence[uuid.UUID],
        owner_id: str,
    ) -> list[File]:
        """Fetch the owner's files matching ``file_ids`` (order is undefined)."""
        if not file_ids:
            return []
        stmt = select(File).where(File.id.in_(file_ids), File.user_id == owner_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
