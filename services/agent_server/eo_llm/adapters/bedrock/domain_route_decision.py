"""Schema for orchestrator routing decisions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from eo_llm.adapters.bedrock.types import ExecutionMode, RouteDomain


class DomainRouteDecision(BaseModel):
    """Schema for routing decisions (orchestrator-level)."""

    model_config = ConfigDict(extra="forbid")

    domains: list[RouteDomain] = Field(default_factory=list, min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    execution_mode: ExecutionMode = "parallel"
    reasoning: str = ""
    needs_web_fallback_if_low_confidence: bool = True
    stop_after_domains_if_confidence_at_least: float = Field(default=0.8, ge=0.0, le=1.0)
