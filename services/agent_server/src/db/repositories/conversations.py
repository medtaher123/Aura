"""Chat conversation repository."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Optional

from sqlalchemy import select

from ..models import Conversation
from .base import BaseRepository


class ConversationRepository(BaseRepository[Conversation]):
    """Repository for owner-scoped chat conversations."""

    model = Conversation

    async def create_for_owner(
        self,
        owner_id: str,
        data: Mapping[str, Any],
        *,
        commit: bool = True,
    ) -> Conversation:
        """Create a conversation for a user without leaking ORM field names upward."""
        payload = dict(data)
        payload["user_id"] = owner_id
        payload["title"] = payload.get("title") or "New chat"
        return await self.create(payload, commit=commit)

    async def list_for_owner(self, owner_id: str) -> list[Conversation]:
        """Return conversations owned by ``owner_id``, newest first."""
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == owner_id)
            .order_by(Conversation.created_at.desc())
        )
        return await self.list(statement=stmt)

    async def get_for_owner(
        self,
        conversation_id: uuid.UUID,
        owner_id: str,
    ) -> Optional[Conversation]:
        """Fetch one conversation while enforcing ownership."""
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == owner_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
