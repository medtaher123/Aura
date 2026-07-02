"""Router node: executes orchestrator-selected domain routing."""

from __future__ import annotations

from eo_llm.graph.state import GraphState, dump_state, validate_state


def router_node(state: GraphState) -> GraphState:
    s = validate_state(state)
    # Routing is owned by orchestrator/AgentCore policy layer.
    # Router only dispatches based on pre-computed selected_domains.
    s.next_step = "run_domains" if s.selected_domains else "websearch_only"
    return dump_state(s)
