"""Gateway node: normalizes incoming state."""

from __future__ import annotations

from eo_llm.graph.state import GraphState, dump_state, validate_state


def gateway_node(state: GraphState) -> GraphState:
    s = validate_state(state)
    return dump_state(s)
