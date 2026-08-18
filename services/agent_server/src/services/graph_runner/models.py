"""DTOs for graph runner requests and artifact payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from eo_llm.graph.state import GraphState
from src.core.event_emitter import EventEmitter
from src.db.models.message import Message, UserMessage
from src.db.models.message_attachments import (
    MessageAttachment,
    apply_attachments,
)
from src.user_inputs import UserInputRouter
from src.tools.contracts import ToolArtifacts, ToolCoordinates


class ArtifactBundle(BaseModel):
    """Normalized artifact payload collected from domain tool results."""

    model_config = ConfigDict(extra="allow")

    maps: list[Any] = Field(default_factory=list)
    thumbnails: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


class GraphTurnResult(BaseModel):
    """Outcome of one graph turn for the websocket / persistence layer.

    Distinct from ``ToolResponse``, which is the return type of a single MCP/tool call.
    """

    message: str
    artifacts: ToolArtifacts = Field(default_factory=ToolArtifacts)
    data: dict[str, Any] = Field(default_factory=dict)
    error: bool = False
    city: str | None = None
    coordinates: ToolCoordinates | None = None

    def pending_input_requests(self) -> dict[str, Any]:
        """Typed ``needs_input`` requests when the turn paused for user input."""
        return UserInputRouter.requests_from_dict(self.data.get("needs_input"))

    def pause_payload(self) -> dict[str, Any]:
        """``data.pause`` snapshot (includes ``graph_state``) for server-side resume."""
        pause = self.data.get("pause")
        return dict(pause) if isinstance(pause, dict) else {}


class GraphTurnRequest(BaseModel):
    """Input for a fresh graph turn."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    message: UserMessage
    user_id: str
    session_id: str
    document_ref: dict[str, Any] = Field(default_factory=dict)
    place_hint: str | None = None
    chat_history: list[Message] = Field(default_factory=list)
    stream_emitter: EventEmitter | None = Field(default=None, exclude=True)

    @property
    def english_query(self) -> str:
        """Free-text user query; attachments are applied separately."""
        return self.message.content

    def to_state_dict(self) -> GraphState:
        # History stays on the request / LLM contextvar — not flattened into ``query``.
        q = (self.english_query or "").strip()
        state: dict[str, Any] = {
            "query": q,
            "user_query": q,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "document_ref": self.document_ref,
        }
        if self.place_hint and self.place_hint.strip():
            state["place_hint"] = self.place_hint.strip()
        apply_attachments(self.message.attachments, state)
        return state  # type: ignore[return-value]


class GraphResumeRequest(BaseModel):
    """Input for resuming a graph paused for user input."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    graph_state: dict[str, Any]
    attachments: list[MessageAttachment] = Field(default_factory=list)
    stream_emitter: EventEmitter | None = Field(default=None, exclude=True)

    def to_state_dict(self) -> GraphState:
        merged: dict[str, Any] = {**self.graph_state}
        apply_attachments(self.attachments, merged)
        return merged  # type: ignore[return-value]
