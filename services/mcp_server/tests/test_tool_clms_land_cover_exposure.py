"""Tests for CLMS land-cover exposure tool."""

import numpy as np
import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clms_land_cover_exposure_tool_exists(mcp_client):
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "clms_land_cover_exposure_tool" in tool_names


@pytest.mark.unit
def test_clms_land_cover_requires_location_input():
    from modules.hazards.clms_land_cover_exposure import clms_land_cover_exposure_tool

    result = clms_land_cover_exposure_tool()
    assert result.error is True
    assert "Provide one location input" in result.message


@pytest.mark.unit
def test_clms_land_cover_city_ambiguous(monkeypatch):
    from modules.hazards import clms_land_cover_exposure as mod

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

    result = mod.clms_land_cover_exposure_tool(city_name="Paris")
    assert result.error is True
    assert "Location is ambiguous" in result.message


@pytest.mark.unit
def test_clms_land_cover_success_point_radius(monkeypatch):
    from modules.hazards import clms_land_cover_exposure as mod

    monkeypatch.setattr(
        mod,
        "reverse_geocode",
        lambda lat, lon: {"city": "Paris", "country": "France", "country_iso": "FR"},
    )
    monkeypatch.setattr(mod, "_oauth_token", lambda: "token")

    # 4x4 toy raster:
    # - built_up class=90 dominates
    # - some tree class=10
    lcm10 = np.array(
        [
            [90, 90, 90, 10],
            [90, 90, 10, 10],
            [90, 90, 90, 90],
            [90, 90, 90, 90],
        ],
        dtype=np.uint8,
    )
    data_mask = np.ones((4, 4), dtype=np.uint8)

    monkeypatch.setattr(
        mod,
        "_fetch_lcm10_raster",
        lambda **_kwargs: (lcm10, data_mask),
    )

    result = mod.clms_land_cover_exposure_tool(lat=48.8566, lon=2.3522, radius_m=1000)

    assert result.error is False
    assert result.tool_name == "clms_land_cover_exposure_tool"
    assert "land_cover_mix_pct" in result.data
    assert "insurance_features" in result.data
    assert result.data["insurance_features"]["exposure_band"] in {
        "low",
        "moderate",
        "high",
    }
    assert result.data["land_cover_mix_pct"]["built_up"] > 0


@pytest.mark.unit
def test_clms_land_cover_year_fallback(monkeypatch):
    from modules.hazards import clms_land_cover_exposure as mod

    monkeypatch.setattr(
        mod,
        "reverse_geocode",
        lambda lat, lon: {"city": "Paris", "country": "France", "country_iso": "FR"},
    )
    monkeypatch.setattr(mod, "_oauth_token", lambda: "token")

    lcm10_valid = np.array(
        [
            [90, 90, 90, 10],
            [90, 90, 10, 10],
            [90, 90, 90, 90],
            [90, 90, 90, 90],
        ],
        dtype=np.uint8,
    )
    data_mask_valid = np.ones((4, 4), dtype=np.uint8)
    data_mask_empty = np.zeros((4, 4), dtype=np.uint8)

    def _fake_fetch(**kwargs):
        req_year = int(kwargs["year"])
        if req_year == 2021:
            return lcm10_valid, data_mask_empty
        return lcm10_valid, data_mask_valid

    monkeypatch.setattr(mod, "_fetch_lcm10_raster", _fake_fetch)

    result = mod.clms_land_cover_exposure_tool(
        lat=48.8566,
        lon=2.3522,
        radius_m=1000,
        year=2021,
    )

    assert result.error is False
    assert result.data["source"]["year_used"] == 2020
    assert result.data["processing"]["attempted_years_desc"] == [2021, 2020]
    quality_notes = result.data["quality_notes"]
    assert any(
        "fallback year 2020 was used" in note
        for note in quality_notes
    )
