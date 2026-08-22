"""Pydantic schemas for tool platform admin API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class McpServerEnabledUpdate(BaseModel):
    """Toggle MCP server availability. Definitions come from external MCP YAML."""

    enabled: bool


class McpServerRead(BaseModel):
    id: uuid.UUID
    slug: str
    display_name: str
    base_url: str
    transport: str
    enabled: bool
    is_primary: bool
    stdio_config: dict[str, Any] = Field(default_factory=dict)
    last_health_at: Optional[datetime] = None
    last_health_status: Optional[dict[str, Any]] = None
    created_at: datetime
    tool_count: int = 0

    model_config = {"from_attributes": True}


class ToolDefinitionRead(BaseModel):
    id: uuid.UUID
    name: str
    source: Literal["native", "mcp"]
    provider_slug: str
    mcp_server_id: Optional[uuid.UUID] = None
    description: str
    enabled: bool
    discovered_at: Optional[datetime] = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class ToolDefinitionDetail(ToolDefinitionRead):
    """Full tool catalog entry including JSON Schema for inputs."""

    input_schema: dict[str, Any] = Field(default_factory=dict)


class AdminDashboardResponse(BaseModel):
    timestamp: datetime
    mcp_servers: list[McpServerRead]
    tools_total: int
    tools_native: int
    tools_mcp: int
    provider_health: list[dict[str, Any]] = Field(default_factory=list)
