"""AURA prompt library for the EO_LLM graph pipeline."""

from eo_llm.prompts.graph import (
    BROWSER_SYSTEM_PROMPT,
    DOCUMENT_QA_SYSTEM,
    get_arg_resolver_prompt,
    get_browser_system_prompt,
    get_browser_user_prompt,
    get_document_location_prompt,
    get_domain_agent_prompt,
    get_finalizer_prompt,
    get_query_location_prompt,
    get_router_prompt,
    get_tool_planner_prompt,
)

__all__ = [
    "BROWSER_SYSTEM_PROMPT",
    "DOCUMENT_QA_SYSTEM",
    "get_arg_resolver_prompt",
    "get_browser_system_prompt",
    "get_browser_user_prompt",
    "get_document_location_prompt",
    "get_domain_agent_prompt",
    "get_finalizer_prompt",
    "get_query_location_prompt",
    "get_router_prompt",
    "get_tool_planner_prompt",
]
