"""Pydantic request/response schemas for the HTTP API."""

from __future__ import annotations

from typing import Any

__all__ = [
    "ConversationCreate",
    "ConversationMessage",
    "ConversationRead",
    "ConversationWithMessages",
    "FileRead",
]


def __getattr__(name: str) -> Any:
    if name in {
        "ConversationCreate",
        "ConversationMessage",
        "ConversationRead",
        "ConversationWithMessages",
    }:
        from . import chat as chat_schemas

        return getattr(chat_schemas, name)
    if name == "FileRead":
        from .files import FileRead

        return FileRead
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
