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
        tool_call_records: Sequence[AgentToolCallRecord] = (),
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
        tool_call_records: Sequence[AgentToolCallRecord] = (),
        query: str | None = None,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> list[dict[str, Any]]:
        """Chat history plus prior tool rounds in provider-native message shape."""
        messages = self.format_messages(chat_history or (), file_media_mode=file_media_mode)
        if not messages and query:
            messages = [{"role": "user", "content": [{"text": query}]}]
        messages.extend(self.format_tool_call_records(tool_call_records))
        return messages

    def format_tool_call_records(
        self,
        records: Sequence[AgentToolCallRecord],
    ) -> list[dict[str, Any]]:
        """Turn executed tool records into assistant/user tool-use messages."""
        if not records:
            return []

        messages: list[dict[str, Any]] = []
        sorted_records = sorted(records, key=lambda record: record.turn_index)
        turn_indices = {record.turn_index for record in sorted_records}

        for turn_index in sorted(turn_indices):
            turn_records = [
                record
                for record in sorted_records
                if record.turn_index == turn_index and record.tool_use_id
            ]
            if not turn_records:
                continue

            tool_use_blocks: list[dict[str, Any]] = []
            tool_result_blocks: list[dict[str, Any]] = []
            for record in turn_records:
                tool_use_blocks.append(
                    {   
                        "toolUse": {
                            "toolUseId": record.tool_use_id,
                            "name": record.tool_name,
                            "input": record.arguments,
                        }
                    }
                )
                if record.result is not None:
                    result_payload = record.result.model_dump(mode="python")
                    result_status: Literal["success", "error"] = (
                        "error" if record.status == "error" else "success"
                    )
                else:
                    result_payload = {
                        "message": record.error_message or "",
                        "error": True,
                    }
                    result_status = "error"
                tool_result_blocks.append(
                    self.tool_result_content_block(
                        tool_use_id=record.tool_use_id,
                        result=result_payload,
                        status=result_status,
                    )
                )

            messages.append({"role": "assistant", "content": tool_use_blocks})
            messages.append({"role": "user", "content": tool_result_blocks})

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
