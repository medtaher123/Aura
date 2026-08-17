"""Flood damage domain node."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import DomainTool, ToolPlanDomainNode
from eo_llm.graph.nodes.helpers import LocationContext, omit_none


class FloodDamageNode(ToolPlanDomainNode):
    domain_name = "flood_damage"
    status_message = "Analyzing floods..."
    tools = [
        #"get_terrazard_available_dates_tool",
        "get_terrazard_flood_briefing_tool",
        DomainTool(
            "get_terrazard_flood_damage_tool",
            required_user_inputs=("bounding_box",),
        ),
        "get_terrazard_hazard_map_tool",
        "geoserver_risk_mask_tool",
        "flood_damage_city_tool",
        "flood_depth_damage_tool",
        "streamflow_forecast_tool",
        "estimate_surface_water_ingress_tool",
        "bdtopo_visualize_tool",
    ]

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        coords = ctx.known_coords()
        display = ctx.display_name or None
        return {
            "get_terrazard_available_dates_tool": omit_none(
                {
                    "location": display,
                    **coords,
                }
            ),
            "get_terrazard_hazard_map_tool": omit_none(
                {
                    "location": display,
                    **coords,
                }
            ),
            "get_terrazard_flood_damage_tool": omit_none(
                {
                    "bbox": ctx.bbox_list,
                }
            ),
            "geoserver_risk_mask_tool": omit_none(
                {
                    "risk_type": "flood",
                    **coords,
                    "location": display,
                }
            ),
            "streamflow_forecast_tool": omit_none({**coords}),
            "estimate_surface_water_ingress_tool": omit_none(
                {
                    **coords,
                    "location_input": display,
                }
            ),
            "flood_damage_city_tool": omit_none(
                {
                    "city": display,
                    "depth_m": 1.0,
                }
            ),
            "flood_depth_damage_tool": omit_none(
                {
                    "country": ctx.country_name or None,
                    "depth_m": 1.0,
                    "asset_class": "residential",
                }
            ),
            "bdtopo_visualize_tool": omit_none(
                {
                    "input_mode": "place_name" if display else ("point" if coords else None),
                    **coords,
                    "place_name": display,
                    "radius_m": 3000,
                    "themes": [
                        "buildings",
                        "land_use_vegetation",
                        "transport",
                        "hydro_surface",
                        "administratif",
                    ],
                }
            ),
        }


flood_damage_node = FloodDamageNode()
