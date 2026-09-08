"""Request-scoped stream EventEmitter via contextvars."""

from __future__ import annotations

import contextvars
from typing import Any, Optional

from .event_emitter import EventEmitter

_stream_emitter: contextvars.ContextVar[Optional[EventEmitter]] = contextvars.ContextVar(
    "stream_emitter", default=None
)


def set_stream_emitter(emitter: EventEmitter | None) -> contextvars.Token:
    """Register the stream emitter for the current execution context."""
    return _stream_emitter.set(emitter)


def reset_stream_emitter(token: contextvars.Token) -> None:
    """Restore the previous stream emitter."""
    try:
        _stream_emitter.reset(token)
    except (ValueError, LookupError):
        pass


def get_stream_emitter() -> EventEmitter | None:
    return _stream_emitter.get()


def emit_event(event: Any) -> None:
    """Forward a typed event to the request-scoped emitter, if any.

    Never raises — streaming must not break tool / graph execution.
    """
    emitter = _stream_emitter.get()
    if emitter is None:
        return
    try:
        emitter.emit_sync(event)
    except Exception:
        pass
