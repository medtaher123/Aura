"""Graph runner service — drives the EO_LLM LangGraph pipeline."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from langgraph.types import Command

from eo_llm.graph import hitl as hitl_store
from eo_llm.graph.builder import build_graph
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.adapters.bedrock.chat_history_context import (
    reset_chat_history,
    set_chat_history,
)
from eo_llm.adapters.bedrock.llm_providers.bedrock_helpers.file_media_context import (
    reset_file_catalog,
    set_file_catalog,
)
from src.core.event_emitter import (
    EventEmitter,
    GraphStatusEvent,
    emit_event,
    reset_stream_emitter,
    set_stream_emitter,
)
from src.files.catalog import FileCatalog
from src.db.models.message_attachments import dump_attachments
from src.services.graph_runner.checkpointer import get_checkpointer

from ...core.logger import get_logger
from .models import GraphResumeRequest, GraphRunnerRequest, GraphTurnResult
from .responses import GraphTurnResultFactory

logger = get_logger("graph_runner")


class GraphRunnerService:
    """Encapsulates graph execution, streaming, and response mapping.

    Must run on the same asyncio event loop that initialized the checkpointer
    (``AsyncPostgresSaver`` binds locks to that loop).
    """

    def __init__(
        self,
        result_factory: GraphTurnResultFactory | None = None,
    ):
        self._graph = build_graph(checkpointer=get_checkpointer())
        self._result_factory = result_factory or GraphTurnResultFactory()

    async def execute(self, request: GraphRunnerRequest) -> GraphTurnResult:
        """Run the graph for any ``GraphRunnerRequest`` (fresh turn or resume)."""
        logger.info(request.start_log_message())
        history_token = set_chat_history(request.llm_chat_history())
        resume_ctx = (
            hitl_store.hitl_resume_context(
                request.hitl_blobs,
                attachments=dump_attachments(request.message.attachments),
                thread_id=request.thread_id,
            )
            if isinstance(request, GraphResumeRequest)
            else nullcontext()
        )
        try:
            with resume_ctx:
                graph_input = request.to_graph_input()
                final, interrupted = await self._arun_streaming(
                    graph_input,
                    request.thread_id,
                    request.stream_emitter,
                )
        finally:
            reset_chat_history(history_token)
        if interrupted is not None:
            return self._result_factory.from_interrupt(
                interrupted,
                final,
                checkpoint_thread_id=request.thread_id,
                hitl_blobs=hitl_store.take_pause_blobs(request.thread_id),
            )
        return self._result_factory.from_state(final)

    async def _arun_streaming(
        self,
        graph_input: dict[str, Any] | Command,
        thread_id: str,
        stream_emitter: EventEmitter | None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        emitted: set[str] = set()
        final_state: dict[str, Any] = {}
        interrupted: dict[str, Any] | None = None
        user_id = ""
        if isinstance(graph_input, dict):
            user_id = str(graph_input.get("user_id") or "").strip()

        catalog = FileCatalog(user_id) if user_id else None
        catalog_token = set_file_catalog(catalog)

        token = None
        if stream_emitter is not None:
            token = set_stream_emitter(stream_emitter)

        config = {"configurable": {"thread_id": thread_id}}
        try:
            async for mode, chunk in self._graph.astream(
                graph_input,
                config=config,
                stream_mode=["updates", "values"],
            ):
                if mode == "updates" and isinstance(chunk, dict):
                    raw_interrupt = chunk.get("__interrupt__")
                    if raw_interrupt:
                        interrupted = self._extract_interrupt_payload(raw_interrupt)
                    for node_name in chunk:
                        if node_name == "__interrupt__" or node_name in emitted:
                            continue
                        emitted.add(node_name)
                        status = GraphNode.status_for(node_name)
                        if status is None:
                            continue
                        stage, message = status
                        emit_event(GraphStatusEvent(stage=stage, message=message))
                elif mode == "values" and isinstance(chunk, dict):
                    final_state = {
                        k: v for k, v in chunk.items() if k != "__interrupt__"
                    }
                    raw_interrupt = chunk.get("__interrupt__")
                    if raw_interrupt:
                        interrupted = self._extract_interrupt_payload(raw_interrupt)
        finally:
            if token is not None:
                reset_stream_emitter(token)
            reset_file_catalog(catalog_token)

        return final_state, interrupted

    @staticmethod
    def _extract_interrupt_payload(raw_interrupt: Any) -> dict[str, Any]:
        if isinstance(raw_interrupt, (list, tuple)) and raw_interrupt:
            first = raw_interrupt[0]
            value = getattr(first, "value", first)
            if isinstance(value, dict):
                return dict(value)
            return {"data": value}
        if isinstance(raw_interrupt, dict):
            return dict(raw_interrupt)
        return {}


_default_service: GraphRunnerService | None = None


def get_graph_runner_service() -> GraphRunnerService:
    global _default_service
    if _default_service is None:
        _default_service = GraphRunnerService()
    return _default_service
