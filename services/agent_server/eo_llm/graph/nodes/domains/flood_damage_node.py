"""Flood damage domain node."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.nodes.domain_base import ToolPlanDomainNode
from eo_llm.graph.nodes.helpers import LocationContext


class FloodDamageNode(ToolPlanDomainNode):
    domain_name = "flood_damage"
    status_message = "Analyzing flood damage..."
    tools = [
        #"get_terrazard_available_dates_tool",
        "get_terrazard_flood_briefing_tool",
        "get_terrazard_hazard_map_tool",
        "geoserver_risk_mask_tool",
        "flood_damage_city_tool",
        "flood_depth_damage_tool",
        "streamflow_forecast_tool",
        "estimate_surface_water_ingress_tool",
    ]

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        lat = float(ctx.lat)  # type: ignore[arg-type]
        lon = float(ctx.lon)  # type: ignore[arg-type]
        return {
            "get_terrazard_available_dates_tool": {
                "location": ctx.display_name or None,
                "lat": lat,
                "lon": lon,
            },
            "get_terrazard_hazard_map_tool": {
                "location": ctx.display_name or None,
                "lat": lat,
                "lon": lon,
            },
            "geoserver_risk_mask_tool": {
                "risk_type": "flood",
                "lat": lat,
                "lon": lon,
                "location": ctx.display_name or None,
            },
            "streamflow_forecast_tool": {
                "lat": lat,
                "lon": lon,
            },
            "estimate_surface_water_ingress_tool": {
                "lat": lat,
                "lon": lon,
                "location_input": ctx.display_name or None,
            },
            "flood_damage_city_tool": {
                "city": ctx.display_name or None,
                "depth_m": 1.0,
            },
            "flood_depth_damage_tool": {
                "country": ctx.country_name or None,
                "depth_m": 1.0,
            },
        }


flood_damage_node = FloodDamageNode()
