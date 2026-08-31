"""Tool provider abstract base and shared models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from src.tools.contracts import ToolResponse


ToolSource = Literal["native", "mcp"]


@dataclass(frozen=True)
class ToolDescriptor:
    """Runtime view of a tool exposed through the platform."""

    id: UUID | None
    name: str
    source: ToolSource
    provider_id: str
    description: str
    input_schema: dict[str, Any]
    enabled: bool = True
    mcp_server_id: UUID | None = None
    module: str | None = None


@dataclass
class ProviderHealth:
    """Health snapshot for a tool provider."""

    provider_id: str
    healthy: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    tool_count: int = 0


class ToolProvider(ABC):
    """Abstract base for native and MCP tool backends."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique slug identifying this provider instance."""

    @abstractmethod
    async def discover_tools(self) -> list[ToolDescriptor]:
        """Return tools currently exposed by this provider."""

    @abstractmethod
    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResponse:
        """Execute a tool by name."""

    @abstractmethod
    async def health(self) -> ProviderHealth:
        """Probe provider connectivity and readiness."""
