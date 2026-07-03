"""Base graph node contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from eo_llm.adapters.agentcore_adapter import AgentCoreAdapter
from eo_llm.adapters.mcp_client import call_mcp_tool
from eo_llm.graph.state import GraphState, GraphStateModel, validate_state


class GraphNode(ABC):
    """LangGraph-compatible node base class."""

    def __init__(
        self,
        adapter: AgentCoreAdapter | None = None,
        tool_caller: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._adapter = adapter or AgentCoreAdapter()
        self._tool_caller = tool_caller or call_mcp_tool

    def __call__(self, state: GraphState) -> GraphState:
        return self.run(validate_state(state))

    @abstractmethod
    def run(self, s: GraphStateModel) -> GraphState: ...
