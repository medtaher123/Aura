"""LLM provider protocol for Bedrock-backed graph operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, AsyncIterator, Type, TypeVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from src.db.models.message import Message

T = TypeVar("T", bound=BaseModel)

_LLM_ROLES = frozenset({"user", "assistant"})


class LLMProvider(ABC):
    """Interface for LLM communications."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Must be implemented by subclasses to identify the provider."""
        pass


    def format_messages(
        self,
        messages: Sequence["Message"],
        *,
        user_message: "Message | None" = None,
    ) -> list[dict[str, Any]]:
        """Turn ORM ``Message`` history (+ optional current user turn) into provider messages.

        The current turn is ``user_message`` (``rendered_content``).

        Default shape is Bedrock Converse ``[{role, content: [{text}]}]``, merging
        consecutive same-role turns. Subclasses may override for other vendors.
        """
        formatted: list[dict[str, Any]] = []
        for message in messages:
            if not message.has_content:
                continue
            role = (message.role or "").strip().lower()
            if role not in _LLM_ROLES:
                role = "user"
            text = message.rendered_content.strip()
            if formatted and formatted[-1]["role"] == role:
                prev = formatted[-1]["content"][0]["text"]
                formatted[-1]["content"] = [{"text": f"{prev}\n{text}"}]
            else:
                formatted.append({"role": role, "content": [{"text": text}]})

        if user_message is not None and user_message.has_content:
            current: dict[str, Any] | None = {
                "role": "user",
                "content": [{"text": user_message.rendered_content.strip()}],
            }
        else:
            current = None

        if current is not None:
            if formatted and formatted[-1]["role"] == "user":
                prev_parts = list(formatted[-1]["content"])
                for part in current["content"]:
                    if (
                        isinstance(part, dict)
                        and "text" in part
                        and prev_parts
                        and isinstance(prev_parts[-1], dict)
                        and "text" in prev_parts[-1]
                    ):
                        prev_parts[-1] = {
                            "text": f"{prev_parts[-1]['text']}\n{part['text']}"
                        }
                    else:
                        prev_parts.append(part)
                formatted[-1]["content"] = prev_parts
            else:
                formatted.append(current)

        return formatted

    @abstractmethod
    async def call_structured(
        self,
        *,
        model_id: str,
        system_prompt: str,
        response_model: Type[T],
        schema_name: str,
        schema_description: str,
        user_message: "Message | None" = None,
        temperature: float = 0.0,
        max_tokens: int = 800,
        chat_history: Sequence["Message"] | None = None,
    ) -> T | None:
        pass

    @abstractmethod
    async def call_stream(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_message: "Message | None" = None,
        temperature: float = 0.0,
        max_tokens: int = 900,
        chat_history: Sequence["Message"] | None = None,
    ) -> AsyncIterator[str]:
        yield ""
        raise NotImplementedError

    @abstractmethod
    async def call_standard_with_document(
        self,
        *,
        model_id: str,
        system_prompt: str,
        document_bytes: bytes,
        document_name: str,
        document_format: str,
        user_message: "Message | None" = None,
        chat_history: Sequence["Message"] | None = None,
    ) -> dict[str, Any]:
        pass
