"""Aggregator routing when domain tools do not produce evidence."""

from __future__ import annotations

import asyncio

from eo_llm.graph.nodes.aggregator_node import aggregator_node


def test_domain_failure_routes_to_web_search() -> None:
    out = asyncio.run(
        aggregator_node(
            {
                "query": "test",
                "domain_results": {
                    "flood_damage": {
                        "status": "error",
                        "summary": {"successful_steps": 0},
                        "message": "upstream failure",
                    },
                },
                "web_results": [],
            }
        )
    )
    assert out.get("next_step") == "web_search"
    assert out.get("fallback_to_websearch") is True


def test_successful_domain_skips_web() -> None:
    out = asyncio.run(
        aggregator_node(
            {
                "query": "test",
                "domain_results": {
                    "flood_damage": {
                        "status": "done",
                        "summary": {"successful_steps": 1},
                    },
                },
                "web_results": [],
            }
        )
    )
    assert out.get("next_step") == "finalize"
    assert out.get("answer_source") == "domain_tools"


def test_empty_domains_no_web_yet_routes_to_web() -> None:
    out = asyncio.run(
        aggregator_node(
            {
                "query": "test",
                "domain_results": {},
                "web_results": [],
            }
        )
    )
    assert out.get("next_step") == "web_search"
