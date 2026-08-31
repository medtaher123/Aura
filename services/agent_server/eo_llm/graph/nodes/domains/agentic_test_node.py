"""Agentic domain node for exercising the iterative LLM tool-use loop.

Includes native user-input tools so you can validate pause/resume behavior
alongside simple tools like ``calculator``.
"""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import AgenticDomainNode, ProviderTools
from eo_llm.graph.nodes.helpers import LocationContext


class AgenticTestNode(AgenticDomainNode):
    """Sandbox domain backed by the agentic tool loop."""

    domain_name = "agentic_test"
    status_message = "Running agentic tool loop..."
    tools = [
        ProviderTools("native"),
        ProviderTools("nominatim"),
    ]

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        return {}


agentic_test_node = AgenticTestNode()
