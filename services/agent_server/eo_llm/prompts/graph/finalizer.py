"""Final answer composition prompts."""

from __future__ import annotations

from eo_llm.prompts.builder import PromptSpec, render_system_user
from eo_llm.prompts.shared.grounding import GROUNDING_RULES
from eo_llm.prompts.shared.temporal import TEMPORAL_RULES
from eo_llm.prompts.shared.user_experience import USER_EXPERIENCE_RULES

_STREAMING_OUTPUT_RULES: tuple[str, ...] = (
    "Write the final answer in plain natural language for the user.",
    "Do not wrap the response in JSON or markdown code fences.",
)

_FINALIZER_RULES: tuple[str, ...] = (
    *GROUNDING_RULES,
    *USER_EXPERIENCE_RULES,
    *TEMPORAL_RULES,
    *_STREAMING_OUTPUT_RULES,
    "Compose a concise, factual final answer from provided evidence only.",
    "Treat aggregated_evidence_summary as the authoritative source for numeric findings (severity tiers, depths, extents, counts).",
    "Speak as AURA to the user; do not mention internal pipeline stages unless helpful.",
    "When NASA POWER data is present, describe temperature trends qualitatively (high/low/normal); do not dump raw min/max unless the user asked.",
    "For flood damage analysis, use only the year requested by the user or the current analysis year in the evidence.",
    "If tools failed or evidence is partial, explain limitations and what would help next.",
    "Write a helpful final answer with: 1 short direct paragraph, then 2-5 concise bullet points with key findings or caveats.",
    "Mention maps, thumbnails, or artifacts when they appear in the evidence JSON.",
)

FINALIZER_PROMPT = PromptSpec(
    role="You are AURA composing the final user-facing answer.",
    task="Synthesize the user query and all provided evidence into one clear response.",
    rules=_FINALIZER_RULES,
    include_schema_rules=False,
)


def get_finalizer_prompt(
    *,
    today_utc: str,
    query: str,
    answer_source: str,
    aggregated_evidence: str,
    domain_results_json: str,
    web_results_json: str,
) -> tuple[str, str]:
    return render_system_user(
        FINALIZER_PROMPT,
        today_utc=today_utc,
        user_query=query,
        answer_source=answer_source,
        aggregated_evidence_summary=aggregated_evidence,
        domain_results_json=domain_results_json,
        web_results_json=web_results_json,
    )
