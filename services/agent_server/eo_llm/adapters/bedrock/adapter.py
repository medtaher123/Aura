"""High-level Bedrock LLM adapter used by EO_LLM graph nodes."""

from __future__ import annotations

from typing import Any

from eo_llm.adapters.bedrock.converse_response import (
    extract_document_citations,
    extract_text_from_converse_response,
)
from eo_llm.adapters.bedrock.domain_route_decision import DomainRouteDecision
from eo_llm.adapters.bedrock.runtime_client import create_bedrock_runtime_client
from eo_llm.adapters.bedrock.llm_provider import LLMProvider
from eo_llm.adapters.bedrock.location_hint import LocationHint
from eo_llm.adapters.bedrock.settings import BedrockLLMSettings
from eo_llm.adapters.bedrock.types import RouteDecider
from eo_llm.document_store import load_document_bytes
from eo_llm.prompts import (
    DOCUMENT_QA_SYSTEM,
    get_document_location_prompt,
    get_query_location_prompt,
    get_router_prompt,
)


class BedrockLLMAdapter:
    """Coordinates Bedrock routing, location extraction, and document QA."""

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
            self.provider = create_bedrock_runtime_client(config)

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

        return {
            "answer": extract_text_from_converse_response(response),
            "citations": extract_document_citations(response),
        }

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
