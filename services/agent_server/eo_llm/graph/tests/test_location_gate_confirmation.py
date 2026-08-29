"""Location gate behavior for country and ambiguous place matches."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from eo_llm.graph.nodes.location_gate_node import LocationGateNode, location_gate_node
from eo_llm.graph.tests.conftest import simulate_hitl_resume


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
    resolved = out.get("resolved_location") or {}
    assert resolved.get("lat") is not None
    assert resolved.get("lon") is not None


def test_single_candidate_skip_confirmation(monkeypatch) -> None:
    async def fake_search(_place_query: str, *, limit: int = 8):
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
    resolved = out.get("resolved_location") or {}
    assert resolved.get("display_name") == "Tunis, Tunisia"


def test_ambiguous_non_country_requests_hitl(monkeypatch) -> None:
    async def fake_search(_place_query: str, *, limit: int = 8):
        return [
            {
                "display_name": "Paris, France",
                "name": "Paris",
                "lat": 48.8566,
                "lon": 2.3522,
            },
            {
                "display_name": "Paris, Texas, USA",
                "name": "Paris",
                "lat": 33.6609,
                "lon": -95.5555,
            },
        ]

    async def fake_pause(self, s, client_payload, *, blob=None):
        payload_blob = blob if blob is not None else self.serialize_hitl_blob(s)
        return await simulate_hitl_resume(
            self,
            s,
            [
                {
                    "type": "location",
                    "name": "Paris, France",
                    "coordinates": [48.8566, 2.3522],
                }
            ],
            blob=payload_blob,
        )

    monkeypatch.setattr(
        "eo_llm.graph.nodes.location_gate_node.search_location_candidates", fake_search
    )
    monkeypatch.setattr(LocationGateNode, "pause_for_hitl", fake_pause)

    out = asyncio.run(
        location_gate_node({"query": "Flood risk in Paris?", "place_hint": "Paris"})
    )
    resolved = out.get("resolved_location") or {}
    assert resolved.get("display_name") == "Paris, France"
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
    assert out.get("location_query") == "Fontainebleau"
    resolved = out.get("resolved_location") or {}
    assert resolved.get("lat") == 48.4049
    assert resolved.get("lon") == 2.7016
