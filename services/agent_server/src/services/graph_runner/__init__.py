"""Graph runner service."""

from __future__ import annotations

import uuid
from typing import Any

from src.core.event_emitter import EventEmitter
from src.db.models.message import InputResponseMessage, Message, UserMessage

from .models import (
    GraphResumeRequest,
    GraphRunnerRequest,
    GraphTurnRequest,
    GraphTurnResult,
)
from .responses import GraphTurnResultFactory
from .service import GraphRunnerService

_default_service: GraphRunnerService | None = None


def get_graph_runner_service() -> GraphRunnerService:
    global _default_service
    if _default_service is None:
        _default_service = GraphRunnerService()
    return _default_service


async def run_graph_turn(
    *,
    message: UserMessage,
    user_id: str,
    session_id: str,
    thread_id: str | None = None,
    document_ref: dict[str, Any] | None = None,
    place_hint: str | None = None,
    chat_history: list[Message] | None = None,
    stream_emitter: EventEmitter | None = None,
) -> GraphTurnResult:
    """Run one graph turn and return a GraphTurnResult for the websocket layer."""
    resolved_thread = thread_id or f"{session_id}:{uuid.uuid4()}"
    request = GraphTurnRequest(
        thread_id=resolved_thread,
        message=message,
        user_id=user_id,
        session_id=session_id,
        document_ref=document_ref or {},
        place_hint=place_hint,
        chat_history=list(chat_history or []),
        stream_emitter=stream_emitter,
    )
    return await get_graph_runner_service().execute(request)


async def resume_graph_turn(
    *,
    thread_id: str,
    message: InputResponseMessage,
    chat_history: list[Message] | None = None,
    stream_emitter: EventEmitter | None = None,
) -> GraphTurnResult:
    """Resume a paused graph after the user provided required inputs."""
    request = GraphResumeRequest(
        thread_id=thread_id,
        message=message,
        chat_history=list(chat_history or []),
        stream_emitter=stream_emitter,
    )
    return await get_graph_runner_service().execute(request)


__all__ = [
    "GraphResumeRequest",
    "GraphRunnerRequest",
    "GraphRunnerService",
    "GraphTurnRequest",
    "GraphTurnResult",
    "GraphTurnResultFactory",
    "get_graph_runner_service",
    "resume_graph_turn",
    "run_graph_turn",
]
