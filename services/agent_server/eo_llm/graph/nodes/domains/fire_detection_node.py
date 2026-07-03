"""Fire detection domain node."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import ToolPlanDomainNode
from eo_llm.graph.nodes.helpers import LocationContext


class FireDetectionNode(ToolPlanDomainNode):
    @property
    def domain_name(self) -> str:
        return "fire_detection"

    @property
    def missing_location_message(self) -> str:
        return "Missing resolved lat/lon; fire tool not called."

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        lat = float(ctx.lat)  # type: ignore[arg-type]
        lon = float(ctx.lon)  # type: ignore[arg-type]
        location = ctx.display_name or None
        return {
            "detect_fire_tool": {
                "lat": lat,
                "lon": lon,
                "location": location,
            },
            "clms_burnt_area_impact_tool": {
                "lat": lat,
                "lon": lon,
                "location": location,
            },
        }


fire_detection_node = FireDetectionNode()
