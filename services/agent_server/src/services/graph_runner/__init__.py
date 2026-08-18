"""Graph runner service.

Drives the ported EO_LLM LangGraph pipeline (`eo_llm.graph`) from the agent
server and adapts it to the existing WebSocket contract:

- Streams per-node status events and per-tool start/done events so the UI
  can follow the graph turn in real time.
- Maps the final `GraphState` into a `GraphTurnResult` (including artifact
  merging and the user-input pause payload).
"""

from __future__ import annotations

from typing import Any

from src.core.event_emitter import EventEmitter
from src.db.models.message import Message, UserMessage
from src.db.models.message_attachments import MessageAttachment, parse_attachments

from .models import GraphResumeRequest, GraphTurnRequest, GraphTurnResult
from .responses import GraphTurnResultFactory
from .service import GraphRunnerService

_default_service: GraphRunnerService | None = None


def get_graph_runner_service() -> GraphRunnerService:
    global _default_service
    if _default_service is None:
        _default_service = GraphRunnerService()
    return _default_service


def run_graph_turn(
    *,
    message: UserMessage,
    user_id: str,
    session_id: str,
    document_ref: dict[str, Any] | None = None,
    place_hint: str | None = None,
    chat_history: list[Message] | None = None,
    stream_emitter: EventEmitter | None = None,
) -> GraphTurnResult:
    """Run one graph turn and return a GraphTurnResult for the websocket layer."""
    request = GraphTurnRequest(
        message=message,
        user_id=user_id,
        session_id=session_id,
        document_ref=document_ref or {},
        place_hint=place_hint,
        chat_history=list(chat_history or []),
        stream_emitter=stream_emitter,
    )
    return get_graph_runner_service().run_turn(request)


def resume_graph_turn(
    *,
    graph_state: dict[str, Any],
    attachments: list[MessageAttachment] | list[dict[str, Any]] | None = None,
    stream_emitter: EventEmitter | None = None,
) -> GraphTurnResult:
    """Resume a paused graph after the user provided required inputs."""
    request = GraphResumeRequest(
        graph_state=graph_state,
        attachments=parse_attachments(attachments),
        stream_emitter=stream_emitter,
    )
    return get_graph_runner_service().resume_turn(request)


__all__ = [
    "GraphResumeRequest",
    "GraphRunnerService",
    "GraphTurnRequest",
    "GraphTurnResult",
    "GraphTurnResultFactory",
    "get_graph_runner_service",
    "resume_graph_turn",
    "run_graph_turn",
]
