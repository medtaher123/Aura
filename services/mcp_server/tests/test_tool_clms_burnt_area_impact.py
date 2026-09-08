"""Tests for CLMS burnt-area impact tool."""

import numpy as np
import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clms_burnt_area_impact_tool_exists(mcp_client):
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "clms_burnt_area_impact_tool" in tool_names


@pytest.mark.unit
def test_clms_burnt_area_requires_at_least_one_location_mode():
    from modules.hazards.clms_burnt_area_impact import clms_burnt_area_impact_tool

    result = clms_burnt_area_impact_tool()
    assert result.error is True
    assert "Unable to resolve AOI from provided inputs." in result.message


@pytest.mark.unit
def test_clms_burnt_area_prefers_polygon_over_latlon_and_location(monkeypatch):
    from modules.hazards import clms_burnt_area_impact as mod

    monkeypatch.setattr(mod, "_oauth_token", lambda: "token")
    monkeypatch.setattr(
        mod,
        "_fetch_burn_raster",
        lambda **_kwargs: (
            np.zeros((2, 2), dtype=np.int16),
            np.ones((2, 2), dtype=np.int16),
            None,
        ),
    )

    # Invalid lat/lon are provided on purpose. Polygon should take precedence
    # so these values must not be used.
    result = mod.clms_burnt_area_impact_tool(
        polygon_wkt="POLYGON ((-1 40, 1 40, 1 41, -1 41, -1 40))",
        lat=999.0,
        lon=999.0,
        location="California, United States",
        start_date="2025-01-01",
        end_date="2025-01-31",
        return_map=False,
    )
    assert result.error is False
    assert result.data["aoi"]["input_mode"] == "polygon"


@pytest.mark.unit
def test_clms_burnt_area_location_ambiguous(monkeypatch):
    from modules.hazards import clms_burnt_area_impact as mod

    monkeypatch.setattr(
        mod,
        "get_city_candidates",
        lambda *_args, **_kwargs: [
            {
                "display_name": "Paris, France",
                "lat": 48.8566,
                "lon": 2.3522,
                "bbox": [48.80, 48.90, 2.20, 2.45],
                "place_id": 123,
                "osm_id": 7444,
                "osm_type": "R",
            },
            {
                "display_name": "Paris, Texas, USA",
                "lat": 33.66,
                "lon": -95.55,
                "bbox": [33.60, 33.70, -95.60, -95.50],
                "place_id": 456,
                "osm_id": 999,
                "osm_type": "R",
            },
        ],
    )

    result = mod.clms_burnt_area_impact_tool(location="Paris")
    assert result.error is True
    assert "Location is ambiguous" in result.message


@pytest.mark.unit
def test_clms_burnt_area_success_point_radius(monkeypatch):
    from modules.hazards import clms_burnt_area_impact as mod

    monkeypatch.setattr(mod, "_oauth_token", lambda: "token")
    monkeypatch.setattr(
        mod,
        "reverse_geocode",
        lambda _lat, _lon: {"city": "Madrid", "country": "Spain"},
    )

    bf = np.array(
        [
            [0, 0, 80, 120],
            [0, 50, 120, 400],
            [0, 0, 0, 0],
            [300, 250, 0, 0],
        ],
        dtype=np.int16,
    )
    data_mask = np.ones((4, 4), dtype=np.int16)
    dob = np.array(
        [
            [0, 0, 210, 211],
            [0, 210, 211, 212],
            [0, 0, 0, 0],
            [212, 212, 0, 0],
        ],
        dtype=np.int16,
    )
    monkeypatch.setattr(
        mod,
        "_fetch_burn_raster",
        lambda **_kwargs: (bf, data_mask, dob),
    )

    result = mod.clms_burnt_area_impact_tool(
        lat=40.4168,
        lon=-3.7038,
        radius_km=10,
        start_date="2025-08-01",
        end_date="2025-08-31",
    )
    assert result.error is False
    assert result.tool_name == "clms_burnt_area_impact_tool"
    assert result.data["source"]["dataset_key"] == "v4_daily"
    assert result.data["impact"]["burnt_area_pct"] > 0
    assert result.data["impact"]["risk_band"] in {"low", "moderate", "high"}
    assert result.data["pixel_stats"]["min_day_of_burn"] == 210


@pytest.mark.unit
def test_clms_burnt_area_fallback_to_monthly(monkeypatch):
    from modules.hazards import clms_burnt_area_impact as mod

    monkeypatch.setattr(mod, "_oauth_token", lambda: "token")
    monkeypatch.setattr(
        mod,
        "reverse_geocode",
        lambda _lat, _lon: {"city": "Paris", "country": "France"},
    )
    called_candidates: list[str] = []

    def _fake_fetch(**kwargs):
        candidate = kwargs["candidate"]
        called_candidates.append(candidate.key)
        if candidate.key != "v4_monthly":
            raise mod.CLMSBurntAreaNoDataError("no data")
        day_of_burn = np.array(
            [
                [0, 10, 11, 0],
                [0, 0, 0, 0],
                [50, 70, 0, 0],
                [0, 0, 0, 0],
            ],
            dtype=np.int16,
        )
        data_mask = np.ones((4, 4), dtype=np.int16)
        dob = np.array(
            [
                [0, 10, 11, 0],
                [0, 0, 0, 0],
                [50, 70, 0, 0],
                [0, 0, 0, 0],
            ],
            dtype=np.int16,
        )
        return day_of_burn, data_mask, dob

    monkeypatch.setattr(mod, "_fetch_burn_raster", _fake_fetch)

    result = mod.clms_burnt_area_impact_tool(
        lat=48.8566,
        lon=2.3522,
        radius_km=5,
        start_date="2020-07-01",
        end_date="2020-07-31",
        dataset_version="auto",
    )
    assert result.error is False
    assert result.data["source"]["dataset_key"] == "v4_monthly"
    assert called_candidates == ["v4_monthly"]
    quality_notes = result.data["quality_notes"]
    assert any("fallback to v4_monthly" in note for note in quality_notes)
