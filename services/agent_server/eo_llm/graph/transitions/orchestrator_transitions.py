"""Transitions after orchestrator node."""

from __future__ import annotations

from typing import Literal

from eo_llm.graph.state import GraphState


def choose_after_orchestrator(state: GraphState) -> Literal["route", "finalize_direct"]:
    label = state.get("next_step", "route")
    if label == "finalize_direct":
        return "finalize_direct"
    return "route"
