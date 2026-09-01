"""Flood / water domain tool selection rules."""

FLOOD_DAMAGE_TOOL_RULES: tuple[str, ...] = (
    "Use get_terrazard_flood_briefing_tool for observed satellite flood history, severity, depth profile, extent, and map in one step.",
    "Use get_terrazard_flood_damage_tool when the user asks for flood damage, economic loss, or exposed buildings from TerraZard observed floods with BDTOPO land use.",
    "The get_terrazard_flood_damage_tool requires a small bouding box around the flood area, so use request_bbox_user_input to get the user to draw a bounding box around the flood area.",
    "the get_terrazard_flood_damage_tool requires a user-drawn bounding box, aslways ask the user even if you already have a bounding box.",
    "the get_terrazard_flood_damage_tool calls the get_terrazard_flood_briefing_tool internally, so you don't need to call it separately.",
    "Use bdtopo_visualize_tool to map or visualize BDTOPO buildings, land cover, roads, hydro, or boundaries around a flood-affected area.",
    "Use get_terrazard_hazard_map_tool only when the user explicitly asks for a map on a specific known observation date.",
    "Use geoserver_risk_mask_tool for water risk, flood risk, flood mask, water mask, risk map, or show risk in [place].",
    "Use streamflow_forecast_tool for river discharge, streamflow, water-level forecast, or river flood forecast requests.",
    "Use flood_damage_city_tool when the user asks for total flood damage for a CITY at a given depth (e.g. Lyon at 3 m).",
    "Use flood_depth_damage_tool for country-level damage per m² at a depth, not total city damage.",
    "flood_depth_damage_tool requires asset_class (residential, commercial, industrial, agriculture, infrastructure, transport); default to residential when unspecified.",
    "Use estimate_surface_water_ingress_tool ONLY for ingress risk, surface water ingress, or water accumulation points.",
    "Do NOT use geoserver_risk_mask_tool for historical disaster event lists; that belongs in disaster_detection.",
    "Prefer one primary tool unless the query clearly needs complementary data (e.g. risk map + streamflow forecast).",
)

FLOOD_DAMAGE_EXAMPLES: tuple[str, ...] = (
    "Exemple 1: \nQuery: show me floods near Lyon last winter\n"
    "Plan: 2 steps — 1. request_location_user_input with the argument 'Lyon' to get the location of Lyon and check if its valid and unique, if its not unique the user will be automatially prompted to choose from the list of candidates, "
    "2. get_terrazard_flood_briefing_tool with winter date range.",

    "Exemple 2: \nQuery: calculate flood damage in Lyon last winter"
    "Plan: 2 steps — 1. request_bbox_user_input to get the user to draw a bounding box around the flood area, then"
    "2. get_terrazard_flood_briefing_tool with winter date range.",

)
