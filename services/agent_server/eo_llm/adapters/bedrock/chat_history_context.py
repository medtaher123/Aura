"""Request-scoped chat history for LLM provider formatting."""

from __future__ import annotations

import contextvars
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.models.message import Message

_chat_history: contextvars.ContextVar[tuple["Message", ...] | None] = contextvars.ContextVar(
    "llm_chat_history", default=None
)


def set_chat_history(messages: Sequence["Message"] | None) -> contextvars.Token:
    """Register conversation messages for the current graph/LLM execution context."""
    if not messages:
        return _chat_history.set(None)
    return _chat_history.set(tuple(messages))


def reset_chat_history(token: contextvars.Token) -> None:
    try:
        _chat_history.reset(token)
    except (ValueError, LookupError):
        pass


def get_chat_history() -> tuple["Message", ...]:
    return _chat_history.get() or ()
