"""Transition after a domain node: pause for user input or continue."""

from __future__ import annotations

from typing import Literal

from eo_llm.graph.state import GraphState


def choose_after_domain(state: GraphState) -> Literal["aggregator", "end"]:
    """Route to END when the domain paused for user input; else aggregator."""
    if state.get("stopped_for_user_input"):
        return "end"
    return "aggregator"
