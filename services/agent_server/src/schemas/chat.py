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
    username: Optional[str] = None
    created_at: datetime

    @classmethod
    def from_model(cls, user: "User") -> "UserRead":
        """Map an ORM user to the public API schema."""
        return cls(
            id=user.id,
            username=user.username,
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



class ConversationMessage(BaseModel):
    """API / UI view of a persisted conversation message.

    Built by ``Message.to_frontend()``. Use ``to_dict()`` when a plain dict is
    required; FastAPI can also serialize this model directly.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    conversation_id: uuid.UUID | None = None
    role: str
    kind: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    needs_input: dict[str, Any] | None = None
    visible_to_ui: bool = True
    visible_to_agent: bool = True

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict for HTTP responses and clients."""
        return self.model_dump(mode="json")



class ConversationWithMessages(ConversationRead):
    """A chat conversation including its messages."""

    messages: list[ConversationMessage] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, result: "ConversationWithMessagesResult") -> "ConversationWithMessages":
        """Build a response from a service-layer domain result."""
        conversation = result.conversation
        return cls(
            id=conversation.id,
            user_id=conversation.user_id,
            title=conversation.title,
            created_at=conversation.created_at,
            messages=[message.to_frontend() for message in result.messages],
        )
