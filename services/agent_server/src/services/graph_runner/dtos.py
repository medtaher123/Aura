"""Data transfer objects for the graph runner service."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.event_emitter import EventEmitter


class ChatMessage(BaseModel):
    role: str = "assistant"
    content: str = ""


class GraphTurnRequest(BaseModel):
    """Input for a single graph turn."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    english_query: str
    user_id: str
    session_id: str
    document_ref: dict[str, Any] = Field(default_factory=dict)
    place_hint: Optional[str] = None
    chat_history: list[ChatMessage] = Field(default_factory=list)
    stream_emitter: Optional[EventEmitter] = None

    def contextualize_query(self) -> str:
        q = (self.english_query or "").strip()
        if not q:
            return ""
        recent = self.chat_history[-6:]
        if not recent:
            return q
        lines: list[str] = [f"Current user message: {q}", "Recent conversation:"]
        for item in recent:
            role = (item.role or "assistant").upper()
            content = (item.content or "").strip()
            if content:
                lines.append(f"- {role}: {content}")
        return "\n".join(lines)

    def to_state_dict(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "query": self.contextualize_query(),
            "user_query": self.english_query,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "document_ref": self.document_ref,
        }
        if self.place_hint and self.place_hint.strip():
            state["place_hint"] = self.place_hint.strip()
        return state


class GraphResumeRequest(BaseModel):
    """Input for resuming a graph paused for location confirmation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    graph_state: dict[str, Any]
    confirmed_index: int
    stream_emitter: Optional[EventEmitter] = None

    def to_state_dict(self) -> dict[str, Any]:
        return {
            **self.graph_state,
            "confirmed_location_index": int(self.confirmed_index),
        }
