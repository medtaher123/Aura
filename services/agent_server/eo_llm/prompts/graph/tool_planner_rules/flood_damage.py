"""Flood / water domain tool selection rules."""

FLOOD_DAMAGE_TOOL_RULES: tuple[str, ...] = (
    "Use get_terrazard_flood_briefing_tool for observed satellite flood history, severity, depth profile, extent, and map in one step.",
    "Use get_terrazard_hazard_map_tool only when the user explicitly asks for a map on a specific known observation date.",
    "Use geoserver_risk_mask_tool for water risk, flood risk, flood mask, water mask, risk map, or show risk in [place].",
    "Use streamflow_forecast_tool for river discharge, streamflow, water-level forecast, or river flood forecast requests.",
    "Use flood_damage_city_tool when the user asks for total flood damage for a CITY at a given depth (e.g. Lyon at 3 m).",
    "Use flood_depth_damage_tool for country-level damage per m² at a depth, not total city damage.",
    "Use estimate_surface_water_ingress_tool ONLY for ingress risk, surface water ingress, or water accumulation points.",
    "Do NOT use geoserver_risk_mask_tool for historical disaster event lists; that belongs in disaster_detection.",
    "Prefer one primary tool unless the query clearly needs complementary data (e.g. risk map + streamflow forecast).",
)

FLOOD_DAMAGE_EXAMPLES: tuple[str, ...] = (
    "Query: show me floods near Lyon last winter\n"
    "Plan: 1 step — get_terrazard_flood_briefing_tool with winter date range.",
    "Query: map TerraZard flood polygons in Paris on 2024-03-15\n"
    "Plan: 1 step — get_terrazard_flood_briefing_tool with observation_date 2024-03-15.",
    "Query: show me water risk in Paris in January\n"
    "Plan: 1 step — geoserver_risk_mask_tool with risk_type water and January date range.",
    "Query: streamflow forecast for the Seine near Paris\n"
    "Plan: 1 step — streamflow_forecast_tool.",
)
