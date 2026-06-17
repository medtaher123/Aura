"""Schemas for chat conversation and message endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.db.models import User

if TYPE_CHECKING:
    from ..db.models import Message, Conversation
    from ..db.services import ConversationWithMessagesResult


class UserRead(BaseModel):
    """A user as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: Optional[str] = None
    created_at: datetime

    @classmethod
    def from_model(cls, user: "User") -> "UserRead":
        """Map an ORM user to the public API schema."""
        return cls(
            id=user.id,
            email=user.email,
            created_at=user.created_at,
        )
    

class ConversationCreate(BaseModel):
    """Payload to create a new chat conversation."""

    title: str | None = Field(default=None, max_length=255)


class ConversationRead(BaseModel):
    """A chat conversation as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: str
    title: str
    created_at: datetime

    @classmethod
    def from_model(cls, conversation: "Conversation") -> "ConversationRead":
        """Map an ORM conversation to the public API schema."""
        return cls(
            id=conversation.id,
            user_id=conversation.user_id,
            title=conversation.title,
            created_at=conversation.created_at,
        )


class MessageCreate(BaseModel):
    """Payload to persist a chat message.

    ``metadata`` accepts arbitrary nested JSON (e.g. tool outputs) and is stored
    in a JSONB column.
    """

    role: str = Field(..., max_length=32)
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageRead(BaseModel):
    """A chat message as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: uuid.UUID
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime

    @classmethod
    def from_model(cls, message: "Message") -> "MessageRead":
        """Map ORM message attributes to the public API schema."""
        return cls(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            metadata=message.message_metadata,
            timestamp=message.timestamp,
        )


class ConversationWithMessages(ConversationRead):
    """A chat conversation including its messages."""

    messages: list[MessageRead] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, result: "ConversationWithMessagesResult") -> "ConversationWithMessages":
        """Build a response from a service-layer domain result."""
        conversation = result.conversation
        return cls(
            id=conversation.id,
            user_id=conversation.user_id,
            title=conversation.title,
            created_at=conversation.created_at,
            messages=[MessageRead.from_model(message) for message in result.messages],
        )
