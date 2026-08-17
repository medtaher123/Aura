from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, AsyncIterator, Type

import aioboto3

from eo_llm.adapters.bedrock import LLMProvider
from eo_llm.adapters.bedrock.llm_provider import T
from src.config import get_config

if TYPE_CHECKING:
    from src.db.models.message import Message

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

    @property
    def last_failure_reason(self) -> str:
        return self._last_failure_reason

    def _converse_messages(
        self,
        *,
        user_message: "Message | None" = None,
        chat_history: Sequence["Message"] | None = None,
    ) -> list[dict[str, Any]]:
        return self.format_messages(
            chat_history or (),
            user_message=user_message,
        )

    async def call_structured0(
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
        if not model_id:
            self._last_failure_reason = "model_not_ready"
            return None

        self._last_failure_reason = ""
        native_schema = response_model.model_json_schema()

        try:
            async with self._session.client("bedrock-runtime") as client:
                response = await client.converse(
                    modelId=model_id,
                    system=[{"text": system_prompt}],
                    messages=self._converse_messages(
                        user_message=user_message,
                        chat_history=chat_history,
                    ),
                    inferenceConfig={
                        "temperature": float(temperature),
                        "maxTokens": int(max_tokens),
                    },
                    outputConfig={
                        "textFormat": {
                            "type": "json_schema",
                            "structure": {
                                "jsonSchema": {
                                    "name": schema_name,
                                    "description": schema_description,
                                    "schema": json.dumps(native_schema),
                                }
                            },
                        }
                    },
                )

            stop_reason = str(response.get("stopReason") or "").lower()
            if stop_reason in {"max_tokens", "guardrail_intervened", "content_filtered"}:
                self._last_failure_reason = f"stop_reason:{stop_reason}"
                return None

            content = response.get("output", {}).get("message", {}).get("content", [])
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]
            raw_text = "\n".join(text_parts).strip()
            return response_model.model_validate_json(raw_text)

        except Exception as e:
            self._last_failure_reason = f"{type(e).__name__}:{e}"
            logger.warning("Bedrock structured call failed for schema %s: %s", schema_name, e)
            return None

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
                    messages=self._converse_messages(
                        user_message=user_message,
                        chat_history=chat_history,
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
        user_message: "Message | None" = None,
        temperature: float = 0.0,
        max_tokens: int = 900,
        chat_history: Sequence["Message"] | None = None,
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
                    messages=self._converse_messages(
                        user_message=user_message,
                        chat_history=chat_history,
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
        """Handles standard (non-structured) calls that include a document payload."""
        messages = self._converse_messages(
            user_message=user_message,
            chat_history=chat_history,
        )
        if not messages or messages[-1]["role"] != "user":
            messages.append(
                {
                    "role": "user",
                    "content": [{"text": "Summarize this document."}],
                }
            )
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
