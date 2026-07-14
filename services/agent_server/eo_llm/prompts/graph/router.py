"""Domain routing prompts for the graph orchestrator."""

from __future__ import annotations

from eo_llm.prompts.builder import PromptSpec, render_system_user
from eo_llm.prompts.shared.grounding import GROUNDING_RULES
from eo_llm.prompts.shared.schema import SCHEMA_OUTPUT_RULES
from eo_llm.prompts.shared.user_experience import USER_EXPERIENCE_RULES

ROUTER_DOMAINS = (
    "flood_damage",
    "fire_detection",
    "disaster_detection",
    "infrastructure",
    "stac",
    "document_qa",
    "tools_info",
    "websearch_only",
)

_ROUTER_RULES: tuple[str, ...] = (
    *GROUNDING_RULES,
    *USER_EXPERIENCE_RULES,
    *SCHEMA_OUTPUT_RULES,
    "Route the user query to one or more domains from the allowed list.",
    f"Allowed domains: {', '.join(ROUTER_DOMAINS)}.",
    "Prefer specific domain(s) when the intent is clear.",
    "Use websearch_only only when no EO domain fits.",
    "Use tools_info when the user asks what tools/capabilities are available, how a tool works, what data sources are used, or what questions they can ask.",
    "Do NOT use tools_info for greetings, thanks, or casual chat.",
    "Use document_qa when the user asks about uploaded/attached document contents.",
    "Streamflow, river discharge, and water-level forecast requests belong to flood_damage.",
    "STAC is for satellite catalog/discovery/imagery tasks, not hydrological forecasts.",
    "CLMS burnt-area impact requests belong to fire_detection.",
    "CLMS land-cover exposure and CEMS rapid-mapping requests belong to disaster_detection.",
    "Historical disaster events (storms, droughts, earthquakes) belong to disaster_detection, not fire_detection.",
    "Active fires and wildfires belong to fire_detection, not disaster_detection.",
    "GeoServer water/flood risk masks and city flood damage belong to flood_damage.",
    "confidence must be in [0, 1].",
    "execution_mode is parallel or sequential.",
    "reasoning must be one short first-person sentence from AURA's point of view.",
    "For routing, describe what the user wants, e.g. 'User is asking for historical flood data in Pas-de-Calais.'",
    "Do not mention domain names, routing mechanics, or confidence in reasoning.",
)

_ROUTER_EXAMPLES: tuple[str, ...] = (
    "Query: show me water risk in Paris in January\n"
    'Domains: ["flood_damage"]',
    "Query: Sentinel-2 images of Casablanca September 2025\n"
    'Domains: ["stac"]',
    "Query: storm events in Germany 2010-2025\n"
    'Domains: ["disaster_detection"]',
    "Query: what tools can detect fires\n"
    'Domains: ["tools_info"]',
    "Query: streamflow forecast for the Amazon River\n"
    'Domains: ["flood_damage"]',
    "Query: hello\n"
    'Domains: ["websearch_only"]',
)

ROUTER_PROMPT = PromptSpec(
    role="You are AURA's routing policy engine.",
    task="Choose the best domain(s) for the user query.",
    rules=_ROUTER_RULES,
    examples=_ROUTER_EXAMPLES,
    include_schema_rules=True,
)


def get_router_prompt(*, query: str) -> tuple[str, str]:
    return render_system_user(ROUTER_PROMPT, query=query)
