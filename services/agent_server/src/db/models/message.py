"""Message ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func, JSON, Uuid
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

if TYPE_CHECKING:
    from src.db.models.conversation import Conversation


class Message(BaseModel):
    """A single message within a chat conversation."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), 
        primary_key=True, 
        autoincrement=True
    )    
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True).with_variant(PGUUID(as_uuid=True), "postgresql"),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    
    # 4. UPDATED: Fall back to generic JSON for SQLite, use JSONB for PostgreSQL
    message_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", 
        JSON().with_variant(JSONB(), "postgresql"), 
        nullable=False, 
        default=dict, 
        server_default="{}"
    )
    
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")