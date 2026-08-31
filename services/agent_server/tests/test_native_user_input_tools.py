"""Tests for native user-input tools."""

from __future__ import annotations

import pytest

from src.tools.native.user_inputs.bounding_box import RequestBoundingBoxUserInputTool
from src.tools.native.user_inputs.location import RequestLocationUserInputTool
from src.tools.providers.native import NativeToolProvider, build_default_native_provider
from src.user_inputs import UserInputRouter


def test_location_user_input_tool_returns_needs_input():
    tool = RequestLocationUserInputTool()
    response = tool.invoke(
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


def test_user_input_router_round_trip_from_tool_response():
    response = RequestLocationUserInputTool().invoke(
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
