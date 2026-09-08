"""Tests for domain evidence digest."""

from __future__ import annotations

import pytest

from eo_llm.graph.evidence_digest import build_domain_evidence_digest


@pytest.mark.unit
def test_digest_summarizes_nested_structured_data():
    domain_results = {
        "flood_damage": {
            "executions": [
                {
                    "status": "success",
                    "tool_name": "get_terrazard_flood_briefing_tool",
                    "result": {
                        "message": "Flood briefing ready.",
                        "city": "Paris",
                        "data": {
                            "agent_briefing": {
                                "headline": "Major event for Paris on 2024-03-15",
                                "severity": {
                                    "tier": "major",
                                    "water_count": 42,
                                },
                                "extent": {"flooded_km2": 12.3},
                            }
                        },
                    },
                }
            ]
        }
    }

    digest = build_domain_evidence_digest(domain_results)
    assert "[flood_damage]" in digest
    assert "get_terrazard_flood_briefing_tool" in digest
    assert "headline: Major event" in digest
    assert "tier: major" in digest
    assert "flooded_km2: 12.3" in digest
    assert "city: Paris" in digest


@pytest.mark.unit
def test_digest_handles_scalar_tool_data():
    domain_results = {
        "fire_detection": {
            "executions": [
                {
                    "status": "success",
                    "tool_name": "detect_fire_tool",
                    "result": {
                        "message": "Found 3 active fires.",
                        "start_date": "20240101",
                        "end_date": "20240107",
                        "data": {"nb_fires": 3, "radius_km": 25},
                    },
                }
            ]
        }
    }

    digest = build_domain_evidence_digest(domain_results)
    assert "[fire_detection]" in digest
    assert "nb_fires: 3" in digest
    assert "radius_km: 25" in digest


@pytest.mark.unit
def test_digest_falls_back_to_message_only():
    domain_results = {
        "flood_damage": {
            "executions": [
                {
                    "status": "success",
                    "tool_name": "geoserver_risk_mask_tool",
                    "result": {
                        "message": "Found flood risk polygons near Paris.",
                        "data": {},
                    },
                }
            ]
        }
    }

    digest = build_domain_evidence_digest(domain_results)
    assert "geoserver_risk_mask_tool" in digest
    assert "Found flood risk polygons" in digest


@pytest.mark.unit
def test_digest_skips_rendering_payload_keys():
    domain_results = {
        "infrastructure": {
            "executions": [
                {
                    "status": "success",
                    "tool_name": "infrastructure_query_tool",
                    "result": {
                        "message": "Infrastructure summary.",
                        "data": {
                            "count": 12,
                            "bbox": [1.0, 2.0, 3.0, 4.0],
                            "maps": [{"view_state": {"zoom": 10}}],
                        },
                    },
                }
            ]
        }
    }

    digest = build_domain_evidence_digest(domain_results)
    assert "count: 12" in digest
    assert "bbox" not in digest
    assert "view_state" not in digest


@pytest.mark.unit
def test_digest_empty_results():
    digest = build_domain_evidence_digest({})
    assert digest == "No structured domain evidence available."
