"""Transitions after router node."""

from __future__ import annotations

from typing import Union

from eo_llm.graph.state import GraphState


def choose_after_router(state: GraphState) -> Union[str, list[str]]:
    """Return selected domain labels, or web fallback label.

    LangGraph will route to all labels in the returned list.
    """
    selected_domains = list(state.get("selected_domains", []))
    if selected_domains:
        return selected_domains
    return "websearch_only"
