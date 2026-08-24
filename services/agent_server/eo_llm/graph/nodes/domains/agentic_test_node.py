"""Agentic domain node for exercising the iterative LLM tool-use loop.

Includes native user-input tools so you can validate pause/resume behavior
alongside simple tools like ``calculator``.
"""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import AgenticDomainNode, DomainTool
from eo_llm.graph.nodes.helpers import LocationContext


class AgenticTestNode(AgenticDomainNode):
    """Sandbox domain backed by the agentic tool loop."""

    domain_name = "agentic_test"
    status_message = "Running agentic tool loop..."
    tools = [
        "calculator",
        "request_location_user_input", # type: ignore
        "request_bounding_box_user_input", # type: ignore
        "reverse_geocode", # type: ignore
        "lookup", # type: ignore
        # DomainTool(   
        #     "request_location_user_input",
        #     required_user_inputs=("location",),
        # ),
        # DomainTool(
        #     "request_bounding_box_user_input",
        #     required_user_inputs=("bounding_box",),
        # ),
    ]

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        return {}


agentic_test_node = AgenticTestNode()
