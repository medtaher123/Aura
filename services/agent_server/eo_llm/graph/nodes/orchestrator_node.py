"""Orchestrator node: sets high-level plan."""

from __future__ import annotations

import logging

from eo_llm.adapters.agentcore_adapter import AgentCoreAdapter
from eo_llm.graph.state import GraphState, dump_state, validate_state

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
    """Deterministic fallback routing when AgentCore routing is unavailable."""
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
    if any(k in q for k in ("road", "bridge", "hospital", "infrastructure", "route", "itinerary", "building")):
        out.append("infrastructure")
    if any(k in q for k in ("satellite", "imagery", "image", "stac", "catalog", "maxar")):
        out.append("stac")
    return out


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


def orchestrator_node(state: GraphState) -> GraphState:
    s = validate_state(state)
    user_msg = (s.user_query or s.query or "").strip()

    if not user_msg:
        s.intent = "empty"
        s.next_step = "finalize_direct"
        s.final_answer = "Please provide a question."
        s.answer_source = "domain_tools"
        return dump_state(s)

    adapter = AgentCoreAdapter()
    if (
        not (s.place_hint or "").strip()
        and isinstance(s.document_ref, dict)
        and s.document_ref
        and _needs_document_location_resolution(user_msg)
    ):
        place_from_doc = adapter.extract_location_from_document(
            query=user_msg,
            document_ref=dict(s.document_ref),
        )
        if place_from_doc:
            s.place_hint = place_from_doc

    route_query = user_msg
    if s.place_hint:
        route_query = f"{user_msg}\nImplicit location context: {s.place_hint}"

    try:
        decision = adapter.route_domains(query=route_query)
        selected_domains = [d for d in decision.domains if d != "websearch_only"]
    except Exception as exc:
        logger.warning(
            "AgentCore route_domains failed (%s); falling back to keyword routing", exc
        )
        selected_domains = _keyword_domains(user_msg)


    if "tools_info" in selected_domains and not _is_tools_info_query(user_msg):
        selected_domains = [d for d in selected_domains if d != "tools_info"]

    if isinstance(s.document_ref, dict) and s.document_ref and _is_document_query(user_msg):
        if "document_qa" not in selected_domains:
            selected_domains.append("document_qa")

    s.intent = "data_or_analysis"
    s.selected_domains = selected_domains
    s.next_step = "route"
    return dump_state(s)
