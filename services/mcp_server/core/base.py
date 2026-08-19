"""Plugin contracts for MCP modules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from core.context import SharedContext
    from core.requirements import Requirement


class HealthStatus:
    """Aggregated module health after probing all requirements."""

    def __init__(
        self,
        healthy: bool,
        details: dict[str, Any] | None = None,
        requirements: list[dict[str, Any]] | None = None,
    ) -> None:
        self.healthy = healthy
        self.details = details or {}
        self.requirements = requirements or []


@dataclass
class ProbeResult:
    """Outcome of a single Requirement.check()."""

    healthy: bool
    status: str
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "healthy": self.healthy,
            "status": self.status,
            "message": self.message,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class BaseModule(ABC):
    """Abstract base class for dynamically discovered MCP modules."""

    name: str
    version: str = "1.0.0"
    requirements: list[Requirement] = []

    async def initialize(self, context: SharedContext) -> None:
        """Optional hook to allocate shared resources after discovery."""

    async def check_health(self, context: SharedContext) -> HealthStatus:
        """Probe every declared requirement and aggregate results."""
        import asyncio

        async def _probe(req: Requirement) -> tuple[Requirement, ProbeResult]:
            try:
                result = await req.check(context)
            except Exception as exc:
                result = ProbeResult(
                    healthy=False,
                    status="error",
                    message=str(exc),
                )
            return req, result

        probed_pairs = await asyncio.gather(
            *[_probe(req) for req in self.requirements]
        )

        probed: list[dict[str, Any]] = []
        details: dict[str, Any] = {}
        overall = True

        for req, result in probed_pairs:
            entry = {
                "name": req.name,
                "label": req.label or req.name,
                "kind": req.kind.value,
                "required": req.required,
                **result.to_dict(),
            }
            probed.append(entry)
            details[req.name] = {
                "kind": req.kind.value,
                "status": result.status,
                "healthy": result.healthy,
                "message": result.message,
            }
            if req.required and not result.healthy:
                overall = False

        return HealthStatus(healthy=overall, details=details, requirements=probed)

    @abstractmethod
    def register_tools(self, mcp: MCPServer, context: SharedContext) -> None:
        """Register this module's tools onto the MCPServer instance."""


# Backward-compatible aliases (prefer Requirement / RequirementKind).
class DependencyType(str, Enum):
    SHARED = "shared"
    MODULE = "module"
    CONFIG = "config"
    CONNECTION = "connection"


@dataclass(frozen=True)
class Dependency:
    """Deprecated: use ModuleRequirement / ConfigRequirement / ConnectionRequirement."""

    name: str
    type: DependencyType
    required: bool = True
