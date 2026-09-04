"""Disaster detection domain node."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import AgenticDomainNode, ModuleTools
from eo_llm.graph.nodes.helpers import LocationContext, omit_none


class DisasterDetectionNode(AgenticDomainNode):
    domain_name = "disaster_detection"
    status_message = "Querying disaster events..."
    tools = [
        ModuleTools(
            "hazards",
            include=(
                "query_disaster_events_tool",
                "clms_land_cover_exposure_tool",
                "cems_rapid_mapping_events_tool",
            ),
        ),
    ]

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        coords = ctx.known_coords()
        display = ctx.display_name or None
        return {
            "query_disaster_events_tool": omit_none(
                {
                    "country_name": ctx.country_name or None,
                    **coords,
                    "location": display,
                }
            ),
            "clms_land_cover_exposure_tool": omit_none(
                {
                    **coords,
                    "city_name": display,
                }
            ),
            "cems_rapid_mapping_events_tool": omit_none(
                {
                    **coords,
                    "location": display,
                }
            ),
        }


disaster_detection_node = DisasterDetectionNode()
