"""Tests for BDTOPO visualization MCP tool (vector-tile map artifacts)."""

from __future__ import annotations

import pytest

from modules.geospatial import bdtopo_visualize as visualize
from utils.contracts import ToolCoordinates


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bdtopo_visualize_tool_is_registered(mcp_client):
    tools = await mcp_client.list_tools()
    names = [tool["name"] for tool in tools]
    assert "bdtopo_visualize_tool" in names


@pytest.mark.unit
def test_bdtopo_visualize_success(monkeypatch):
    monkeypatch.setattr(
        visualize,
        "_resolve_tile_server_url",
        lambda: "http://tiles.example",
    )
    monkeypatch.setattr(
        visualize,
        "resolve_area_context",
        lambda **_kwargs: {
            "mode": "point",
            "coords": ToolCoordinates(lat=48.8566, lon=2.3522),
            "radius_m": 3000,
            "bbox": None,
            "place_label": "Paris",
        },
    )

    result = visualize.bdtopo_visualize_tool(
        input_mode="point",
        lat=48.8566,
        lon=2.3522,
        radius_m=3000,
        themes=["buildings", "transport"],
    )

    assert result.error is False
    assert result.data["themes_requested"] == ["buildings", "transport"]
    assert result.artifacts.maps
    map_spec = result.artifacts.maps[0]
    assert map_spec["renderer"] == "vector_tile"
    layers_by_theme = {layer["theme"]: layer for layer in map_spec["vector_layers"]}
    assert layers_by_theme["buildings"]["minzoom"] == 14
    assert layers_by_theme["transport"]["minzoom"] == 13
    assert result.data["layers"][0]["minzoom"] == 14


@pytest.mark.unit
def test_normalize_themes_defaults():
    assert visualize._normalize_themes(None) == list(visualize.DEFAULT_THEMES)


@pytest.mark.unit
def test_normalize_themes_filters_unknown():
    assert visualize._normalize_themes(["buildings", "unknown", "transport"]) == [
        "buildings",
        "transport",
    ]
