"""Graph runner service — drives the EO_LLM LangGraph pipeline."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from eo_llm.graph.builder import build_graph
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.adapters.bedrock.chat_history_context import reset_chat_history, set_chat_history
from src.core.event_emitter import (
    EventEmitter,
    GraphStatusEvent,
    emit_event,
    reset_stream_emitter,
    set_stream_emitter,
)

from ...core.logger import get_logger
from .models import GraphRunnerRequest, GraphTurnResult
from .responses import GraphTurnResultFactory

logger = get_logger("graph_runner")


class GraphRunnerService:
    """Encapsulates graph execution, streaming, and response mapping."""

    def __init__(
        self,
        graph_builder: Callable[[], Any] = build_graph,
        result_factory: GraphTurnResultFactory | None = None,
    ):
        self._graph = graph_builder()
        self._result_factory = result_factory or GraphTurnResultFactory()

    def execute(self, request: GraphRunnerRequest) -> GraphTurnResult:
        """Run the graph for any ``GraphRunnerRequest`` (fresh turn or resume)."""
        state = request.to_state_dict()
        logger.info(request.start_log_message())
        history_token = set_chat_history(request.llm_chat_history())
        try:
            final = self._run_streaming(state, request.stream_emitter)
        finally:
            reset_chat_history(history_token)
        return self._result_factory.from_state(final)

    def _run_streaming(
        self,
        state: dict[str, Any],
        stream_emitter: EventEmitter | None,
    ) -> dict[str, Any]:
        # Nodes are async (GraphNode.__call__); LangGraph requires astream/ainvoke.
        # Called from a worker thread so the websocket loop stays free to flush
        # stream events in real time.
        return asyncio.run(self._arun_streaming(state, stream_emitter))

    async def _arun_streaming(
        self,
        state: dict[str, Any],
        stream_emitter: EventEmitter | None,
    ) -> dict[str, Any]:
        emitted: set[str] = set()
        final_state: dict[str, Any] = dict(state)

        token = None
        if stream_emitter is not None:
            token = set_stream_emitter(stream_emitter)
        try:
            async for mode, chunk in self._graph.astream(
                state, stream_mode=["updates", "values"]
            ):
                if mode == "updates" and isinstance(chunk, dict):
                    for node_name in chunk:
                        if node_name in emitted:
                            continue
                        emitted.add(node_name)
                        status = GraphNode.status_for(node_name)
                        if status is None:
                            continue
                        stage, message = status
                        emit_event(GraphStatusEvent(stage=stage, message=message))
                elif mode == "values" and isinstance(chunk, dict):
                    final_state = chunk
        finally:
            if token is not None:
                reset_stream_emitter(token)

        return final_state
