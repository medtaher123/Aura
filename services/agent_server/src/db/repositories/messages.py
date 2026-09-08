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

    async def list_for_conversation(
        self,
        conversation_id: uuid.UUID,
        *,
        visible_to_ui: bool | None = True,
        visible_to_agent: bool | None = None,
    ) -> list[Message]:
        """Return messages in insertion order.

        ``visible_to_ui=True`` (default) returns only UI-visible rows.
        ``visible_to_agent=True`` returns only agent/LLM-visible rows.
        Pass ``None`` for either filter to leave that dimension unrestricted.
        """
        stmt = select(Message).where(Message.conversation_id == conversation_id)
        if visible_to_ui is not None:
            stmt = stmt.where(Message.visible_to_ui.is_(visible_to_ui))
        if visible_to_agent is not None:
            stmt = stmt.where(Message.visible_to_agent.is_(visible_to_agent))
        stmt = stmt.order_by(Message.id.asc())
        return await self.list(statement=stmt)
