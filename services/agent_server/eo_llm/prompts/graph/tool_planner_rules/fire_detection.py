"""Fire detection domain tool selection rules."""

FIRE_DETECTION_TOOL_RULES: tuple[str, ...] = (
    "Use detect_fire_tool for fire detections, wildfires, and active fire events near a location.",
    "Use clms_burnt_area_impact_tool when the query mentions burnt area, burned area, zone brulee, or CLMS burnt-area impact.",
    "Never use disaster event tools for fires.",
    "Prefer one tool unless the query explicitly asks for both fire detections and burnt-area impact analysis.",
)

FIRE_DETECTION_EXAMPLES: tuple[str, ...] = (
    "Query: are there fires in Berlin in 2024\n"
    "Plan: 1 step — detect_fire_tool.",
    "Query: CLMS burnt area impact near Marseille\n"
    "Plan: 1 step — clms_burnt_area_impact_tool.",
)
