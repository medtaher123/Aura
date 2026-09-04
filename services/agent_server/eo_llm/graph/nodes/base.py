"""Base graph node contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from langgraph.types import interrupt

from eo_llm.graph import hitl as hitl_store
from eo_llm.graph.state import GraphState, GraphStateModel, validate_state
from src.core.event_emitter import GraphNodeLifecycleEvent, GraphStatusStage, emit_event


class GraphNode(ABC):
    """LangGraph-compatible node base class."""

    node_name: ClassVar[str] = ""
    status_stage: ClassVar[GraphStatusStage | None] = None
    status_message: ClassVar[str | None] = None
    emit_node_lifecycle: ClassVar[bool] = True

    _registry: ClassVar[dict[str, type[GraphNode]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.node_name:
            GraphNode._registry[cls.node_name] = cls

    async def __call__(self, state: GraphState) -> GraphState:
        s = hitl_store.hydrate_state_from_resume(validate_state(state))
        self._emit_lifecycle_running()
        result = await self.run(s)
        # Persist attachment-derived fields via this node's update only.
        # Never use Command(update=...) on resume — it races with dump_state.
        patch = hitl_store.resume_state_patch()
        if patch:
            out = dict(result) if isinstance(result, dict) else {}
            result = {**patch, **out}
        self._emit_lifecycle_done(result)
        return result

    def node_lifecycle_result(self, result: GraphState) -> dict[str, Any] | None:
        """Body for node_end. Override to slim/customize. None omits result."""
        return dict(result) if isinstance(result, dict) else {}

    def _lifecycle_domain(self) -> str | None:
        domain = getattr(type(self), "domain_name", None)
        if isinstance(domain, str) and domain.strip():
            return domain.strip()
        return None

    def _emit_lifecycle_running(self) -> None:
        if not self.emit_node_lifecycle:
            return
        emit_event(
            GraphNodeLifecycleEvent(
                phase="running",
                node_name=self.node_name or type(self).__name__,
                domain=self._lifecycle_domain(),
                message=self.status_message,
            )
        )

    def _emit_lifecycle_done(self, result: GraphState) -> None:
        if not self.emit_node_lifecycle:
            return
        payload = self.node_lifecycle_result(result)
        error = False
        message = self.status_message
        if isinstance(payload, dict):
            error = bool(payload.get("error"))
            display = payload.get("message")
            if isinstance(display, str) and display.strip():
                message = display.strip()
        emit_event(
            GraphNodeLifecycleEvent(
                phase="done",
                node_name=self.node_name or type(self).__name__,
                domain=self._lifecycle_domain(),
                message=message,
                result=payload,
                error=error,
            )
        )

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
        raw = interrupt(client_payload)
        if isinstance(raw, dict):
            return raw
        return {"data": raw} if raw is not None else {}
