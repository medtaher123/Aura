"""Domain-to-tool registry used by domain nodes."""

from __future__ import annotations

DOMAIN_TOOLS: dict[str, list[str]] = {
    "flood_damage": [
        "geoserver_risk_mask_tool",
        "flood_damage_city_tool",
        "flood_depth_damage_tool",
        "streamflow_forecast_tool",
        "estimate_surface_water_ingress_tool",
    ],
    "fire_detection": ["detect_fire_tool"],
    "disaster_detection": [
        "query_disaster_events_tool",
    ],
    "infrastructure": [
        "infrastructure_query_tool",
        "get_route_info",
    ],
    "stac": [
        "query_stac_catalog",
        "maxar_open_data_imagery_tool",
    ],
}
