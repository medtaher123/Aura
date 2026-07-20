"""Typed stream events emitted during graph / agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.tools.contracts import ToolArtifacts

DataAgentStepPhase = Literal["running", "done"]
DataAgentStepStatus = Literal["done", "error", "skipped"]
GraphStatusStage = Literal[
    "planning",
    "tool_call",
    "analyzing",
    "Domain_call",
    "web_search",
]
ThinkingSource = Literal["route_domains", "route_keyword_fallback", "tool_plan"]


@dataclass
class TokenStreamEvent:
    content: str


@dataclass
class ThinkingStreamEvent:
    source: ThinkingSource
    reasoning: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class DataAgentStepEvent:
    phase: DataAgentStepPhase
    tool_name: str
    tool_input: dict[str, Any] = field(default_factory=dict)
    step_id: str | None = None
    domain: str | None = None
    status: DataAgentStepStatus | None = None
    attempts: int | None = None
    execution_time_seconds: float | None = None
    observation: str = ""
    error: bool = False
    artifacts: ToolArtifacts = field(default_factory=ToolArtifacts)


@dataclass
class GraphStatusEvent:
    stage: GraphStatusStage
    message: str
