"""Location extraction prompts."""

from __future__ import annotations

from eo_llm.prompts.builder import PromptSpec, render_system
from eo_llm.prompts.shared.schema import SCHEMA_OUTPUT_RULES

_LOCATION_RULES: tuple[str, ...] = (
    *SCHEMA_OUTPUT_RULES,
    "Extract only the most relevant place name for geocoding.",
    "Return one place suitable for geocoding (city/town/region/country).",
    "Prefer the settlement or region name; drop feature words like forest(s), woods, park, mountains unless they are the official place name.",
    "Return empty string if no location is present.",
    "Prefer adding country context when unambiguous (e.g. Paris -> Paris, France).",
)

_LOCATION_EXAMPLES: tuple[str, ...] = (
    "Query: fires in paris in 2025 -> Paris, France",
    "Query: storms in spain 2015-2025 -> Spain",
    "Query: show me water risk in Casablanca -> Casablanca, Morocco",
    "Query: meteo dresden -> Dresden, Germany",
    "Query: Were there any fires around fontainebleau forests in 2026? -> Fontainebleau, France",
    "Query: hello -> (empty string)",
)

QUERY_LOCATION_PROMPT = PromptSpec(
    role="You are AURA's location extraction helper.",
    task="Extract a geocodable place from the user query.",
    rules=_LOCATION_RULES,
    examples=_LOCATION_EXAMPLES,
    include_schema_rules=True,
)

_DOCUMENT_LOCATION_RULES: tuple[str, ...] = (
    *_LOCATION_RULES,
    "Use the uploaded document together with the user query.",
    "Return the single place most relevant to answering the query.",
)

DOCUMENT_LOCATION_PROMPT = PromptSpec(
    role="You are AURA's document location extraction helper.",
    task="Extract a geocodable place from the document relevant to the user query.",
    rules=_DOCUMENT_LOCATION_RULES,
    include_schema_rules=True,
)


def get_query_location_prompt() -> str:
    return render_system(QUERY_LOCATION_PROMPT)


def get_document_location_prompt() -> str:
    return render_system(DOCUMENT_LOCATION_PROMPT)
