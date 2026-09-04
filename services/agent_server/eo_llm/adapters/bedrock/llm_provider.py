"""LLM provider protocol for Bedrock-backed graph operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal, Type, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from src.db.models.message_attachments import FileAttachment
from src.tools.contracts import ToolResponse
from src.tools.providers.base import ToolDescriptor

if TYPE_CHECKING:
    from src.db.models.message import Message
    from src.db.models.message_attachments import MessageAttachment

T = TypeVar("T", bound=BaseModel)

_LLM_ROLES = frozenset({"user", "assistant"})


class FileMediaMode(str, Enum):
    """How file attachments are sent on a provider call."""

    CAPTION = "caption"
    MEDIA = "media"


class ConverseToolCall(BaseModel):
    """One tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentToolCallRecord(BaseModel):
    """One executed tool call, used to rebuild provider converse history."""

    model_config = ConfigDict(extra="forbid")

    tool_use_id: str = ""
    turn_index: int = Field(default=0, ge=0)
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: Literal["done", "error"] = "done"
    latency_ms: int = Field(default=0, ge=0)
    result: ToolResponse | None = None
    error_message: str | None = None

    def to_messages(self) -> list["Message"]:
        """Persistable tool-call / tool-result message pair (UI-hidden)."""
        from src.db.models.message import Message, ToolCallMessage, ToolResultMessage

        call: Message = ToolCallMessage.create(
            tool_use_id=self.tool_use_id,
            tool_name=self.tool_name,
            arguments=dict(self.arguments or {}),
            turn_index=self.turn_index,
        )
        result_payload = (
            self.result.model_dump(mode="python") if self.result is not None else None
        )
        result_msg: Message = ToolResultMessage.create(
            tool_use_id=self.tool_use_id,
            status=self.status,
            result=result_payload,
            error_message=self.error_message,
            latency_ms=self.latency_ms,
            turn_index=self.turn_index,
        )
        return [call, result_msg]


class ConverseResponse(BaseModel):
    """Normalized result of one converse turn."""

    stop_reason: Literal["end_turn", "tool_use", "other"] = "other"
    text: str = ""
    tool_calls: list[ConverseToolCall] = Field(default_factory=list)


class LLMProvider(ABC):
    """Interface for LLM communications."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Must be implemented by subclasses to identify the provider."""
        pass

    def format_file_attachment(
        self,
        attachment: FileAttachment,
        *,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> list[dict[str, Any]]:
        """Text caption. Providers may override with native document/image blocks."""
        text = attachment.llm_text()
        return [{"text": text}] if text else []

    def format_messages(
        self,
        messages: Sequence["Message"],
        *,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> list[dict[str, Any]]:
        """Turn ORM ``Message`` history into provider messages."""
        formatted: list[dict[str, Any]] = []
        for message in messages:
            blocks = self._content_blocks_for_message(
                message, file_media_mode=file_media_mode
            )
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
        self,
        message: "Message",
        *,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> list[dict[str, Any]]:
        from src.db.models.message import MessageKind, ToolCallMessage, ToolResultMessage

        if isinstance(message, ToolCallMessage) or message.kind == MessageKind.TOOL_CALL.value:
            return self._tool_call_content_blocks(message)
        if (
            isinstance(message, ToolResultMessage)
            or message.kind == MessageKind.TOOL_RESULT.value
        ):
            return self._tool_result_content_blocks(message)
        return self._standard_content_blocks_for_message(
            message, file_media_mode=file_media_mode
        )

    def _standard_content_blocks_for_message(
        self,
        message: "Message",
        *,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        text = (message.content or "").strip()
        if text:
            blocks.append({"text": text})
        for attachment in message.attachments:
            blocks.extend(
                self._content_blocks_for_attachment(
                    attachment, file_media_mode=file_media_mode
                )
            )
        return blocks

    def _tool_call_content_blocks(self, message: "Message") -> list[dict[str, Any]]:
        meta = dict(message.message_metadata or {})
        tool_use_id = str(meta.get("tool_use_id") or "")
        tool_name = str(meta.get("tool_name") or "")
        if not tool_use_id or not tool_name:
            return []
        arguments = meta.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        return [
            {
                "toolUse": {
                    "toolUseId": tool_use_id,
                    "name": tool_name,
                    "input": arguments,
                }
            }
        ]

    def _tool_result_content_blocks(self, message: "Message") -> list[dict[str, Any]]:
        meta = dict(message.message_metadata or {})
        tool_use_id = str(meta.get("tool_use_id") or "")
        if not tool_use_id:
            return []
        status_raw = str(meta.get("status") or "done")
        result_status: Literal["success", "error"] = (
            "error" if status_raw == "error" else "success"
        )
        result_payload = meta.get("result")
        if not isinstance(result_payload, dict):
            result_payload = {
                "message": meta.get("error_message") or "",
                "error": True,
            }
            result_status = "error"
        return [
            self.tool_result_content_block(
                tool_use_id=tool_use_id,
                result=result_payload,
                status=result_status,
            )
        ]

    def _content_blocks_for_attachment(
        self,
        attachment: "MessageAttachment",
        *,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> list[dict[str, Any]]:
        if isinstance(attachment, FileAttachment):
            return self.format_file_attachment(
                attachment, file_media_mode=file_media_mode
            )
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

    def filter_messages_for_llm(
        self,
        messages: Sequence["Message"] | None,
        *,
        include_tool_messages: bool = False,
    ) -> list["Message"]:
        """Return messages safe for a provider call.

        Bedrock requires ``toolConfig`` whenever history contains ``toolUse`` or
        ``toolResult`` blocks, so non-tool calls must exclude persisted tool rows.
        """
        history = list(messages or ())
        if include_tool_messages:
            return history

        from src.db.models.message import MessageKind

        return [
            message
            for message in history
            if message.kind
            not in {
                MessageKind.TOOL_CALL.value,
                MessageKind.TOOL_RESULT.value,
            }
        ]

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
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
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
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> AsyncIterator[str]:
        yield ""
        raise NotImplementedError

    @abstractmethod
    async def call_converse(
        self,
        *,
        model_id: str,
        system_prompt: str,
        chat_history: Sequence["Message"] | None = None,
        tools: list[ToolDescriptor] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> ConverseResponse:
        """One multi-modal / tool-use converse turn."""

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

    async def format_converse_messages(
        self,
        *,
        chat_history: Sequence["Message"] | None = None,
        query: str | None = None,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
        include_tool_messages: bool = False,
    ) -> list[dict[str, Any]]:
        """Chat history in provider-native message shape."""
        messages = self.format_messages(
            self.filter_messages_for_llm(
                chat_history,
                include_tool_messages=include_tool_messages,
            ),
            file_media_mode=file_media_mode,
        )
        if not messages and query:
            messages = [{"role": "user", "content": [{"text": query}]}]
        return messages

    def tool_result_content_block(
        self,
        *,
        tool_use_id: str,
        result: dict[str, Any],
        status: Literal["success", "error"] = "success",
    ) -> dict[str, Any]:
        """One tool-result content block (Bedrock Converse shape)."""
        return {
            "toolResult": {
                "toolUseId": tool_use_id,
                "content": [{"json": result}],
                "status": status,
            }
        }
