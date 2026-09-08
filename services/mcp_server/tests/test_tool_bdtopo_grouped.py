"""Unit tests for grouped BDTOPO tools."""

from __future__ import annotations

import pytest

from modules.geospatial import bdtopo_change as change_tool
from modules.geospatial import bdtopo_explain as explain_tool
from modules.geospatial import bdtopo_intersection as intersection_tool
from modules.geospatial import bdtopo_quality as quality_tool
from utils.contracts import ToolCoordinates


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grouped_bdtopo_tools_are_registered(mcp_client):
    tools = await mcp_client.list_tools()
    names = [tool["name"] for tool in tools]
    assert "bdtopo_intersection_tool" in names
    assert "bdtopo_coverage_quality_tool" in names
    assert "bdtopo_change_snapshot_tool" in names
    assert "bdtopo_thematic_explain_tool" in names
    assert "bdtopo_visualize_tool" in names


@pytest.mark.unit
def test_bdtopo_intersection_point_success(monkeypatch):
    monkeypatch.setattr(
        intersection_tool,
        "run_query",
        lambda *_args, **_kwargs: [
            {
                "road_id": "R1",
                "road_label": "Rue Test",
                "road_nature": "Route a 2 chaussees",
                "zone_id": "Z1",
                "zone_label": "Zone test",
                "regulation_type": "Site Natura 2000",
                "distance_m": 120.5,
                "geom_geojson": '{"type":"Point","coordinates":[2.35,48.86]}',
            }
        ],
    )

    result = intersection_tool.bdtopo_intersection_tool(
        input_mode="point",
        lat=48.8566,
        lon=2.3522,
        radius_m=5000,
        limit=5,
    )
    assert result.error is False
    assert result.data["summary"]["top_regulation_types"]
    assert result.artifacts.maps
    assert result.artifacts.urls


@pytest.mark.unit
def test_bdtopo_quality_success(monkeypatch):
    monkeypatch.setattr(
        quality_tool,
        "resolve_area_context",
        lambda **_kwargs: {
            "mode": "point",
            "coords": ToolCoordinates(lat=48.8566, lon=2.3522),
            "radius_m": 3000,
            "bbox": None,
            "place_label": None,
        },
    )
    monkeypatch.setattr(
        quality_tool,
        "run_query",
        lambda *_args, **_kwargs: [
            {"metric_key": "test", "source": "test_source", "feature_count": 10, "named_count": 8}
        ],
    )

    result = quality_tool.bdtopo_coverage_quality_tool(
        input_mode="point",
        lat=48.8566,
        lon=2.3522,
        radius_m=3000,
    )
    assert result.error is False
    assert result.data["indicators"]
    assert "themes_with_data" in result.data


@pytest.mark.unit
def test_bdtopo_change_snapshot_success(monkeypatch):
    monkeypatch.setattr(change_tool, "_edition_exists", lambda _edition: True)
    monkeypatch.setattr(
        change_tool,
        "resolve_area_context",
        lambda **_kwargs: {
            "mode": "point",
            "coords": ToolCoordinates(lat=48.8566, lon=2.3522),
            "radius_m": 3000,
            "bbox": None,
            "place_label": "Paris",
        },
    )
    monkeypatch.setattr(
        change_tool,
        "_count_for_table",
        lambda **kwargs: 20 if kwargs["edition"] == "2026-03-15" else 10,
    )

    result = change_tool.bdtopo_change_snapshot_tool(
        baseline_edition="2025-12-15",
        target_edition="2026-03-15",
        input_mode="point",
        lat=48.8566,
        lon=2.3522,
    )
    assert result.error is False
    assert result.data["summary"]["delta_total"] > 0
    assert result.data["tables"]


@pytest.mark.unit
def test_bdtopo_thematic_explain_success(monkeypatch):
    monkeypatch.setattr(
        explain_tool,
        "resolve_area_context",
        lambda **_kwargs: {
            "mode": "point",
            "coords": ToolCoordinates(lat=48.8566, lon=2.3522),
            "radius_m": 2000,
            "bbox": None,
            "place_label": "Paris",
        },
    )

    def fake_run_query(sql_query, _params):
        if "FROM bdtopo_raw.commune" in sql_query:
            return [
                {
                    "nom_officiel": "Paris",
                    "code_insee": "75056",
                    "population": 2000000,
                    "code_postal": "75000",
                }
            ]
        if "COUNT(*) AS value" in sql_query:
            return [{"value": 25}]
        return []

    monkeypatch.setattr(explain_tool, "run_query", fake_run_query)

    result = explain_tool.bdtopo_thematic_explain_tool(
        objective="site_screening",
        input_mode="point",
        lat=48.8566,
        lon=2.3522,
        radius_m=2000,
    )
    assert result.error is False
    assert result.data["evidence"]
    assert result.data["summary"]["screening_score_0_100"] >= 0
