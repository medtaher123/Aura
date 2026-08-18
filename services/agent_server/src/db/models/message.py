"""Message ORM model and typed conversation message subclasses.

``role`` is the LLM speaker (``user`` | ``assistant`` | ``system``).
``kind`` is the product message type and the STI discriminator.

Free-text lives in ``content``; structured extras live in ``attachments``.
The LLM provider turns attachments into vendor content blocks.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, ClassVar, TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func, JSON, Uuid
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel
from .message_attachments import (
    MessageAttachment,
    dump_attachments,
    parse_attachments,
)

if TYPE_CHECKING:
    from src.db.models.conversation import Conversation
    from src.schemas.chat import ConversationMessage


class MessageRole(str, enum.Enum):
    """Speaker role consumed by LLM providers."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageKind(str, enum.Enum):
    """Product message type (also the SQLAlchemy STI discriminator)."""

    USER_TEXT = "user_text"
    ASSISTANT_TEXT = "assistant_text"
    SYSTEM = "system"
    INPUT_REQUEST = "input_request"
    INPUT_RESPONSE = "input_response"


class Message(BaseModel):
    """A single message within a chat conversation.

    Subclasses are selected by ``kind``. ``role`` is always a valid LLM speaker.
    """

    __tablename__ = "messages"
    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_on": "kind",
        "polymorphic_identity": "message",
    }

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True).with_variant(PGUUID(as_uuid=True), "postgresql"),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    role: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    message_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
        server_default="{}",
    )

    _attachments: Mapped[list[Any]] = mapped_column(
        "attachments",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
        server_default="[]",
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    @property
    def attachments(self) -> list[MessageAttachment]:
        return parse_attachments(self._attachments)

    @attachments.setter
    def attachments(self, value: list[MessageAttachment] | None) -> None:
        self._attachments = dump_attachments(value)


    @property
    def has_content(self) -> bool:
        return bool(self.content.strip() or self.attachments)

    def to_frontend(self) -> "ConversationMessage":
        """API / UI view of this persisted message."""
        from src.schemas.chat import ConversationMessage

        return ConversationMessage(
            id=self.id,
            conversation_id=self.conversation_id,
            role=self.role,
            kind=self.kind,
            content=self.content or "",
            metadata=dict(self.message_metadata or {}),
            timestamp=self.timestamp,
            attachments=dump_attachments(self.attachments),
        )


class UserMessage(Message):
    """Normal user free-text turn (optionally with attachments)."""

    __mapper_args__ = {"polymorphic_identity": MessageKind.USER_TEXT.value}

    @classmethod
    def create(
        cls,
        content: str = "",
        *,
        attachments: list[MessageAttachment] | None = None,
    ) -> UserMessage:
        return cls(
            role=MessageRole.USER.value,
            kind=MessageKind.USER_TEXT.value,
            content=content or "",
            message_metadata={},
            _attachments=dump_attachments(attachments),
        )


class AssistantMessage(Message):
    """Normal assistant reply."""

    __mapper_args__ = {"polymorphic_identity": MessageKind.ASSISTANT_TEXT.value}

    @classmethod
    def create(
        cls,
        content: str = "",
        *,
        metadata: dict[str, Any] | None = None,
    ) -> AssistantMessage:
        return cls(
            role=MessageRole.ASSISTANT.value,
            kind=MessageKind.ASSISTANT_TEXT.value,
            content=content or "",
            message_metadata=dict(metadata or {}),
        )


class InputRequestMessage(Message):
    """Assistant-side pause asking the user for one or more inputs."""

    __mapper_args__ = {"polymorphic_identity": MessageKind.INPUT_REQUEST.value}

    @classmethod
    def create(
        cls,
        content: str = "",
        *,
        needs_input: dict[str, Any] | None = None,
    ) -> InputRequestMessage:
        return cls(
            role=MessageRole.ASSISTANT.value,
            kind=MessageKind.INPUT_REQUEST.value,
            content=content or "",
            message_metadata={"needs_input": dict(needs_input or {})},
        )

    @property
    def needs_input(self) -> dict[str, Any]:
        return dict((self.message_metadata or {}).get("needs_input") or {})

    def to_frontend(self) -> "ConversationMessage":
        from src.schemas.chat import ConversationMessage

        return ConversationMessage(
            id=self.id,
            conversation_id=self.conversation_id,
            role=self.role,
            kind=self.kind,
            content=self.content or "",
            metadata=dict(self.message_metadata or {}),
            timestamp=self.timestamp,
            attachments=dump_attachments(self.attachments),
            needs_input=self.needs_input,
        )


class InputResponseMessage(Message):
    """User-side answer covering the requested input kinds."""

    __mapper_args__ = {"polymorphic_identity": MessageKind.INPUT_RESPONSE.value}

    @classmethod
    def create(
        cls,
        content: str = "",
        *,
        attachments: list[MessageAttachment] | None = None,
    ) -> InputResponseMessage:
        return cls(
            role=MessageRole.USER.value,
            kind=MessageKind.INPUT_RESPONSE.value,
            content=content or "",
            message_metadata={},
            _attachments=dump_attachments(attachments),
        )
