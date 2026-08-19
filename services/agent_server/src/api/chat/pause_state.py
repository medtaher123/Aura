"""Typed pause state persisted on a conversation between HITL turns."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.db.models.message import UserMessage
from src.services.graph_runner.models import GraphTurnResult


class ConversationPauseState(BaseModel):
    """Server-side snapshot for resuming a graph turn after user input.

    Stored as JSONB on ``conversations.pause_state``. The client only receives
    a conversation_id reference, not this full payload.
    """

    model_config = ConfigDict(extra="ignore")

    graph_state: dict[str, Any] = Field(default_factory=dict)
    needs_input: dict[str, Any] = Field(default_factory=dict)
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
        payload = turn.pause_payload()
        return cls(
            graph_state=dict(payload.get("graph_state") or {}),
            needs_input=needs_input,
            detected_lang=detected_lang or "en",
            conversation_id=conversation_id,
            conversation_title_pending=conversation_title_pending,
            title_user_message=title_user_message,
            user_message_persisted=user_message_persisted,
        )

    def to_storage(self) -> dict[str, Any]:
        return self.model_dump(mode="python")

    @property
    def resume_user_text(self) -> str:
        """Original user query for history if it was not persisted before pause."""
        return str(self.graph_state.get("user_query") or self.title_user_message or "")

    def unpersisted_user_message(self) -> UserMessage | None:
        """Original user turn to persist if it was skipped before the pause."""
        if self.user_message_persisted:
            return None
        text = self.resume_user_text
        if not text:
            return None
        return UserMessage.create(text)
