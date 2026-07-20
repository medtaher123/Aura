"""DTOs for graph runner requests and artifact payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from eo_llm.graph.state import GraphState
from src.core.event_emitter import EventEmitter


class ChatMessage(BaseModel):
    role: str = "assistant"
    content: str = ""


class ArtifactBundle(BaseModel):
    """Normalized artifact payload collected from domain tool results."""

    model_config = ConfigDict(extra="allow")

    maps: list[Any] = Field(default_factory=list)
    thumbnails: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


class GraphTurnRequest(BaseModel):
    """Input for a fresh graph turn."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    english_query: str
    user_id: str
    session_id: str
    document_ref: dict[str, Any] = Field(default_factory=dict)
    place_hint: str | None = None
    chat_history: list[ChatMessage] = Field(default_factory=list)
    stream_emitter: EventEmitter | None = Field(default=None, exclude=True)

    def contextualize_query(self) -> str:
        q = (self.english_query or "").strip()
        if not q:
            return ""
        recent = self.chat_history[-6:]
        if not recent:
            return q
        lines: list[str] = [f"Current user message: {q}", "Recent conversation:"]
        for item in recent:
            content = (item.content or "").strip()
            if content:
                role = (item.role or "assistant").upper()
                lines.append(f"- {role}: {content}")
        return "\n".join(lines)

    def to_state_dict(self) -> GraphState:
        state: dict[str, Any] = {
            "query": self.contextualize_query(),
            "user_query": self.english_query,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "document_ref": self.document_ref,
        }
        if self.place_hint and self.place_hint.strip():
            state["place_hint"] = self.place_hint.strip()
        return state  # type: ignore[return-value]


class GraphResumeRequest(BaseModel):
    """Input for resuming a graph paused for location confirmation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    graph_state: dict[str, Any]
    confirmed_index: int
    stream_emitter: EventEmitter | None = Field(default=None, exclude=True)

    def to_state_dict(self) -> GraphState:
        merged = {
            **self.graph_state,
            "confirmed_location_index": int(self.confirmed_index),
        }
        return merged  # type: ignore[return-value]
