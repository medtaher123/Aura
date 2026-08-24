"""System prompt for agentic domain nodes (iterative tool calling)."""

from __future__ import annotations

from eo_llm.prompts.builder import PromptSpec, render_system
from eo_llm.prompts.shared.grounding import GROUNDING_RULES
from eo_llm.prompts.shared.user_experience import USER_EXPERIENCE_RULES
from eo_llm.prompts.graph.tool_planner_rules import DOMAIN_TOOL_RULES

_AGENT_RULES: tuple[str, ...] = (
    *GROUNDING_RULES,
    *USER_EXPERIENCE_RULES,
    "You are AURA operating inside a single domain workflow.",
    "Use the provided tools to gather evidence and answer the user query.",
    "Call one or more tools when needed; read tool results before deciding next steps.",
    "When you have enough information, reply with a concise final answer in plain language.",
    "Do not invent tool outputs or geospatial facts.",
    "Prefer domain-specific tools first; use web_search_tool only for recent context gaps.",
    "If a tool requests user input (location, bounding box), call it and stop — do not guess.",
)


def get_domain_agent_prompt(*, domain: str, allowed_tools: list[str]) -> str:
    domain_rules = DOMAIN_TOOL_RULES.get(domain, ())
    spec = PromptSpec(
        role="You are AURA's domain analyst.",
        task=f"Answer the user query for the {domain} domain using available tools.",
        rules=(*_AGENT_RULES, *domain_rules),
        examples=(),
        include_schema_rules=False,
    )
    return render_system(
        spec,
        domain=domain,
        allowed_tools=", ".join(allowed_tools),
    )
