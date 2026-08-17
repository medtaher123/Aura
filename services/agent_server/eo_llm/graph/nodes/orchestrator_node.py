"""Orchestrator node: sets high-level plan."""

from __future__ import annotations

import logging
from typing import Any, Callable

from eo_llm.adapters.bedrock import DomainRouteDecision, LocationHint
from eo_llm.adapters.bedrock.chat_history_context import get_chat_history
from eo_llm.adapters.bedrock.llm_model_router import LLMModelRouter
from eo_llm.adapters.bedrock.types import RouteDecider
from eo_llm.document_store import load_document_bytes
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import GraphState, dump_state, GraphStateModel
from eo_llm.prompts import get_document_location_prompt, get_router_prompt
from eo_llm.stream.decision_reasoning import emit_decision_reasoning

logger = logging.getLogger("eo_llm.orchestrator")

_TOOLS_INFO_MARKERS: tuple[str, ...] = (
    "what tools",
    "which tools",
    "list all tools",
    "list the tools",
    "all tools",
    "available tools",
    "tools do you have",
    "tools are available",
    "tools can you",
    "what can you do",
    "what are your capabilities",
    "your capabilities",
    "what are your tools",
    "your tools",
    "show me the tools",
    "show me your tools",
    "how does the",
    "how do the",
    "what data sources",
    "what questions can i ask",
)


def _is_tools_info_query(query: str) -> bool:
    """True when the current user message is asking about tools/capabilities."""
    q = (query or "").lower().strip()
    if not q:
        return False
    return any(marker in q for marker in _TOOLS_INFO_MARKERS)


def _keyword_domains(query: str) -> list[str]:
    """Deterministic fallback routing when Bedrock routing is unavailable."""
    q = (query or "").lower()

    if _is_tools_info_query(q):
        return ["tools_info"]

    out: list[str] = []
    if any(k in q for k in ("flood", "inondation", "water", "river", "streamflow", "discharge", "drought")):
        out.append("flood_damage")
    if any(k in q for k in ("fire", "wildfire", "burn", "incendie")):
        out.append("fire_detection")
    if any(k in q for k in ("disaster", "earthquake", "storm", "cyclone", "hurricane", "event")):
        out.append("disaster_detection")
    if any(k in q for k in ("road", "bridge", "hospital", "infrastructure", "route", "itinerary", "building", "bdtopo")):
        out.append("infrastructure")
    if any(k in q for k in ("bdtopo",)) and any(k in q for k in ("flood", "inondation", "water")):
        if "flood_damage" not in out:
            out.append("flood_damage")
    if any(k in q for k in ("satellite", "imagery", "image", "stac", "catalog", "maxar")):
        out.append("stac")
    return out


def _keyword_routing_reasoning(query: str, domains: list[str]) -> str:
    if not domains:
        return "I couldn't map this request to a specialist domain, so I'll try web search."
    q = (query or "").strip()
    if q:
        return f"User is asking about {q[:120]}."
    return "User is asking for geospatial analysis and I'll use the matching specialist tools."


def _is_document_query(query: str) -> bool:
    q = (query or "").lower()
    markers = (
        "document",
        "pdf",
        "uploaded file",
        "attached file",
        "in the file",
        "in the document",
    )
    return any(marker in q for marker in markers)


def _needs_document_location_resolution(query: str) -> bool:
    q = (query or "").lower()
    phrases = (
        "location in the document",
        "location in document",
        "that location",
        "the location there",
        "in that city",
    )
    return any(p in q for p in phrases)


class OrchestratorNode(GraphNode):
    node_name = "orchestrator"
    status_stage = "planning"
    status_message = "Planning your request..."

    async def route_domains(self, *, query: str) -> DomainRouteDecision:
        system_prompt, user_prompt = get_router_prompt(query=query)
        decision = await LLMModelRouter().call_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=DomainRouteDecision,
            schema_name="domain_route_decision",
            schema_description="Routing decision for EO_LLM orchestrator",
            max_tokens=500,
            chat_history=get_chat_history(),
        )
        return decision

    async def run(self, s: GraphStateModel) -> GraphState:
        user_msg = (s.user_query or s.query or "").strip()

        if not user_msg:
            s.intent = "empty"
            s.next_step = "finalize_direct"
            s.final_answer = "Please provide a question."
            s.answer_source = "domain_tools"
            return dump_state(s)

        if (
            not (s.place_hint or "").strip()
            and isinstance(s.document_ref, dict)
            and s.document_ref
            and _needs_document_location_resolution(user_msg)
        ):
            place_from_doc = await self._extract_location_from_document(
                query=user_msg,
                document_ref=dict(s.document_ref),
            )
            if place_from_doc:
                s.place_hint = place_from_doc

        route_query = user_msg
        if s.place_hint:
            route_query = f"{user_msg}\nImplicit location context: {s.place_hint}"

        try:
            decision = await self.route_domains(query=route_query)
            selected_domains = [d for d in decision.domains if d != "websearch_only"]
            emit_decision_reasoning(
                "route_domains",
                decision.reasoning,
                domains=selected_domains,
                confidence=decision.confidence,
                execution_mode=decision.execution_mode,
            )
        except Exception as exc:
            logger.warning(
                "Bedrock route_domains failed (%s); falling back to keyword routing", exc
            )
            selected_domains = _keyword_domains(user_msg)
            emit_decision_reasoning(
                "route_keyword_fallback",
                _keyword_routing_reasoning(user_msg, selected_domains),
                domains=selected_domains,
            )

        if "tools_info" in selected_domains and not _is_tools_info_query(user_msg):
            selected_domains = [d for d in selected_domains if d != "tools_info"]

        if isinstance(s.document_ref, dict) and s.document_ref and _is_document_query(user_msg):
            if "document_qa" not in selected_domains:
                selected_domains.append("document_qa")

        s.intent = "data_or_analysis"
        s.selected_domains = selected_domains
        s.next_step = "route"
        return dump_state(s)


    async def _extract_location_from_document(
        self, *, query: str, document_ref: dict[str, Any]
    ) -> str:
        """Resolve an implicit place reference from uploaded document context."""
    
        doc_bytes = load_document_bytes(document_ref)
        if not doc_bytes:
            raise ValueError("Uploaded document is empty.")

        neutral_name = str(document_ref.get("neutral_name") or "Uploaded Document").strip()
        format_value = str(document_ref.get("format") or "pdf").strip().lower() or "pdf"
        user_prompt = (query or "").strip() or "Summarize this document."

        response = await LLMModelRouter().call_structured(
            system_prompt=get_document_location_prompt(query=query),
            user_prompt=user_prompt,
            response_model=LocationHint,
            schema_name="location_hint",
            schema_description="Location inferred from uploaded document and query",
            max_tokens=120,
            chat_history=get_chat_history(),
        )
        return response.place_query.strip() if response else ""


orchestrator_node = OrchestratorNode()
