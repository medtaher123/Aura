"""Transitions after location_gate_node."""

from __future__ import annotations

from typing import Literal

from eo_llm.graph.state import GraphState


def choose_after_location_gate(
    state: GraphState,
) -> Literal["router", "location_response"]:
    if state.get("location_phase") == "pause":
        return "location_response"
    return "router"
