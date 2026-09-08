"""Tests for native user-input tools."""

from __future__ import annotations

import pytest

from src.tools.native.user_inputs.bounding_box import RequestBoundingBoxUserInputTool
from src.tools.native.user_inputs.location import RequestLocationUserInputTool
from src.tools.providers.native import NativeToolProvider, build_default_native_provider
from src.user_inputs import UserInputRouter


@pytest.mark.asyncio
async def test_location_user_input_tool_returns_needs_input():
    tool = RequestLocationUserInputTool()
    response = await tool.invoke(
        candidates=[
            {"display_name": "Paris, France", "lat": 48.8566, "lon": 2.3522},
            {"display_name": "Paris, TX", "lat": 33.66, "lon": -95.56},
        ],
        prompt="Pick a city",
        location_query="Paris",
    )
    assert response.error is False
    assert response.data["stopped_for_user_input"] is True
    assert response.data["input_kind"] == "location"
    needs = response.data["needs_input"]
    assert "location" in needs
    assert len(needs["location"]["candidates"]) == 2
    assert needs["location"]["prompt"] == "Pick a city"


def test_bounding_box_user_input_tool_returns_needs_input():
    tool = RequestBoundingBoxUserInputTool()
    response = tool.invoke(
        prompt="Draw the analysis area",
        map_center=[48.85, 2.35],
        map_zoom=11.0,
    )
    assert response.error is False
    assert response.data["input_kind"] == "bounding_box"
    needs = response.data["needs_input"]
    assert needs["bounding_box"]["prompt"] == "Draw the analysis area"
    assert needs["bounding_box"]["map_center"] == [48.85, 2.35]
    assert needs["bounding_box"]["map_zoom"] == 11.0


@pytest.mark.asyncio
async def test_user_input_router_round_trip_from_tool_response():
    response = await RequestLocationUserInputTool().invoke(
        candidates=[{"display_name": "Lyon", "lat": 45.75, "lon": 4.85}],
    )
    parsed = UserInputRouter.requests_from_dict(response.data["needs_input"])
    assert "location" in parsed
    assert parsed["location"].candidates[0].display_name == "Lyon"


@pytest.mark.asyncio
async def test_build_default_native_provider_registers_user_input_tools():
    provider = build_default_native_provider()
    tools = await provider.discover_tools()
    names = {t.name for t in tools}
    assert "request_location_user_input" in names
    assert "request_bounding_box_user_input" in names

    location_tool = next(t for t in tools if t.name == "request_location_user_input")
    assert "candidates" in location_tool.input_schema.get("properties", {})

    result = await provider.invoke(
        "request_bounding_box_user_input",
        {"prompt": "Select area"},
    )
    assert result.data["stopped_for_user_input"] is True


@pytest.mark.asyncio
async def test_native_provider_passes_kwargs_for_location_tool():
    """``invoke(self, **kwargs)`` tools must receive full LLM argument dicts."""
    provider = build_default_native_provider()
    result = await provider.invoke(
        "request_location_user_input",
        {
            "candidates": [
                {
                    "display_name": "Pas-de-Calais, France",
                    "lat": 50.5144061,
                    "lon": 2.2580078,
                    "name": "Pas-de-Calais",
                    "osm_id": 7394,
                    "osm_type": "relation",
                },
                {
                    "display_name": "Strait of Dover / Pas de Calais",
                    "lat": 51.0149083,
                    "lon": 1.5270969,
                    "name": "Strait of Dover / Pas de Calais",
                    "osm_id": 1180740208,
                    "osm_type": "way",
                },
            ],
            "location_query": "Pas-de-Calais, France",
            "prompt": "Which Pas-de-Calais location do you mean?",
        },
    )
    assert result.error is False, result.message
    assert result.data["stopped_for_user_input"] is True
    assert len(result.data["needs_input"]["location"]["candidates"]) == 2


@pytest.mark.asyncio
async def test_location_tool_geocodes_when_candidates_omitted(monkeypatch):
    async def fake_search(place_query: str, *, limit: int = 8):
        assert place_query == "Pas-de-Calais, France"
        return [
            {
                "display_name": "Pas-de-Calais, Hauts-de-France, France",
                "lat": 50.5144061,
                "lon": 2.2580078,
                "name": "Pas-de-Calais",
            },
            {
                "display_name": "Strait of Dover / Pas de Calais",
                "lat": 51.0149083,
                "lon": 1.5270969,
                "name": "Strait of Dover / Pas de Calais",
            },
        ]

    monkeypatch.setattr(
        "src.tools.native.user_inputs.location.search_location_candidates",
        fake_search,
    )
    provider = build_default_native_provider()
    result = await provider.invoke(
        "request_location_user_input",
        {"location_query": "Pas-de-Calais, France"},
    )
    assert result.error is False, result.message
    candidates = result.data["needs_input"]["location"]["candidates"]
    assert len(candidates) == 2
    assert result.data["needs_input"]["location"]["location_query"] == (
        "Pas-de-Calais, France"
    )


@pytest.mark.asyncio
async def test_location_tool_requires_query_when_candidates_omitted():
    provider = build_default_native_provider()
    result = await provider.invoke("request_location_user_input", {"prompt": "Pick one"})
    assert result.error is True
    assert "location_query" in result.message


def test_location_tool_schema_makes_candidates_optional():
    schema = RequestLocationUserInputTool.input_schema()
    assert "candidates" not in (schema.get("required") or [])
    assert "minItems" not in (schema.get("properties") or {}).get("candidates", {})
    assert "candidates" in (schema.get("properties") or {})
