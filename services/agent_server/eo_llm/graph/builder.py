"""Graph definition (nodes + edges)."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from eo_llm.graph.state import GraphState
from eo_llm.graph.nodes.gateway_node import gateway_node
from eo_llm.graph.nodes.orchestrator_node import orchestrator_node
from eo_llm.graph.nodes.location_gate_node import location_gate_node
from eo_llm.graph.nodes.location_response_node import location_response_node
from eo_llm.graph.nodes.router_node import router_node
from eo_llm.graph.nodes.domains.flood_damage_node import flood_damage_node
from eo_llm.graph.nodes.domains.fire_detection_node import fire_detection_node
from eo_llm.graph.nodes.domains.disaster_detection_node import disaster_detection_node
from eo_llm.graph.nodes.domains.document_qa_node import document_qa_node
from eo_llm.graph.nodes.domains.infrastructure_node import infrastructure_node
from eo_llm.graph.nodes.domains.stac_node import stac_node
from eo_llm.graph.nodes.domains.tools_info_node import tools_info_node
from eo_llm.graph.nodes.aggregator_node import aggregator_node
from eo_llm.graph.nodes.web_search_node import web_search_node
from eo_llm.graph.nodes.finalizer_node import finalizer_node
from eo_llm.graph.transitions.orchestrator_transitions import (
    choose_after_orchestrator,
)
from eo_llm.graph.transitions.router_transitions import choose_after_router
from eo_llm.graph.transitions.location_transitions import choose_after_location_gate
from eo_llm.graph.transitions.aggregator_transitions import choose_after_aggregator
from eo_llm.graph.transitions.domain_transitions import choose_after_domain


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("gateway", gateway_node)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("location_gate", location_gate_node)
    graph.add_node("location_response", location_response_node)
    graph.add_node("router", router_node)
    graph.add_node("flood_damage", flood_damage_node)
    graph.add_node("fire_detection", fire_detection_node)
    graph.add_node("disaster_detection", disaster_detection_node)
    graph.add_node("document_qa", document_qa_node)
    graph.add_node("infrastructure", infrastructure_node)
    graph.add_node("stac", stac_node)
    graph.add_node("tools_info", tools_info_node)
    graph.add_node("aggregator", aggregator_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("finalizer", finalizer_node)

    graph.set_entry_point("gateway")
    graph.add_edge("gateway", "orchestrator")

    graph.add_conditional_edges(
        "orchestrator",
        choose_after_orchestrator,
        {"route": "location_gate", "finalize_direct": "finalizer"},
    )

    graph.add_conditional_edges(
        "location_gate",
        choose_after_location_gate,
        {"router": "router", "location_response": "location_response"},
    )

    graph.add_edge("location_response", END)

    graph.add_conditional_edges(
        "router",
        choose_after_router,
        {
            "flood_damage": "flood_damage",
            "fire_detection": "fire_detection",
            "disaster_detection": "disaster_detection",
            "document_qa": "document_qa",
            "infrastructure": "infrastructure",
            "stac": "stac",
            "tools_info": "tools_info",
            "websearch_only": "web_search",
        },
    )

    # Tool-plan domains may pause for user input; otherwise continue to aggregator.
    # tools_info returns a formatted catalog and skips aggregation/LLM compose.
    _domain_pause_targets = {"aggregator": "aggregator", "end": END}
    for _domain in (
        "flood_damage",
        "fire_detection",
        "disaster_detection",
        "document_qa",
        "infrastructure",
        "stac",
    ):
        graph.add_conditional_edges(
            _domain,
            choose_after_domain,
            _domain_pause_targets,
        )
    graph.add_edge("tools_info", "finalizer")

    graph.add_edge("web_search", "aggregator")

    graph.add_conditional_edges(
        "aggregator",
        choose_after_aggregator,
        {"finalize": "finalizer", "web_search": "web_search"},
    )

    graph.add_edge("finalizer", END)
    return graph.compile()
