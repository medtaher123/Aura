from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, AsyncIterator, Type

import aioboto3

from eo_llm.adapters.bedrock import LLMProvider
from eo_llm.adapters.bedrock.llm_providers.bedrock_helpers.file_media import (
    MAX_DOCUMENTS_PER_MESSAGE,
)
from eo_llm.adapters.bedrock.llm_providers.bedrock_helpers.file_media_context import (
    ensure_bedrock_media_for_messages,
    get_bedrock_file_media,
)
from eo_llm.adapters.bedrock.llm_provider import (
    ConverseResponse,
    ConverseToolCall,
    FileMediaMode,
    LLMProvider,
    T,
)
from src.tools.providers.base import ToolDescriptor
from src.config import get_config
from src.db.models.message_attachments import FileAttachment

if TYPE_CHECKING:
    from src.db.models.message import Message
    from src.db.models.message_attachments import MessageAttachment

logger = logging.getLogger("eo_llm.bedrock")

config = get_config()


class BedrockProvider(LLMProvider):
    """AWS Bedrock Runtime async implementation of ``LLMProvider``."""

    @property
    def name(self) -> str:
        return "bedrock"

    def __init__(self) -> None:
        # aioboto3 sessions are standard objects, but the clients they create are async context managers
        self._session = aioboto3.Session(region_name=config.bedrock_region)
        self._last_failure_reason = ""

    def format_file_attachment(
        self,
        attachment: FileAttachment,
        *,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> list[dict[str, Any]]:
        if file_media_mode is not FileMediaMode.MEDIA:
            return super().format_file_attachment(
                attachment, file_media_mode=file_media_mode
            )
        media = get_bedrock_file_media(attachment.file_id)
        if media is None:
            return super().format_file_attachment(
                attachment, file_media_mode=file_media_mode
            )
        return [media.to_content_block()]

    def _standard_content_blocks_for_message(
        self,
        message: "Message",
        *,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> list[dict[str, Any]]:
        blocks = self._text_and_attachment_blocks(
            message, file_media_mode=file_media_mode
        )
        return self._with_media_requirements(blocks)

    def _text_and_attachment_blocks(
        self,
        message: "Message",
        *,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        text = (message.content or "").strip()
        if text:
            blocks.append({"text": text})
        remaining_documents = MAX_DOCUMENTS_PER_MESSAGE
        for attachment in message.attachments:
            extra = self._capped_attachment_blocks(
                attachment,
                remaining_documents,
                file_media_mode=file_media_mode,
            )
            remaining_documents -= sum(1 for block in extra if "document" in block)
            blocks.extend(extra)
        return blocks

    def _capped_attachment_blocks(
        self,
        attachment: "MessageAttachment",
        remaining_documents: int,
        *,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
    ) -> list[dict[str, Any]]:
        extra = self._content_blocks_for_attachment(
            attachment, file_media_mode=file_media_mode
        )
        extra_docs = sum(1 for block in extra if "document" in block)
        if extra_docs and extra_docs > remaining_documents:
            if isinstance(attachment, FileAttachment):
                return super().format_file_attachment(
                    attachment, file_media_mode=file_media_mode
                )
            return []
        return extra

    @staticmethod
    def _with_media_requirements(
        blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        has_media = any("document" in block or "image" in block for block in blocks)
        if not has_media:
            return blocks
        if not any("text" in block for block in blocks):
            blocks = [{"text": " "}, *blocks]
        return [*blocks, {"cachePoint": {"type": "default"}}]

    @property
    def last_failure_reason(self) -> str:
        return self._last_failure_reason

    async def format_converse_messages(
        self,
        *,
        chat_history: Sequence["Message"] | None = None,
        query: str | None = None,
        file_media_mode: FileMediaMode = FileMediaMode.CAPTION,
        include_tool_messages: bool = False,
    ) -> list[dict[str, Any]]:
        messages = self.filter_messages_for_llm(
            chat_history,
            include_tool_messages=include_tool_messages,
        )
        if file_media_mode is FileMediaMode.MEDIA and messages:
            await ensure_bedrock_media_for_messages(messages)
        formatted = self.format_messages(messages, file_media_mode=file_media_mode)
        if not formatted and query:
            return [{"role": "user", "content": [{"text": query}]}]
        return formatted

    @staticmethod
    def _parse_converse_response(raw: dict[str, Any]) -> ConverseResponse:
        stop_reason = str(raw.get("stopReason") or "").lower()
        content = list((raw.get("output") or {}).get("message", {}).get("content") or [])
        text_parts: list[str] = []
        tool_calls: list[ConverseToolCall] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if "text" in block:
                text = str(block.get("text") or "").strip()
                if text:
                    text_parts.append(text)
            tool_use = block.get("toolUse")
            if isinstance(tool_use, dict):
                raw_input = tool_use.get("input") or {}
                tool_calls.append(
                    ConverseToolCall(
                        id=str(tool_use.get("toolUseId") or ""),
                        name=str(tool_use.get("name") or ""),
                        arguments=raw_input if isinstance(raw_input, dict) else {},
                    )
                )
        normalized_stop = (
            "tool_use"
            if stop_reason == "tool_use"
            else "end_turn"
            if stop_reason == "end_turn"
            else "other"
        )
        return ConverseResponse(
            stop_reason=normalized_stop,
            text="\n".join(text_parts).strip(),
            tool_calls=tool_calls,
        )

    @staticmethod
    def _bedrock_tool_config(tools: list[ToolDescriptor]) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool.name,
                        "description": tool.description or tool.name,
                        "inputSchema": {
                            "json": tool.input_schema
                            or {"type": "object", "properties": {}},
                        },
                    }
                }
                for tool in tools
            ],
            "toolChoice": {"auto": {}},
        }

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
        file_media_mode: FileMediaMode = FileMediaMode.MEDIA,
    ) -> T | None:
        if not model_id:
            self._last_failure_reason = "model_not_ready"
            return None

        self._last_failure_reason = ""
        native_schema = response_model.model_json_schema()
        tool_config = {
            "tools": [
                {
                    "toolSpec": {
                        "name": schema_name,
                        "description": schema_description,
                        "inputSchema": {
                            "json": native_schema,
                        },
                    },
                }
            ],
            "toolChoice": {
                "tool": {
                    "name": schema_name,
                }
            },
        }

        try:
            async with self._session.client("bedrock-runtime") as client:
                response = await client.converse(
                    modelId=model_id,
                    system=[{"text": system_prompt}],
                    messages=await self.format_converse_messages(
                        chat_history=chat_history,
                        file_media_mode=file_media_mode,
                        include_tool_messages=False,
                    ),
                    inferenceConfig={
                        "temperature": float(temperature),
                        "maxTokens": int(max_tokens),
                    },
                    toolConfig=tool_config,
                )

            stop_reason = str(response.get("stopReason") or "").lower()
            if stop_reason == "tool_use":
                result = response["output"]["message"]["content"][0]["toolUse"]["input"]
                return response_model.model_validate(result)

        except Exception as e:
            logger.warning("Bedrock structured call failed for schema %s: %s", schema_name, e)
            return None

    async def call_stream(
        self,
        *,
        model_id: str,
        system_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 900,
        chat_history: Sequence["Message"] | None = None,
        file_media_mode: FileMediaMode = FileMediaMode.MEDIA,
    ) -> AsyncIterator[str]:
        """Send a standard text prompt and yield streamed text responses."""
        if not model_id:
            self._last_failure_reason = "model_not_ready"
            return

        self._last_failure_reason = ""

        try:
            async with self._session.client("bedrock-runtime") as client:
                response = await client.converse_stream(
                    modelId=model_id,
                    system=[{"text": system_prompt}],
                    messages=await self.format_converse_messages(
                        chat_history=chat_history,
                        file_media_mode=file_media_mode,
                        include_tool_messages=False,
                    ),
                    inferenceConfig={
                        "temperature": float(temperature),
                        "maxTokens": int(max_tokens),
                    },
                )

                stream = response.get("stream")
                if stream:
                    async for event in stream:
                        if "contentBlockDelta" in event:
                            delta = event["contentBlockDelta"].get("delta", {})
                            if "text" in delta:
                                yield delta["text"]

        except Exception as e:
            self._last_failure_reason = f"{type(e).__name__}:{e}"
            logger.warning("Bedrock streaming call failed: %s", e)
            raise RuntimeError(f"Streaming failed: {self._last_failure_reason}") from e

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
        if not model_id:
            self._last_failure_reason = "model_not_ready"
            raise RuntimeError("Bedrock model_id is not configured")

        converse_messages = await self.format_converse_messages(
            chat_history=chat_history,
            file_media_mode=file_media_mode,
            include_tool_messages=bool(tools),
        )

        self._last_failure_reason = ""
        request: dict[str, Any] = {
            "modelId": model_id,
            "system": [{"text": system_prompt}],
            "messages": converse_messages,
            "inferenceConfig": {
                "temperature": float(temperature),
                "maxTokens": int(max_tokens),
            },
        }
        if tools:
            request["toolConfig"] = self._bedrock_tool_config(tools)

        async with self._session.client("bedrock-runtime") as client:
            raw = await client.converse(**request)
        return self._parse_converse_response(raw)

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
        """Handles standard (non-structured) calls that include a document payload."""
        messages = self.format_messages(chat_history or ())
        if not messages or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": [{"text": " "}]})
        elif not any(
            isinstance(part, dict) and "text" in part
            for part in messages[-1]["content"]
        ):
            messages[-1]["content"].insert(0, {"text": " "})
        messages[-1]["content"].append(
            {
                "document": {
                    "format": document_format,
                    "name": document_name,
                    "source": {"bytes": document_bytes},
                }
            }
        )

        async with self._session.client("bedrock-runtime") as client:
            response = await client.converse(
                modelId=model_id,
                system=[{"text": system_prompt}],
                messages=messages,
                inferenceConfig={"temperature": 0.0, "maxTokens": 900},
            )
            return response
