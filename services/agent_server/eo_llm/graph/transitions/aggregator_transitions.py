"""Transitions after aggregator node."""

from __future__ import annotations

from typing import Literal

from eo_llm.graph.state import GraphState


def choose_after_aggregator(state: GraphState) -> Literal["finalize", "web_search"]:
    # Prevent loops: if web results already exist, finalize.
    if state.get("web_results"):
        return "finalize"

    label = state.get("next_step", "web_search")
    if label == "finalize":
        return "finalize"
    return "web_search"
