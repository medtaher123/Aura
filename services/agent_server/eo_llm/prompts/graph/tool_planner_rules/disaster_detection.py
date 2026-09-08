"""Disaster detection domain tool selection rules."""

DISASTER_DETECTION_TOOL_RULES: tuple[str, ...] = (
    "Use query_disaster_events_tool for historical disaster EVENTS (storms, droughts, earthquakes, floods in EMDAT sense).",
    "Use clms_land_cover_exposure_tool for land-cover exposure analysis tied to disaster or environmental impact context.",
    "Use cems_rapid_mapping_events_tool for CEMS rapid mapping, emergency mapping, or activation-style disaster mapping requests.",
    "Never use query_disaster_events_tool for active fire detections; route those to fire_detection.",
    "Never use weather-only tools for disaster event history.",
    "disaster_type accepts a list of strings when filtering event types (e.g. [\"storm\", \"drought\"]).",
)

DISASTER_DETECTION_EXAMPLES: tuple[str, ...] = (
    "Query: storm events in Germany 2010-2025\n"
    "Plan: 1 step — query_disaster_events_tool with disaster_type including storm.",
)
