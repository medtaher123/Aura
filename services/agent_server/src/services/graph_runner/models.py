"""DTOs for graph runner requests and artifact payloads."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Self

from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from eo_llm.graph.hitl import state_update_from_attachments
from eo_llm.graph.state import GraphState
from src.core.event_emitter import EventEmitter
from src.db.models.message import InputResponseMessage, Message, UserMessage
from src.db.models.message_attachments import apply_attachments, dump_attachments
from src.tools.contracts import ToolArtifacts, ToolCoordinates


class ArtifactBundle(BaseModel):
    """Normalized artifact payload collected from domain tool results."""

    model_config = ConfigDict(extra="allow")

    maps: list[Any] = Field(default_factory=list)
    thumbnails: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


class GraphTurnResult(BaseModel):
    """Outcome of one graph turn for the websocket / persistence layer."""

    message: str
    artifacts: ToolArtifacts = Field(default_factory=ToolArtifacts)
    data: dict[str, Any] = Field(default_factory=dict)
    error: bool = False
    city: str | None = None
    coordinates: ToolCoordinates | None = None

    def pending_input_requests(self) -> dict[str, Any]:
        """``needs_input`` map when the turn paused for user input."""
        raw = self.data.get("needs_input")
        return dict(raw) if isinstance(raw, dict) else {}

    def assistant_metadata(self) -> dict[str, Any]:
        """Metadata stored on the persisted assistant message."""
        return {
            "artifacts": self.artifacts.model_dump(mode="json"),
            "error": bool(self.error),
        }


class GraphRunnerRequest(BaseModel, ABC):
    """How the graph is started. Subclass for a new entry mode (fresh vs resume)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    thread_id: str
    message: Message
    chat_history: list[Message] = Field(default_factory=list)
    stream_emitter: EventEmitter | None = Field(default=None, exclude=True)

    def llm_chat_history(self) -> list[Message]:
        """Prior conversation plus this turn's incoming user message."""
        return [*self.chat_history, self.message]

    @abstractmethod
    def to_graph_input(self) -> dict[str, Any] | Command:
        """LangGraph input for this execution."""

    @abstractmethod
    def start_log_message(self) -> str:
        """One-line log when this execution begins."""

    def with_stream_emitter(self, emitter: EventEmitter) -> Self:
        return self.model_copy(update={"stream_emitter": emitter})


class GraphTurnRequest(GraphRunnerRequest):
    """Input for a fresh graph turn."""

    message: UserMessage
    user_id: str
    session_id: str
    document_ref: dict[str, Any] = Field(default_factory=dict)
    place_hint: str | None = None

    @property
    def english_query(self) -> str:
        return self.message.content

    def start_log_message(self) -> str:
        return (
            f"Graph turn starting - thread_id: {self.thread_id}, "
            f"query length: {len(self.english_query)}"
        )

    def to_graph_input(self) -> GraphState:
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


class GraphResumeRequest(GraphRunnerRequest):
    """Input for resuming a graph paused for user input."""

    message: InputResponseMessage
    hitl_blobs: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def start_log_message(self) -> str:
        types = [getattr(a, "type", type(a).__name__) for a in self.message.attachments]
        return (
            f"Graph resume starting - thread_id: {self.thread_id}, "
            f"attachment_types: {types}, hitl_nodes: {list(self.hitl_blobs)}"
        )

    def to_graph_input(self) -> Command:
        state_patch = state_update_from_attachments(
            self.message.attachments,
            self.hitl_blobs,
        )
        return Command(
            update=state_patch or None,
            resume={"data": {"attachments": dump_attachments(self.message.attachments)}},
        )
