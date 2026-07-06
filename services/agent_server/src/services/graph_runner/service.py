"""Graph runner service — drives the EO_LLM LangGraph pipeline."""

from __future__ import annotations

from typing import Any, Callable

from eo_llm.adapters.mcp_client import reset_stream_callback, set_stream_callback
from eo_llm.graph.builder import build_graph
from eo_llm.graph.nodes.base import GraphNode

from ...core.logger import get_logger
from ...tools.contracts import ToolResponse
from .models import GraphResumeRequest, GraphTurnRequest, StreamCallback
from .responses import ToolResponseFactory

logger = get_logger("graph_runner")


class GraphRunnerService:
    """Encapsulates graph execution, streaming, and response mapping."""

    def __init__(
        self,
        graph_builder: Callable[[], Any] = build_graph,
        response_factory: ToolResponseFactory | None = None,
    ):
        self._graph = graph_builder()
        self._response_factory = response_factory or ToolResponseFactory()

    def run_turn(self, request: GraphTurnRequest) -> ToolResponse:
        """Run one graph turn and return a ToolResponse for the websocket layer."""
        state = request.to_state_dict()
        logger.info(
            f"Graph turn starting - session_id: {request.session_id}, "
            f"query length: {len(request.english_query)}"
        )
        final = self._run_streaming(state, request.stream_callback)
        return self._response_factory.from_state(final)

    def resume_turn(self, request: GraphResumeRequest) -> ToolResponse:
        """Resume a paused graph after the user confirmed a location."""
        state = request.to_state_dict()
        logger.info(
            f"Graph resume starting - confirmed_index: {request.confirmed_index}, "
            f"candidates: {len(request.graph_state.get('location_candidates') or [])}"
        )
        final = self._run_streaming(state, request.stream_callback)
        return self._response_factory.from_state(final)

    def _run_streaming(
        self,
        state: dict[str, Any],
        stream_callback: StreamCallback | None,
    ) -> dict[str, Any]:
        emitted: set[str] = set()
        final_state: dict[str, Any] = dict(state)

        token = None
        if stream_callback is not None:
            token = set_stream_callback(stream_callback)
        try:
            for mode, chunk in self._graph.stream(state, stream_mode=["updates", "values"]):
                if mode == "updates" and isinstance(chunk, dict):
                    for node_name in chunk:
                        self._emit_status(stream_callback, node_name, emitted)
                elif mode == "values" and isinstance(chunk, dict):
                    final_state = chunk
        finally:
            if token is not None:
                reset_stream_callback(token)
        return final_state

    @staticmethod
    def _emit_status(
        stream_callback: StreamCallback | None,
        node_name: str,
        emitted: set[str],
    ) -> None:
        if stream_callback is None or node_name in emitted:
            return
        emitted.add(node_name)
        spec = GraphNode.status_for(node_name)
        if spec is None:
            return
        stage, message = spec
        try:
            stream_callback({"type": "graph_status", "stage": stage, "message": message})
        except Exception:
            logger.debug("graph status stream callback failed", exc_info=True)
