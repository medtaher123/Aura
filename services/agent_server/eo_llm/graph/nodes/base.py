"""Base graph node contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from eo_llm.graph import hitl as hitl_store
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

    def serialize_hitl_blob(self, s: GraphStateModel) -> dict[str, Any]:
        """Return node-local JSON-safe context to store in ``pause_state.hitl_blobs``."""
        return {}

    def apply_hitl_blob(
        self,
        s: GraphStateModel,
        blob: dict[str, Any],
    ) -> GraphStateModel:
        """Reapply stored node-local context after resume (optional override)."""
        return s

    def load_hitl_blob(self) -> dict[str, Any] | None:
        """Return this node's blob for the current resume turn, if any."""
        return hitl_store.get_resume_blob(self.node_name)

    async def pause_for_hitl(
        self,
        s: GraphStateModel,
        client_payload: dict[str, Any],
        *,
        blob: dict[str, Any] | None = None,
    ) -> GraphStateModel:
        """Register execution context, pause via ``interrupt()``, reapply blob on resume."""
        payload_blob = blob if blob is not None else self.serialize_hitl_blob(s)
        hitl_store.register_pause_blob(self.node_name, payload_blob)
        self._interrupt(client_payload)
        return self.apply_hitl_blob(s, payload_blob)

    @staticmethod
    def client_payload_needs_input(payload: dict[str, Any]) -> dict[str, Any]:
        return hitl_store.client_payload_needs_input(payload)

    def _interrupt(self, client_payload: dict[str, Any]) -> dict[str, Any]:
        from langgraph.types import interrupt

        raw = interrupt(client_payload)
        if isinstance(raw, dict):
            return raw
        return {"data": raw} if raw is not None else {}
