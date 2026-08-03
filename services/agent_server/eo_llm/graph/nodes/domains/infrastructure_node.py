"""Infrastructure domain node."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import ToolPlanDomainNode
from eo_llm.graph.nodes.helpers import LocationContext


class InfrastructureNode(ToolPlanDomainNode):
    domain_name = "infrastructure"
    status_message = "Querying infrastructure..."
    tools = [
        "infrastructure_query_tool",
        "get_route_info",
        "bdtopo_visualize_tool",
        "bdtopo_query_tool",
        "bdtopo_intersection_tool",
        "bdtopo_thematic_explain_tool"
    ] # type: ignore[assignment]

    @property
    def missing_location_message(self) -> str:
        return "Missing resolved lat/lon; infrastructure tool not called."

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        lat = float(ctx.lat)  # type: ignore[arg-type]
        lon = float(ctx.lon)  # type: ignore[arg-type]
        return {
            "infrastructure_query_tool": {
                "lat": lat,
                "lon": lon,
                "location": ctx.display_name or None,
                "radius_km": 25.0,
            },
            "get_route_info": {},
            "bdtopo_visualize_tool": {
                "input_mode": "place_name" if ctx.display_name else "point",
                "lat": lat,
                "lon": lon,
                "place_name": ctx.display_name or None,
                "radius_m": 3000,
                "themes": ["buildings", "transport", "activity_zones"],
            },
            "bdtopo_query_tool": {
                "lat": lat,
                "lon": lon,
                "place_name": ctx.display_name or None,
                "radius_m": 3000,
                "themes": ["buildings", "transport", "activity_zones"],
            },
            "bdtopo_intersection_tool": {
                "lat": lat,
                "lon": lon,
                "place_name": ctx.display_name or None,
                "radius_m": 3000,
                "themes": ["buildings", "transport", "activity_zones"],
            },
            "bdtopo_visualize_tool": {
                "input_mode": "place_name" if ctx.display_name else "point",
                "lat": lat,
                "lon": lon,
                "place_name": ctx.display_name or None,
                "radius_m": 3000,
                "themes": ["buildings", "transport", "activity_zones"],
            },
            "bdtopo_thematic_explain_tool": {
                "lat": lat,
                "lon": lon,
                "place_name": ctx.display_name or None,
                "radius_m": 3000,
                "themes": ["buildings", "transport", "activity_zones"],
            },
        }


infrastructure_node = InfrastructureNode()
