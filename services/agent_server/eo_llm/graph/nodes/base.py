"""Base graph node contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from eo_llm.graph.state import GraphState, GraphStateModel, validate_state
from src.core.event_emitter import GraphStatusStage


class GraphNode(ABC):
    """LangGraph-compatible node base class."""

    node_name: ClassVar[str] = ""
    status_stage: ClassVar[GraphStatusStage | None] = None
    status_message: ClassVar[str | None] = None

    _registry: ClassVar[dict[str, type[GraphNode]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.node_name:
            GraphNode._registry[cls.node_name] = cls

    async def __call__(self, state: GraphState) -> GraphState:
        return await self.run(validate_state(state))

    @classmethod
    def status_for(cls, node_name: str) -> tuple[GraphStatusStage, str] | None:
        """Return (stage, message) for a graph node name, if the node defines one."""
        node_cls = cls._registry.get(node_name)
        if node_cls is None:
            return None
        stage = node_cls.status_stage
        message = node_cls.status_message
        if not stage or not message:
            return None
        return stage, message

    @abstractmethod
    async def run(self, s: GraphStateModel) -> GraphState: ...
