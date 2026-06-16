"""Chat session repository."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Optional

from sqlalchemy import select

from ..models import Session
from .base import BaseRepository


class SessionRepository(BaseRepository[Session]):
    """Repository for owner-scoped chat sessions."""

    model = Session

    async def create_for_owner(
        self,
        owner_id: str,
        data: Mapping[str, Any],
        *,
        commit: bool = True,
    ) -> Session:
        """Create a session for a user without leaking ORM field names upward."""
        payload = dict(data)
        payload["user_id"] = owner_id
        payload["title"] = payload.get("title") or "New chat"
        return await self.create(payload, commit=commit)

    async def list_for_owner(self, owner_id: str) -> list[Session]:
        """Return sessions owned by ``owner_id``, newest first."""
        stmt = (
            select(Session)
            .where(Session.user_id == owner_id)
            .order_by(Session.created_at.desc())
        )
        return await self.list(statement=stmt)

    async def get_for_owner(
        self,
        session_id: uuid.UUID,
        owner_id: str,
    ) -> Optional[Session]:
        """Fetch one session while enforcing ownership."""
        stmt = select(Session).where(
            Session.id == session_id,
            Session.user_id == owner_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
