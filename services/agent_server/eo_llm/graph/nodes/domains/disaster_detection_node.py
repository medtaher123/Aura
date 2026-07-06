"""Disaster detection domain node."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import ToolPlanDomainNode
from eo_llm.graph.nodes.helpers import LocationContext


class DisasterDetectionNode(ToolPlanDomainNode):
    domain_name = "disaster_detection"
    status_message = "Querying disaster events..."
    tools = [
        "query_disaster_events_tool",
        "clms_land_cover_exposure_tool",
        "cems_rapid_mapping_events_tool",
    ]

    @property
    def missing_location_message(self) -> str:
        return "Missing resolved lat/lon; disaster tool not called."

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        lat = float(ctx.lat)  # type: ignore[arg-type]
        lon = float(ctx.lon)  # type: ignore[arg-type]
        display = ctx.display_name or None
        return {
            "query_disaster_events_tool": {
                "country_name": ctx.country_name or None,
                "lat": lat,
                "lon": lon,
                "location": display,
            },
            "clms_land_cover_exposure_tool": {
                "lat": lat,
                "lon": lon,
                "city_name": display,
            },
            "cems_rapid_mapping_events_tool": {
                "lat": lat,
                "lon": lon,
                "location": display,
            },
        }


disaster_detection_node = DisasterDetectionNode()
