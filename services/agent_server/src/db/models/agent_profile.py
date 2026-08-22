"""Agent profile and tool binding ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, JSON, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

if TYPE_CHECKING:
    from src.db.models.tool_definition import ToolDefinition


class AgentProfile(BaseModel):
    """Configurable agent with domain and tool access."""

    __tablename__ = "agent_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False, default="")
    enabled_domains: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tool_bindings: Mapped[list["AgentToolBinding"]] = relationship(
        back_populates="agent_profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AgentToolBinding(BaseModel):
    """Many-to-many link between agent profiles and tools."""

    __tablename__ = "agent_tool_bindings"

    agent_profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tool_definition_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tool_definitions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    agent_profile: Mapped["AgentProfile"] = relationship(
        back_populates="tool_bindings"
    )
    tool_definition: Mapped["ToolDefinition"] = relationship(
        back_populates="agent_bindings"
    )
