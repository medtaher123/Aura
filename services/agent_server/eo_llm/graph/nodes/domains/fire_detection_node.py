"""Fire detection domain node."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import AgenticDomainNode, ModuleTools
from eo_llm.graph.nodes.helpers import LocationContext, omit_none


class FireDetectionNode(AgenticDomainNode):
    domain_name = "fire_detection"
    status_message = "Detecting fires..."
    tools = [
        ModuleTools(
            "hazards",
            include=("detect_fire_tool", "clms_burnt_area_impact_tool"),
        ),
    ]

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        location_args = omit_none(
            {
                **ctx.known_coords(),
                "location": ctx.display_name or None,
            }
        )
        return {
            "detect_fire_tool": dict(location_args),
            "clms_burnt_area_impact_tool": dict(location_args),
        }


fire_detection_node = FireDetectionNode()
