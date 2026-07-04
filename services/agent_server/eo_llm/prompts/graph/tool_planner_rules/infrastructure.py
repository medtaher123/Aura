"""Infrastructure domain tool selection rules."""

INFRASTRUCTURE_TOOL_RULES: tuple[str, ...] = (
    "Use infrastructure_query_tool for hospitals, critical infrastructure, buildings, or facilities near a location.",
    "Use get_route_info for itineraries, driving routes, or directions between named places.",
    "Do not use STAC or flood tools for pure infrastructure or routing questions.",
)

INFRASTRUCTURE_EXAMPLES: tuple[str, ...] = (
    "Query: what infrastructure is near Paris within 10 km\n"
    "Plan: 1 step — infrastructure_query_tool.",
    "Query: route from Paris to Lyon\n"
    "Plan: 1 step — get_route_info.",
)
