"""LLM provider protocol for Bedrock-backed graph operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, AsyncIterator, Type, TypeVar

from pydantic import BaseModel

from src.db.models.message_attachments import FileAttachment

if TYPE_CHECKING:
    from src.db.models.message import Message
    from src.db.models.message_attachments import MessageAttachment

T = TypeVar("T", bound=BaseModel)

_LLM_ROLES = frozenset({"user", "assistant"})


class LLMProvider(ABC):
    """Interface for LLM communications."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Must be implemented by subclasses to identify the provider."""
        pass

    #TODO: to implement
    def format_file_attachment(
        self, attachment: FileAttachment
    ) -> list[dict[str, Any]]:
        """Provider-specific file content blocks. Empty until files are wired."""
        return []

    def format_messages(
        self,
        messages: Sequence["Message"],
    ) -> list[dict[str, Any]]:
        """Turn ORM ``Message`` history into provider messages.

        Default shape is Bedrock Converse ``[{role, content: [{text}]}]``.
        Messages with no content blocks are skipped.
        """
        formatted: list[dict[str, Any]] = []
        for message in messages:
            blocks = self._content_blocks_for_message(message)
            if not blocks:
                continue
            formatted.append(
                {
                    "role": self._llm_role(message.role),
                    "content": blocks,
                }
            )
        return formatted

    def _llm_role(self, role: str | None) -> str:
        normalized = (role or "").strip().lower()
        return normalized if normalized in _LLM_ROLES else "user"

    def _content_blocks_for_message(
        self, message: "Message"
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        text = (message.content or "").strip()
        if text:
            blocks.append({"text": text})
        for attachment in message.attachments:
            blocks.extend(self._content_blocks_for_attachment(attachment))
        return blocks

    def _content_blocks_for_attachment(
        self, attachment: "MessageAttachment"
    ) -> list[dict[str, Any]]:
        if isinstance(attachment, FileAttachment):
            return self.format_file_attachment(attachment)
        llm_text = attachment.llm_text()
        if not llm_text:
            return []
        return [{"text": llm_text}]

    def format_message(
        self,
        message: "Message",
    ) -> dict[str, Any] | None:
        blocks = self._content_blocks_for_message(message)
        if not blocks:
            return None
        return {
            "role": self._llm_role(message.role),
            "content": blocks,
        }

    @abstractmethod
    async def call_structured(
        self,
        *,
        model_id: str,
        system_prompt: str,
        response_model: Type[T],
        schema_name: str,
        schema_description: str,
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
        chat_history: Sequence["Message"] | None = None,
    ) -> dict[str, Any]:
        pass
