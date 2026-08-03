"""Per-domain tool planning prompts."""

from __future__ import annotations

from eo_llm.prompts.builder import PromptSpec, render_system_user
from eo_llm.prompts.shared.grounding import GROUNDING_RULES
from eo_llm.prompts.shared.schema import SCHEMA_OUTPUT_RULES
from eo_llm.prompts.shared.user_experience import USER_EXPERIENCE_RULES
from eo_llm.prompts.graph.tool_planner_rules import DOMAIN_TOOL_RULES
from eo_llm.prompts.graph.tool_planner_rules.disaster_detection import (
    DISASTER_DETECTION_EXAMPLES,
)
from eo_llm.prompts.graph.tool_planner_rules.fire_detection import FIRE_DETECTION_EXAMPLES
from eo_llm.prompts.graph.tool_planner_rules.flood_damage import FLOOD_DAMAGE_EXAMPLES
from eo_llm.prompts.graph.tool_planner_rules.infrastructure import (
    INFRASTRUCTURE_EXAMPLES,
)
from eo_llm.prompts.graph.tool_planner_rules.stac import STAC_EXAMPLES

_BASE_TOOL_PLANNER_RULES: tuple[str, ...] = (
    *GROUNDING_RULES,
    *USER_EXPERIENCE_RULES,
    *SCHEMA_OUTPUT_RULES,
    "Build a concise tool plan with 1-4 steps.",
    "tool_name must be from the allowed tools list only.",
    "Use supported enums exactly (no synonyms).",
    "Prefer practical required_inputs that match runtime data availability.",
    "Prefer tool defaults when reasonable; do not block on optional parameters.",
    "Prefer domain-specific EO tools first; use web_search_tool as a complement for recent news, public context, or gaps EO tools cannot cover.",
    "Do not use web_search_tool alone when a domain EO tool can answer the query.",
    "reasoning must be one short first-person sentence from AURA's point of view.",
    "Describe the next action you will take, starting with 'I' (e.g. 'I have to retrieve observed satellite flood data for November 2023.').",
    "Never use bare imperative verbs like 'Retrieve...' or 'Query...' in reasoning.",
)

_DOMAIN_EXAMPLES: dict[str, tuple[str, ...]] = {
    "flood_damage": FLOOD_DAMAGE_EXAMPLES,
    "fire_detection": FIRE_DETECTION_EXAMPLES,
    "disaster_detection": DISASTER_DETECTION_EXAMPLES,
    "infrastructure": INFRASTRUCTURE_EXAMPLES,
    "stac": STAC_EXAMPLES,
}


def get_tool_planner_prompt(*, domain: str, query: str, allowed_tools: list[str]) -> tuple[str, str]:
    domain_rules = DOMAIN_TOOL_RULES.get(domain, ())
    examples = _DOMAIN_EXAMPLES.get(domain, ())
    spec = PromptSpec(
        role="You are AURA's domain tool planner.",
        task=f"Plan which tools to call for the {domain} domain.",
        rules=(*_BASE_TOOL_PLANNER_RULES, *domain_rules),
        examples=examples,
        include_schema_rules=True,
    )
    return render_system_user(
        spec,
        domain=domain,
        allowed_tools=", ".join(allowed_tools),
        user_query=(query or "").strip(),
    )
