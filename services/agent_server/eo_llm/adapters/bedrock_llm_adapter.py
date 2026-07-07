"""Bedrock LLM integration for the EO_LLM graph pipeline.

Provides routing, planning, and document QA via AWS Bedrock Runtime.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Literal, Protocol, Type, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from eo_llm.document_store import load_document_bytes
from eo_llm.prompts import (
    DOCUMENT_QA_SYSTEM,
    get_document_location_prompt,
    get_query_location_prompt,
    get_router_prompt,
)

logger = logging.getLogger("eo_llm.bedrock")

T = TypeVar("T", bound=BaseModel)

RouteDomain = Literal[
    "flood_damage",
    "fire_detection",
    "disaster_detection",
    "infrastructure",
    "stac",
    "document_qa",
    "tools_info",
    "websearch_only",
]
ExecutionMode = Literal["parallel", "sequential"]
RouteDecider = Callable[[str], Any]


class DomainRouteDecision(BaseModel):
    """Schema for routing decisions (orchestrator-level)."""

    model_config = ConfigDict(extra="forbid")

    domains: list[RouteDomain] = Field(default_factory=list, min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    execution_mode: ExecutionMode = "parallel"
    reasoning: str = ""
    needs_web_fallback_if_low_confidence: bool = True
    stop_after_domains_if_confidence_at_least: float = Field(default=0.8, ge=0.0, le=1.0)


class LocationHint(BaseModel):
    """Schema for geo-location query extraction."""

    model_config = ConfigDict(extra="forbid")

    place_query: str


@dataclass
class LLMSessionContext:
    task_id: str
    session_id: str
    user_id: str


class BedrockLLMSettings(Protocol):
    """Bedrock LLM settings consumed by the graph adapter."""

    bedrock_llm_enabled: bool
    bedrock_region: str
    bedrock_endpoint: str
    bedrock_router_model_id: str
    bedrock_tool_planner_model_id: str


class LLMProvider(Protocol):
    """Interface for LLM communications."""

    @property
    def last_failure_reason(self) -> str: ...

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
    ) -> T | None: ...

    def call_stream(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 900,
    ) -> Iterator[str]: ...

    def call_standard_with_document(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        document_bytes: bytes,
        document_name: str,
        document_format: str,
    ) -> dict[str, Any]: ...


class BedrockRuntimeClient(LLMProvider):
    """AWS Bedrock Runtime implementation of ``LLMProvider``."""

    def __init__(self, client: Any) -> None:
        self._client = client
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


def _create_bedrock_runtime_client(config: BedrockLLMSettings) -> BedrockRuntimeClient | None:
    """Build the default Bedrock runtime client from application config."""
    if not config.bedrock_llm_enabled:
        return None
    try:
        import boto3

        kwargs: dict[str, Any] = {"region_name": config.bedrock_region}
        endpoint = (config.bedrock_endpoint or "").strip()
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        return BedrockRuntimeClient(boto3.client("bedrock-runtime", **kwargs))
    except Exception:
        return None


def create_bedrock_llm_adapter(
    route_decider: RouteDecider | None = None,
) -> BedrockLLMAdapter:
    """Factory for the production Bedrock LLM adapter with config-driven defaults."""
    from eo_llm.config import get_config

    cfg = get_config()
    return BedrockLLMAdapter(
        config=cfg,
        provider=_create_bedrock_runtime_client(cfg),
        route_decider=route_decider,
    )


class BedrockLLMAdapter:
    """High-level Bedrock LLM adapter used by EO_LLM graph nodes."""

    def __init__(
        self,
        config: BedrockLLMSettings | None = None,
        provider: LLMProvider | None = None,
        route_decider: RouteDecider | None = None,
    ) -> None:
        if config is None:
            from eo_llm.config import get_config

            config = get_config()

        self._bedrock_llm_enabled = bool(config.bedrock_llm_enabled)
        self._router_model_id = (config.bedrock_router_model_id or "").strip()
        self._tool_planner_model_id = (config.bedrock_tool_planner_model_id or "").strip()

        self._route_decider = route_decider
        self.provider = provider
        if self.provider is None and self._bedrock_llm_enabled:
            self.provider = _create_bedrock_runtime_client(config)

    def is_ready(self) -> bool:
        return bool(self._bedrock_llm_enabled and self.provider is not None)

    @property
    def router_model_id(self) -> str:
        return self._router_model_id

    @property
    def tool_planner_model_id(self) -> str:
        return self._tool_planner_model_id

    @property
    def finalizer_model_id(self) -> str:
        return self._router_model_id or self._tool_planner_model_id

    def route_domains(self, *, query: str) -> DomainRouteDecision:
        q = (query or "").strip().lower()
        if not q:
            return DomainRouteDecision(
                domains=["websearch_only"],
                confidence=1.0,
                execution_mode="sequential",
                reasoning="Empty query fallback.",
            )

        if self._route_decider is not None:
            raw = self._route_decider(q)
            if raw is not None:
                return (
                    raw
                    if isinstance(raw, DomainRouteDecision)
                    else DomainRouteDecision.model_validate(raw)
                )

        if self.is_ready() and self._router_model_id:
            assert self.provider is not None
            system_prompt, user_prompt = get_router_prompt(query=q)
            decision = self.provider.call_structured(
                model_id=self._router_model_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=DomainRouteDecision,
                schema_name="domain_route_decision",
                schema_description="Routing decision for EO_LLM orchestrator",
                max_tokens=500,
            )
            if decision is not None:
                return decision

            raise RuntimeError(
                "Bedrock route_domains call failed. "
                f"Reason: {self.provider.last_failure_reason}"
            )

        raise RuntimeError("Bedrock route_domains unavailable.")

    def extract_location_hint(self, *, query: str) -> str:
        model_id = self._router_model_id or self._tool_planner_model_id
        if not self.is_ready() or not model_id:
            return ""

        assert self.provider is not None
        system_prompt, user_prompt = get_query_location_prompt(query=query)
        response = self.provider.call_structured(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=LocationHint,
            schema_name="location_hint",
            schema_description="Geocodable place extracted from user query",
            max_tokens=120,
        )
        return response.place_query.strip() if response else ""

    def answer_question_with_document(
        self, *, query: str, document_ref: dict[str, Any]
    ) -> dict[str, Any]:
        """Answer a user question grounded in one uploaded document."""
        model_id = self._router_model_id or self._tool_planner_model_id
        if not self.is_ready() or not model_id:
            raise RuntimeError("Bedrock document QA unavailable: provider not ready.")

        assert self.provider is not None

        doc_bytes = load_document_bytes(document_ref)
        if not doc_bytes:
            raise ValueError("Uploaded document is empty.")

        neutral_name = str(document_ref.get("neutral_name") or "Uploaded Document").strip()
        format_value = str(document_ref.get("format") or "pdf").strip().lower() or "pdf"
        user_prompt = (query or "").strip() or "Summarize this document."

        response = self.provider.call_standard_with_document(
            model_id=model_id,
            system_prompt=DOCUMENT_QA_SYSTEM,
            user_prompt=user_prompt,
            document_bytes=doc_bytes,
            document_name=neutral_name,
            document_format=format_value,
        )

        text = self._extract_text_from_converse_response(response)
        citations = self._extract_document_citations(response)
        return {"answer": text, "citations": citations}

    def extract_location_from_document(
        self, *, query: str, document_ref: dict[str, Any]
    ) -> str:
        """Resolve an implicit place reference from uploaded document context."""
        model_id = self._router_model_id or self._tool_planner_model_id
        if not self.is_ready() or not model_id:
            return ""

        try:
            doc_bytes = load_document_bytes(document_ref)
        except Exception:
            return ""

        neutral_name = str(document_ref.get("neutral_name") or "Uploaded Document").strip()
        format_value = str(document_ref.get("format") or "pdf").strip().lower() or "pdf"
        system_prompt, user_prompt = get_document_location_prompt(query=query)

        assert self.provider is not None
        response = self.provider.call_structured(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=LocationHint,
            schema_name="document_location_hint",
            schema_description="Location inferred from uploaded document and query",
            max_tokens=120,
            user_content=[
                {"text": f"User query: {query}"},
                {
                    "document": {
                        "format": format_value,
                        "name": neutral_name,
                        "source": {"bytes": doc_bytes},
                    }
                },
            ],
        )
        return response.place_query.strip() if response else ""

    @staticmethod
    def _extract_text_from_converse_response(response: dict[str, Any]) -> str:
        content = response.get("output", {}).get("message", {}).get("content", [])
        if not isinstance(content, list):
            return ""
        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
            citations_block = part.get("citationsContent")
            if isinstance(citations_block, dict):
                generated = citations_block.get("content")
                if isinstance(generated, list):
                    for item in generated:
                        if isinstance(item, dict):
                            t = item.get("text")
                            if isinstance(t, str) and t.strip():
                                text_parts.append(t.strip())
        return "\n".join(text_parts).strip()

    @staticmethod
    def _extract_document_citations(response: dict[str, Any]) -> list[dict[str, Any]]:
        content = response.get("output", {}).get("message", {}).get("content", [])
        if not isinstance(content, list):
            return []
        citations: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            citations_block = part.get("citationsContent")
            if not isinstance(citations_block, dict):
                continue
            refs = citations_block.get("citations")
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if isinstance(ref, dict):
                    citations.append(ref)
        return citations
