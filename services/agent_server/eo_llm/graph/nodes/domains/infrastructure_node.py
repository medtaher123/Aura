"""Infrastructure domain node."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import ModuleTools, ToolPlanDomainNode
from eo_llm.graph.nodes.helpers import LocationContext, omit_none


class InfrastructureNode(ToolPlanDomainNode):
    domain_name = "infrastructure"
    status_message = "Querying infrastructure..."
    tools = [
        ModuleTools(
            "geospatial",
            include=(
                "infrastructure_query_tool",
                "bdtopo_visualize_tool",
                "bdtopo_query_tool",
                "bdtopo_intersection_tool",
                "bdtopo_thematic_explain_tool",
            ),
        ),
        ModuleTools("utility", include=("get_route_info",)),
        # TODO: inlude bdtopo mcp
    ]

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        coords = ctx.known_coords()
        display = ctx.display_name or None
        bdtopo_base = omit_none(
            {
                "input_mode": "place_name" if display else ("point" if coords else None),
                **coords,
                "place_name": display,
                "radius_m": 3000,
                "themes": ["buildings", "transport", "activity_zones"],
            }
        )
        return {
            "infrastructure_query_tool": omit_none(
                {
                    **coords,
                    "location": display,
                    "radius_km": 25.0,
                }
            ),
            "get_route_info": {},
            "bdtopo_visualize_tool": dict(bdtopo_base),
            "bdtopo_query_tool": omit_none(
                {
                    **coords,
                    "place_name": display,
                    "radius_m": 3000,
                    "themes": ["buildings", "transport", "activity_zones"],
                }
            ),
            "bdtopo_intersection_tool": omit_none(
                {
                    **coords,
                    "place_name": display,
                    "radius_m": 3000,
                    "themes": ["buildings", "transport", "activity_zones"],
                }
            ),
            "bdtopo_thematic_explain_tool": omit_none(
                {
                    **coords,
                    "place_name": display,
                    "radius_m": 3000,
                    "themes": ["buildings", "transport", "activity_zones"],
                }
            ),
        }


infrastructure_node = InfrastructureNode()
