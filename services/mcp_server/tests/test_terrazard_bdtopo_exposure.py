"""Unit tests for BDTOPO exposure mapping helpers."""

from __future__ import annotations

import pytest

from modules.flood.terrazard.bdtopo_exposure import map_usage_to_asset, map_vegetation_to_asset


@pytest.mark.unit
def test_map_usage_to_asset_residential():
    assert map_usage_to_asset("Résidentiel") == "residential"


@pytest.mark.unit
def test_map_usage_to_asset_commercial():
    assert map_usage_to_asset("Commercial et services") == "commercial"


@pytest.mark.unit
def test_map_usage_to_asset_unknown_defaults_residential():
    assert map_usage_to_asset("Unknown usage") == "residential"


@pytest.mark.unit
def test_map_vegetation_to_asset_agriculture():
    assert map_vegetation_to_asset("Terre labourée") == "agriculture"


@pytest.mark.unit
def test_map_vegetation_to_asset_non_agriculture_returns_none():
    assert map_vegetation_to_asset("Forêt fermée") is None


@pytest.mark.unit
def test_empty_touched_buildings():
    from modules.flood.terrazard.bdtopo_exposure import empty_touched_buildings

    assert empty_touched_buildings() == {
        "type": "FeatureCollection",
        "features": [],
    }
