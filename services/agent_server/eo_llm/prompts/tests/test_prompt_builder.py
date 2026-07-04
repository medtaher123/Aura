"""Prompt builder unit tests (no Bedrock calls)."""

from __future__ import annotations

from eo_llm.prompts import (
    BROWSER_SYSTEM_PROMPT,
    DOCUMENT_QA_SYSTEM,
    get_arg_resolver_prompt,
    get_browser_user_prompt,
    get_document_location_prompt,
    get_finalizer_prompt,
    get_query_location_prompt,
    get_router_prompt,
    get_tool_planner_prompt,
)
from eo_llm.prompts.graph.router import ROUTER_DOMAINS
from eo_llm.prompts.persona import AURA_PERSONA
from eo_llm.prompts.shared.grounding import GROUNDING_RULES


def test_router_prompt_includes_domains_and_aura() -> None:
    system, user = get_router_prompt(query="fires in Paris")
    assert AURA_PERSONA.split(".")[0] in system
    for domain in ROUTER_DOMAINS:
        assert domain in system
    assert "fires in Paris" in user
    assert "NEVER invent" in system


def test_tool_planner_flood_damage_disambiguation() -> None:
    system, user = get_tool_planner_prompt(
        domain="flood_damage",
        query="streamflow forecast for the Seine",
        allowed_tools=["streamflow_forecast_tool", "geoserver_risk_mask_tool"],
    )
    assert "geoserver_risk_mask_tool" in system
    assert "streamflow_forecast_tool" in system
    assert "streamflow forecast for the Seine" in user


def test_finalizer_includes_grounding_and_analysis_rules() -> None:
    system, user = get_finalizer_prompt(
        today_utc="2026-07-03",
        query="temperature trend in Paris",
        answer_source="domain_tools",
        aggregated_evidence="Domain evidence available.",
        domain_results_json="{}",
        web_results_json="[]",
    )
    assert any(rule in system for rule in GROUNDING_RULES[:2])
    assert "NASA POWER" in system
    assert "temperature trend in Paris" in user


def test_arg_resolver_includes_temporal_rules() -> None:
    system, user = get_arg_resolver_prompt(
        today_utc="2026-07-03",
        domain="fire_detection",
        tool_name="detect_fire_tool",
        required_inputs=["location", "start_date", "end_date"],
        tool_param_names=["location", "start_date", "end_date", "lat", "lon"],
        required_params=["start_date", "end_date"],
        docstring="Detect fires.",
        candidate_args={"lat": 48.8, "lon": 2.3},
        execution_context={"query": "fires in Paris last summer"},
    )
    assert "YYYY-MM-DD" in system
    assert "fires in Paris last summer" in user


def test_location_prompts_non_empty() -> None:
    system, user = get_query_location_prompt(query="storms in Spain")
    assert system.strip()
    assert "storms in Spain" in user
    doc_system, doc_user = get_document_location_prompt(query="location in the document")
    assert doc_system.strip()
    assert "location in the document" in doc_user


def test_document_qa_and_browser_prompts() -> None:
    assert "AURA" in DOCUMENT_QA_SYSTEM
    assert "document" in DOCUMENT_QA_SYSTEM.lower()
    assert "AURA" in BROWSER_SYSTEM_PROMPT
    user = get_browser_user_prompt(
        user_query="What is Sentinel-2?",
        contextualized_query="What is Sentinel-2?",
        domain_failure_hint="stac: status=error",
    )
    assert "Sentinel-2" in user
    assert "stac: status=error" in user
