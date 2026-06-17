"""Message repository."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from ..models import Message
from .base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    """Repository for chat messages and JSONB metadata mapping."""

    model = Message

    async def create_for_conversation(
        self,
        converation_id: uuid.UUID,
        data: Mapping[str, Any],
        *,
        commit: bool = True,
    ) -> Message:
        """Create a message, mapping API ``metadata`` to ORM ``message_metadata``."""
        payload = dict(data)
        metadata = payload.pop("metadata", None)
        payload["conversation_id"] = converation_id
        payload["message_metadata"] = metadata or {}
        return await self.create(payload, commit=commit)

    async def list_for_conversation(self, conversation_id: uuid.UUID) -> list[Message]:
        """Return messages in insertion order."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.asc())
        )
        return await self.list(statement=stmt)
