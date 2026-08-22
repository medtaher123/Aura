"""Tool definition ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, JSON, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

if TYPE_CHECKING:
    from src.db.models.agent_profile import AgentToolBinding
    from src.db.models.mcp_server import McpServer


class ToolDefinition(BaseModel):
    """Catalog entry for a native or MCP-backed tool."""

    __tablename__ = "tool_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    mcp_server_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    provider_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discovered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    mcp_server: Mapped[Optional["McpServer"]] = relationship(
        back_populates="tool_definitions"
    )
    agent_bindings: Mapped[list["AgentToolBinding"]] = relationship(
        back_populates="tool_definition",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
