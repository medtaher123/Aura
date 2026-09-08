"""Typed pause state persisted on a conversation between HITL turns."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.db.models.message import UserMessage
from src.services.graph_runner.models import GraphTurnResult


class ConversationPauseState(BaseModel):
    """Server-side metadata for resuming a graph turn after user input.

    LangGraph checkpoints hold graph channel state; this record holds the
    resume pointer, UI payload, and node execution blobs.
    """

    model_config = ConfigDict(extra="ignore")

    checkpoint_thread_id: str = ""
    needs_input: dict[str, Any] = Field(default_factory=dict)
    hitl_blobs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    detected_lang: str = "en"
    conversation_id: str | None = None
    conversation_title_pending: bool = False
    title_user_message: str = ""
    user_message_persisted: bool = False

    @classmethod
    def from_storage(cls, raw: dict[str, Any] | None) -> ConversationPauseState | None:
        if not isinstance(raw, dict) or not raw:
            return None
        return cls.model_validate(raw)

    @classmethod
    def from_turn(
        cls,
        turn: GraphTurnResult,
        *,
        conversation_id: str,
        detected_lang: str,
        title_user_message: str,
        conversation_title_pending: bool,
        user_message_persisted: bool,
        needs_input: dict[str, Any],
    ) -> ConversationPauseState:
        raw_blobs = turn.data.get("hitl_blobs")
        hitl_blobs = (
            {name: dict(blob) for name, blob in raw_blobs.items()}
            if isinstance(raw_blobs, dict)
            else {}
        )
        return cls(
            checkpoint_thread_id=str(turn.data.get("checkpoint_thread_id") or ""),
            needs_input=needs_input,
            hitl_blobs=hitl_blobs,
            detected_lang=detected_lang or "en",
            conversation_id=conversation_id,
            conversation_title_pending=conversation_title_pending,
            title_user_message=title_user_message,
            user_message_persisted=user_message_persisted,
        )

    def to_storage(self) -> dict[str, Any]:
        return self.model_dump(mode="python")

    def unpersisted_user_message(self) -> UserMessage | None:
        if self.user_message_persisted:
            return None
        text = (self.title_user_message or "").strip()
        if not text:
            return None
        return UserMessage.create(text)
