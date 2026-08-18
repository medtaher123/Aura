"""Message repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from ..models import Message
from .base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    """Repository for chat messages."""

    model = Message

    async def create_for_conversation(
        self,
        conversation_id: uuid.UUID,
        message: Message,
        *,
        commit: bool = True,
    ) -> Message:
        """Persist an already-constructed message subclass instance."""
        message.conversation_id = conversation_id
        return await self.add(message, commit=commit)

    async def list_for_conversation(self, conversation_id: uuid.UUID) -> list[Message]:
        """Return messages in insertion order."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.asc())
        )
        return await self.list(statement=stmt)
