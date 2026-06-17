"""Chat conversation service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Message, Conversation, User
from ..repositories import MessageRepository, ConversationRepository


@dataclass(frozen=True)
class ConversationWithMessagesResult:
    """Domain result for a conversation and its ordered messages."""

    conversation: Conversation
    messages: list[Message]


class ConversationService:
    """Business operations for chat conversations."""

    def __init__(self, db: AsyncSession):
        self.conversations = ConversationRepository(db)
        self.messages = MessageRepository(db)

    async def create_conversation(
        self,
        user: User,
        data: dict,
        *,
        commit: bool = True,
    ) -> Conversation:
        return await self.conversations.create_for_owner(
            self._owner_id(user), data, commit=commit
        )

    async def list_conversations(self, user: User) -> list[Conversation]:
        return await self.conversations.list_for_owner(self._owner_id(user))

    async def get_conversation(
        self,
        user: User,
        conversation_id: uuid.UUID,
    ) -> Optional[Conversation]:
        return await self.conversations.get_for_owner(conversation_id, self._owner_id(user))

    async def get_conversation_with_messages(
        self,
        user: User,
        conversation_id: uuid.UUID,
    ) -> Optional[ConversationWithMessagesResult]:
        conversation = await self.get_conversation(user, conversation_id)
        if conversation is None:
            return None
        messages = await self.messages.list_for_conversation(conversation_id)
        return ConversationWithMessagesResult(conversation=conversation, messages=messages)

    @staticmethod
    def _owner_id(user: User) -> str:
        """Concentrate access to the user primary key in one place."""
        return user.id
