"""Emit a user-visible pause when multiple geocoding matches exist."""

from __future__ import annotations

from eo_llm.graph.state import GraphState, dump_state, validate_state


def location_response_node(state: GraphState) -> GraphState:
    s = validate_state(state)
    q = s.location_query or s.query
    payload = (s.needs_input or {}).get("location") or {}
    cands = list(payload.get("candidates") or s.location_candidates)

    lines = [
        f"Several places match “{q}”. Reply by resuming with "
        "`user_inputs.location` set to the chosen option "
        "(or `confirmed_location_index` 0-based).",
        "",
    ]
    for i, c in enumerate(cands[:8]):
        name = c.get("display_name") or c.get("name") or str(c)
        lines.append(f"  [{i}] {name}")

    s.final_answer = "\n".join(lines)
    s.answer_source = "domain_tools"
    return dump_state(s)
