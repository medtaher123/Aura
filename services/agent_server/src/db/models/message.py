"""Message ORM model and typed conversation message subclasses."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar, TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func, JSON, Uuid
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

if TYPE_CHECKING:
    from src.db.models.conversation import Conversation


class Message(BaseModel):
    """A single message within a chat conversation.

    Subclasses are selected by ``role`` (SQLAlchemy single-table inheritance)
    and know how to render themselves for the LLM and the frontend.
    """

    __tablename__ = "messages"
    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_on": "role",
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
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    message_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
        server_default="{}",
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    def to_llm_dict(self) -> dict[str, str]:
        """``{role, content}`` shape consumed by LLM / memory formatting."""
        return {"role": self.role, "content": self.content or ""}

    def to_frontend_dict(self) -> dict[str, Any]:
        """Shape sent to UI clients (includes ``message_type``)."""
        meta = dict(self.message_metadata or {})
        return {
            "message_type": meta.get("message_type") or self.role,
            "role": self.role,
            "content": self.content or "",
            "metadata": meta,
        }


class UserMessage(Message):
    """Message authored by the end user."""

    __mapper_args__ = {"polymorphic_identity": "user"}

    @classmethod
    def create(
        cls,
        content: str = "",
        *,
        user_inputs: dict[str, Any] | None = None,
    ) -> UserMessage:
        meta: dict[str, Any] = {"message_type": "user"}
        if user_inputs:
            meta["user_inputs"] = dict(user_inputs)
        return cls(
            content=content or "",
            message_metadata=meta,
        )

    @property
    def user_inputs(self) -> dict[str, Any]:
        return dict((self.message_metadata or {}).get("user_inputs") or {})

    def to_llm_dict(self) -> dict[str, str]:
        """Include attached user inputs in the content the LLM sees."""
        content = self.content or ""
        inputs = self.user_inputs
        if inputs:
            from src.schemas.user_inputs import UserInputRouter

            suffix = UserInputRouter.results_llm_text(inputs)
            if suffix and suffix not in content:
                content = UserInputRouter.append_user_inputs_text(content, inputs)
        return {"role": "user", "content": content}

class AssistantMessage(Message):
    """Message authored by the assistant."""

    __mapper_args__ = {"polymorphic_identity": "assistant"}

    @classmethod
    def create(
        cls,
        content: str = "",
        *,
        metadata: dict[str, Any] | None = None,
    ) -> AssistantMessage:
        meta = dict(metadata or {})
        meta["message_type"] = "assistant"
        return cls(content=content or "", message_metadata=meta)


class InputRequestMessage(Message):
    """Assistant-side pause asking the user for one or more inputs."""

    __mapper_args__ = {"polymorphic_identity": "input_request"}

    @classmethod
    def create(
        cls,
        content: str = "",
        *,
        needs_input: dict[str, Any] | None = None,
    ) -> InputRequestMessage:
        return cls(
            content=content or "",
            message_metadata={
                "message_type": "input_request",
                "needs_input": dict(needs_input or {}),
            },
        )

    @property
    def needs_input(self) -> dict[str, Any]:
        return dict((self.message_metadata or {}).get("needs_input") or {})

    def to_llm_dict(self) -> dict[str, str]:
        return {"role": "assistant", "content": self.content or ""}

    def to_frontend_dict(self) -> dict[str, Any]:
        return {
            "message_type": "input_request",
            "role": "input_request",
            "content": self.content or "",
            "needs_input": self.needs_input,
        }


class InputResponseMessage(Message):
    """User-side answer covering the requested input kinds."""

    __mapper_args__ = {"polymorphic_identity": "input_response"}

    @classmethod
    def create(
        cls,
        content: str = "",
        *,
        user_inputs: dict[str, Any] | None = None,
    ) -> InputResponseMessage:
        return cls(
            content=content or "",
            message_metadata={
                "message_type": "input_response",
                "user_inputs": dict(user_inputs or {}),
            },
        )

    @property
    def user_inputs(self) -> dict[str, Any]:
        return dict((self.message_metadata or {}).get("user_inputs") or {})

    def to_llm_dict(self) -> dict[str, str]:
        return {"role": "user", "content": self.content or ""}

    def to_frontend_dict(self) -> dict[str, Any]:
        return {
            "message_type": "input_response",
            "role": "input_response",
            "content": self.content or "",
            "user_inputs": self.user_inputs,
        }
