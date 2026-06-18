"""Chat conversation service."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Message, Conversation, User
from ..repositories import MessageRepository, ConversationRepository


MAX_CONVERSATION_TITLE_LENGTH = 80


@dataclass(frozen=True)
class ConversationWithMessagesResult:
    """Domain result for a conversation and its ordered messages."""

    conversation: Conversation
    messages: list[Message]
    created: bool = False


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

    async def get_or_create_conversation_with_messages(
        self,
        user: User,
        conversation_id: Optional[uuid.UUID],
    ) -> Optional[ConversationWithMessagesResult]:
        """Resolve a chat request to an owner-scoped conversation context."""
        if conversation_id is not None:
            return await self.get_conversation_with_messages(user, conversation_id)

        conversation = await self.create_conversation(user, {})
        return ConversationWithMessagesResult(
            conversation=conversation,
            messages=[],
            created=True,
        )

    async def append_messages(
        self,
        user: User,
        conversation_id: uuid.UUID,
        messages: Sequence[dict],
        *,
        commit: bool = True,
    ) -> bool:
        """Append messages to an owner-scoped conversation."""
        conversation = await self.get_conversation(user, conversation_id)
        if conversation is None:
            return False

        for message in messages:
            await self.messages.create_for_conversation(
                conversation_id,
                message,
                commit=False,
            )

        if commit:
            await self.messages.db.commit()
        return True

    async def update_title(
        self,
        user: User,
        conversation_id: uuid.UUID,
        title: str,
        *,
        commit: bool = True,
    ) -> Optional[Conversation]:
        """Update an owner-scoped conversation title."""
        conversation = await self.get_conversation(user, conversation_id)
        if conversation is None:
            return None
        conversation.title = self._clean_title(title) or "New chat"
        if commit:
            await self.conversations.db.commit()
            await self.conversations.db.refresh(conversation)
        else:
            await self.conversations.db.flush()
        return conversation

    def generate_title(self, user_message: str, assistant_message: str) -> str:
        """Generate a short title from the first conversation turn."""
        from src.services.llm_service import get_chat_llm

        fallback_title = self._fallback_title(user_message)
        prompt = (
            "Generate a concise chat title for this conversation.\n"
            "Rules:\n"
            "- Return only the title, no quotes and no punctuation wrapper.\n"
            "- Maximum 6 words.\n"
            "- Use the user's language if clear.\n\n"
            f"User: {user_message[:2000]}\n\n"
            f"Assistant: {assistant_message[:2000]}\n\n"
            "Title:"
        )

        try:
            llm = get_chat_llm(temperature=0.0, max_tokens=32)
            message = llm.invoke(prompt)
            raw_title = getattr(message, "content", message)
            return self._clean_title(str(raw_title)) or fallback_title
        except Exception:
            return fallback_title

    @classmethod
    def _clean_title(cls, title: str) -> str:
        """Normalize an LLM title into the DB/display constraints."""
        cleaned = " ".join(title.replace("\n", " ").split())
        cleaned = cleaned.strip(" \t\r\n\"'`“”‘’")
        if len(cleaned) > MAX_CONVERSATION_TITLE_LENGTH:
            cleaned = cleaned[:MAX_CONVERSATION_TITLE_LENGTH].rstrip()
        return cleaned

    @classmethod
    def _fallback_title(cls, user_message: str) -> str:
        title = cls._clean_title(user_message)
        if not title:
            return "New chat"
        words = title.split()
        if len(words) > 6:
            title = " ".join(words[:6])
        return cls._clean_title(title) or "New chat"

    @staticmethod
    def _owner_id(user: User) -> str:
        """Concentrate access to the user primary key in one place."""
        return user.id
