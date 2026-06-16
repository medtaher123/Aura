"""Schemas for chat session and message endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.db.models import User

if TYPE_CHECKING:
    from ..db.models import Message, Session
    from ..db.services import SessionWithMessagesResult


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
    

class SessionCreate(BaseModel):
    """Payload to create a new chat session."""

    title: str | None = Field(default=None, max_length=255)


class SessionRead(BaseModel):
    """A chat session as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: str
    title: str
    created_at: datetime

    @classmethod
    def from_model(cls, session: "Session") -> "SessionRead":
        """Map an ORM session to the public API schema."""
        return cls(
            id=session.id,
            user_id=session.user_id,
            title=session.title,
            created_at=session.created_at,
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
    session_id: uuid.UUID
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime

    @classmethod
    def from_model(cls, message: "Message") -> "MessageRead":
        """Map ORM message attributes to the public API schema."""
        return cls(
            id=message.id,
            session_id=message.session_id,
            role=message.role,
            content=message.content,
            metadata=message.message_metadata,
            timestamp=message.timestamp,
        )


class SessionWithMessages(SessionRead):
    """A chat session including its messages."""

    messages: list[MessageRead] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, result: "SessionWithMessagesResult") -> "SessionWithMessages":
        """Build a response from a service-layer domain result."""
        session = result.session
        return cls(
            id=session.id,
            user_id=session.user_id,
            title=session.title,
            created_at=session.created_at,
            messages=[MessageRead.from_model(message) for message in result.messages],
        )
