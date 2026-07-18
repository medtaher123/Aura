"""AWS Bedrock Runtime client implementing ``LLMProvider``."""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator, Type
import boto3
from eo_llm.adapters.bedrock import LLMProvider
from eo_llm.adapters.bedrock.llm_provider import T
from src.config import get_config

logger = logging.getLogger("eo_llm.bedrock")


config = get_config()

class BedrockProvider(LLMProvider):
    """AWS Bedrock Runtime implementation of ``LLMProvider``."""

    @property
    def name(self) -> str:
        return "bedrock"

    def __init__(self) -> None:
        self._client = boto3.client("bedrock-runtime", region_name=config.bedrock_region)
        self._last_failure_reason = ""

    @property
    def last_failure_reason(self) -> str:
        return self._last_failure_reason

    def call_structured(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        schema_name: str,
        schema_description: str,
        temperature: float = 0.0,
        max_tokens: int = 800,
        user_content: list[dict[str, Any]] | None = None,
    ) -> T | None:
        if not self._client or not model_id:
            self._last_failure_reason = "client_or_model_not_ready"
            return None

        self._last_failure_reason = ""
        native_schema = response_model.model_json_schema()

        try:
            response = self._client.converse(
                modelId=model_id,
                system=[{"text": system_prompt}],
                messages=[
                    {
                        "role": "user",
                        "content": user_content or [{"text": user_prompt}],
                    }
                ],
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

    def call_stream(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 900,
    ) -> Iterator[str]:
        """Send a standard text prompt and yield streamed text responses."""
        if not self._client or not model_id:
            self._last_failure_reason = "client_or_model_not_ready"
            return

        self._last_failure_reason = ""

        try:
            response = self._client.converse_stream(
                modelId=model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={
                    "temperature": float(temperature),
                    "maxTokens": int(max_tokens),
                },
            )

            for event in response.get("stream", []):
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    if "text" in delta:
                        yield delta["text"]

        except Exception as e:
            self._last_failure_reason = f"{type(e).__name__}:{e}"
            logger.warning("Bedrock streaming call failed: %s", e)
            raise RuntimeError(f"Streaming failed: {self._last_failure_reason}") from e

    def call_standard_with_document(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        document_bytes: bytes,
        document_name: str,
        document_format: str,
    ) -> dict[str, Any]:
        """Handles standard (non-structured) calls that include a document payload."""
        response = self._client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"text": user_prompt},
                        {
                            "document": {
                                "format": document_format,
                                "name": document_name,
                                "source": {"bytes": document_bytes},
                            }
                        },
                    ],
                }
            ],
            inferenceConfig={"temperature": 0.0, "maxTokens": 900},
        )
        return response

