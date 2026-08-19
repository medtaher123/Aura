"""Location gate behavior for country and ambiguous place matches."""

from __future__ import annotations

import asyncio

from eo_llm.graph.nodes.location_gate_node import location_gate_node


def test_country_candidates_skip_confirmation(monkeypatch) -> None:
    async def fake_search(_place_query: str, *, limit: int = 8):
        assert limit == 8
        return [
            {
                "display_name": "France",
                "name": "France",
                "lat": 46.2276,
                "lon": 2.2137,
                "class": "boundary",
                "type": "administrative",
                "addresstype": "country",
            },
            {
                "display_name": "France, Metropolitan France",
                "name": "France",
                "lat": 46.2275,
                "lon": 2.2138,
                "class": "boundary",
                "type": "administrative",
                "addresstype": "country",
            },
        ]

    monkeypatch.setattr(
        "eo_llm.graph.nodes.location_gate_node.search_location_candidates", fake_search
    )

    out = asyncio.run(
        location_gate_node({"query": "What is flood risk in France?", "place_hint": "France"})
    )
    assert out.get("location_phase") == "router"
    assert out.get("stopped_for_user_input") is False
    assert not out.get("needs_input")
    resolved = out.get("resolved_location") or {}
    assert resolved.get("lat") is not None
    assert resolved.get("lon") is not None


def test_single_candidate_skip_confirmation(monkeypatch) -> None:
    async def fake_search(_place_query: str, *, limit: int = 8):
        assert limit == 8
        return [
            {
                "display_name": "Tunis, Tunisia",
                "name": "Tunis",
                "lat": 36.8065,
                "lon": 10.1815,
                "class": "place",
                "type": "city",
                "addresstype": "city",
            }
        ]

    monkeypatch.setattr(
        "eo_llm.graph.nodes.location_gate_node.search_location_candidates", fake_search
    )

    out = asyncio.run(
        location_gate_node({"query": "Flood risk in Tunis?", "place_hint": "Tunis"})
    )
    assert out.get("location_phase") == "router"
    assert out.get("stopped_for_user_input") is False
    assert not out.get("needs_input")
    resolved = out.get("resolved_location") or {}
    assert resolved.get("display_name") == "Tunis, Tunisia"


def test_ambiguous_non_country_requires_confirmation(monkeypatch) -> None:
    async def fake_search(_place_query: str, *, limit: int = 8):
        assert limit == 8
        return [
            {
                "display_name": "Paris, France",
                "name": "Paris",
                "lat": 48.8566,
                "lon": 2.3522,
                "class": "place",
                "type": "city",
                "addresstype": "city",
            },
            {
                "display_name": "Paris, Texas, USA",
                "name": "Paris",
                "lat": 33.6609,
                "lon": -95.5555,
                "class": "place",
                "type": "city",
                "addresstype": "city",
            },
        ]

    monkeypatch.setattr(
        "eo_llm.graph.nodes.location_gate_node.search_location_candidates", fake_search
    )

    out = asyncio.run(
        location_gate_node({"query": "Flood risk in Paris?", "place_hint": "Paris"})
    )
    assert out.get("location_phase") == "pause"
    assert out.get("stopped_for_user_input") is True
    needs_input = out.get("needs_input") or {}
    assert "location" in needs_input
    assert len((needs_input.get("location") or {}).get("candidates") or []) == 2
    assert len(out.get("location_candidates") or []) == 2


def test_feature_suffix_retry_when_full_query_misses(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_search(place_query: str, *, limit: int = 8):
        calls.append(place_query)
        if place_query.lower() == "fontainebleau forests":
            return []
        if place_query.lower() == "fontainebleau":
            return [
                {
                    "display_name": "Fontainebleau, Seine-et-Marne, France",
                    "name": "Fontainebleau",
                    "lat": 48.4049,
                    "lon": 2.7016,
                    "class": "boundary",
                    "type": "administrative",
                    "addresstype": "town",
                }
            ]
        return []

    monkeypatch.setattr(
        "eo_llm.graph.nodes.location_gate_node.search_location_candidates", fake_search
    )

    out = asyncio.run(
        location_gate_node(
            {
                "query": "Were there any fires around fontainebleau forests in 2026?",
                "place_hint": "Fontainebleau forests",
            }
        )
    )
    assert calls == ["Fontainebleau forests", "Fontainebleau"]
    assert out.get("location_phase") == "router"
    assert out.get("stopped_for_user_input") is False
    assert out.get("location_query") == "Fontainebleau"
    resolved = out.get("resolved_location") or {}
    assert resolved.get("lat") == 48.4049
    assert resolved.get("lon") == 2.7016
