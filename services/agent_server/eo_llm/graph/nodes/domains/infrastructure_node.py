"""Infrastructure domain node."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import ToolPlanDomainNode
from eo_llm.graph.nodes.helpers import LocationContext


class InfrastructureNode(ToolPlanDomainNode):
    @property
    def domain_name(self) -> str:
        return "infrastructure"

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
        }


infrastructure_node = InfrastructureNode()
