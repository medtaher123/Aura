"""Unit tests for TerraZard hazard mask repository caching."""

from __future__ import annotations

import pytest

from modules.flood.terrazard import repository as repo_mod
from modules.flood.terrazard.repository import HazardMaskRepository, MapStats


@pytest.mark.unit
def test_get_map_stats_caches_identical_arguments(monkeypatch):
    calls: list[dict] = []

    def fake_execute(query, params):
        calls.append(dict(params))
        return [
            {
                "total_polygons": 10,
                "water_count": 8,
                "cloud_count": 2,
                "avg_lat": 48.85,
                "avg_lon": 2.35,
            }
        ]

    monkeypatch.setattr(repo_mod, "execute_read_query", fake_execute)
    repo_mod._fetch_map_stats_cached.cache_clear()

    bbox = [48.8, 48.9, 2.2, 2.5]
    first = HazardMaskRepository().get_map_stats("20240315", "flood80", bbox)
    second = HazardMaskRepository().get_map_stats("20240315", "flood80", list(bbox))

    assert first == second == MapStats(10, 8, 2, 48.85, 2.35)
    assert len(calls) == 1

    HazardMaskRepository().get_map_stats("20240316", "flood80", bbox)
    assert len(calls) == 2
