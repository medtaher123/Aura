"""Tool argument resolution prompts."""

from __future__ import annotations

import json
from typing import Any

from eo_llm.prompts.builder import PromptSpec, render_system
from eo_llm.prompts.shared.grounding import GROUNDING_RULES
from eo_llm.prompts.shared.schema import SCHEMA_OUTPUT_RULES
from eo_llm.prompts.shared.temporal import TEMPORAL_RULES

_ARG_RESOLVER_RULES: tuple[str, ...] = (
    *GROUNDING_RULES,
    *TEMPORAL_RULES,
    *SCHEMA_OUTPUT_RULES,
    "Return arguments ready for tool execution.",
    "Use only allowed argument names.",
    "Keep values as JSON strings in value_json.",
    "Resolve conceptual required_inputs to concrete args when possible.",
    "Ensure required argument names are present with valid values.",
    "If a required argument is missing, infer a safe value from context or the tool docstring.",
    "Put unresolved conceptual inputs in unresolved_required_inputs.",
)

_ARG_RESOLVER_EXAMPLES: tuple[str, ...] = (
    "Query: fires in Paris last summer\n"
    "Override default year with last summer dates (YYYY-MM-DD) in start_date/end_date.",
    "Query: water risk in Berlin between January and March 2026\n"
    "Set start_date=2026-01-01 and end_date=2026-03-31 even if candidate args used a different year.",
)

ARG_RESOLVER_PROMPT = PromptSpec(
    role="You are AURA's argument-resolution policy engine for tool execution.",
    task="Map conceptual tool inputs and candidate arguments to concrete executable arguments.",
    rules=_ARG_RESOLVER_RULES,
    examples=_ARG_RESOLVER_EXAMPLES,
    include_schema_rules=True,
)


def get_arg_resolver_prompt(
    *,
    today_utc: str,
    domain: str,
    tool_name: str,
    required_inputs: list[str],
    tool_param_names: list[str],
    required_params: list[str],
    docstring: str,
    candidate_args: dict[str, Any],
    execution_context: dict[str, Any],
) -> str:
    return render_system(
        ARG_RESOLVER_PROMPT,
        today_utc=today_utc,
        domain=domain,
        tool=tool_name,
        required_inputs_conceptual=json.dumps(required_inputs),
        allowed_argument_names=json.dumps(tool_param_names),
        required_argument_names=json.dumps(required_params),
        tool_docstring=docstring[:1200],
        candidate_arguments=json.dumps(candidate_args, default=str),
        execution_context=json.dumps(execution_context, default=str),
    )
