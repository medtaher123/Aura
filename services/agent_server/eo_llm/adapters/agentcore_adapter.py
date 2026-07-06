"""AgentCore integration seam.

Keep this adapter thin so graph code stays framework-agnostic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Type, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from eo_llm.document_store import load_document_bytes
from eo_llm.prompts import DOCUMENT_QA_SYSTEM, get_document_location_prompt

logger = logging.getLogger("eo_llm.agentcore")

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


class FinalAnswerResponse(BaseModel):
    """Schema for structured final answers."""

    model_config = ConfigDict(extra="forbid")

    final_answer: str


class LocationHint(BaseModel):
    """Schema for geo-location query extraction."""

    model_config = ConfigDict(extra="forbid")

    place_query: str


class BedrockStructuredClient:
    """Handles communications, schema rendering, and auto-parsing for Bedrock."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.last_failure_reason = ""

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
        """Send native Pydantic schema to Bedrock and auto-parse the response."""
        if not self._client or not model_id:
            self.last_failure_reason = "client_or_model_not_ready"
            return None

        self.last_failure_reason = ""
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
                self.last_failure_reason = f"stop_reason:{stop_reason}"
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
            self.last_failure_reason = f"{type(e).__name__}:{e}"
            logger.warning("Bedrock call failed for schema %s: %s", schema_name, e)
            return None


@dataclass
class AgentCoreContext:
    task_id: str
    session_id: str
    user_id: str


class AgentCoreAdapter:
    """Cleaned structural adapter for AgentCore integration."""

    def __init__(self, route_decider: RouteDecider | None = None) -> None:
        cfg = self._load_runtime_config()
        self._agentcore_enabled = bool(cfg.agentcore_enabled)
        self._router_model_id = (cfg.agentcore_router_model_id or "").strip()
        self._tool_planner_model_id = (cfg.agentcore_tool_planner_model_id or "").strip()
        self._route_decider = route_decider

        raw_boto_client = self._init_agentcore_client()
        self.structured_client = (
            BedrockStructuredClient(raw_boto_client) if raw_boto_client else None
        )

    @property
    def _last_bedrock_failure_reason(self) -> str:
        if self.structured_client is None:
            return "client_not_initialized"
        return self.structured_client.last_failure_reason

    def is_ready(self) -> bool:
        return bool(self._agentcore_enabled and self.structured_client is not None)

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
            from eo_llm.prompts import get_router_prompt

            client = self.structured_client
            assert client is not None
            system_prompt, user_prompt = get_router_prompt(query=q)
            decision = client.call_structured(
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
                "AgentCore route_domains Bedrock call failed. "
                f"Reason: {self._last_bedrock_failure_reason}"
            )

        raise RuntimeError("AgentCore route_domains unavailable.")

    def compose_final_answer(
        self,
        *,
        query: str,
        answer_source: str,
        aggregated_evidence: str,
        domain_results: dict[str, Any] | None = None,
        web_results: list[dict[str, Any]] | None = None,
    ) -> str:
        model_id = self._router_model_id or self._tool_planner_model_id
        if not self.is_ready() or not model_id:
            raise RuntimeError("AgentCore finalizer unavailable.")

        from eo_llm.prompts import get_finalizer_prompt

        client = self.structured_client
        assert client is not None
        today_utc = datetime.now(timezone.utc).date().isoformat()
        system_prompt, user_prompt = get_finalizer_prompt(
            today_utc=today_utc,
            query=query,
            answer_source=answer_source,
            aggregated_evidence=aggregated_evidence,
            domain_results_json=json.dumps(domain_results or {}, default=str)[:6000],
            web_results_json=json.dumps(web_results or [], default=str)[:2500],
        )

        response = client.call_structured(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=FinalAnswerResponse,
            schema_name="final_answer_response",
            schema_description="Final user-facing answer text",
            max_tokens=900,
        )
        if response is None:
            raise RuntimeError(
                "AgentCore compose_final_answer failed. "
                f"Reason: {self._last_bedrock_failure_reason}"
            )
        final_answer = response.final_answer.strip()
        if not final_answer:
            raise RuntimeError("AgentCore compose_final_answer returned empty answer.")
        return final_answer

    def extract_location_hint(self, *, query: str) -> str:
        model_id = self._router_model_id or self._tool_planner_model_id
        if not self.is_ready() or not model_id:
            return ""

        from eo_llm.prompts import get_query_location_prompt

        client = self.structured_client
        assert client is not None
        system_prompt, user_prompt = get_query_location_prompt(query=query)
        response = client.call_structured(
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
            raise RuntimeError("AgentCore document QA unavailable: Bedrock model/client not ready.")
        assert self.structured_client is not None

        doc_bytes = load_document_bytes(document_ref)
        if not doc_bytes:
            raise ValueError("Uploaded document is empty.")

        neutral_name = str(document_ref.get("neutral_name") or "Uploaded Document").strip()
        format_value = str(document_ref.get("format") or "pdf").strip().lower() or "pdf"
        response = self.structured_client._client.converse(
            modelId=model_id,
            system=[{"text": DOCUMENT_QA_SYSTEM}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"text": (query or "").strip() or "Summarize this document."},
                        {
                            "document": {
                                "format": format_value,
                                "name": neutral_name,
                                "source": {"bytes": doc_bytes},
                            }
                        },
                    ],
                }
            ],
            inferenceConfig={"temperature": 0.0, "maxTokens": 900},
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
        client = self.structured_client
        assert client is not None
        response = client.call_structured(
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
    def _load_runtime_config() -> Any:
        import importlib

        return importlib.import_module("eo_llm.config").get_config()

    def _init_agentcore_client(self) -> Any | None:
        if not self._agentcore_enabled:
            return None
        try:
            import boto3

            cfg = self._load_runtime_config()
            kwargs: dict[str, Any] = {"region_name": cfg.agentcore_region}
            if getattr(cfg, "agentcore_endpoint", None):
                kwargs["endpoint_url"] = cfg.agentcore_endpoint.strip()
            return boto3.client("bedrock-runtime", **kwargs)
        except Exception:
            return None

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
