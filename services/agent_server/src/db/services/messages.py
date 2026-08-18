"""Message service."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.services.conversations import ConversationService

from ..models import Message, User
from ..repositories import MessageRepository


class MessageService:
    """Business operations for messages."""

    def __init__(self, db: AsyncSession):
        self.messages = MessageRepository(db)
        self.conversations = ConversationService(db)

    async def list_messages(
        self,
        user: User,
        conversation_id: uuid.UUID,
    ) -> Optional[list[Message]]:
        """List messages if the conversation belongs to ``user``."""
        conversation = await self.conversations.get_conversation(user, conversation_id)
        if conversation is None:
            return None
        return await self.messages.list_for_conversation(conversation_id)
