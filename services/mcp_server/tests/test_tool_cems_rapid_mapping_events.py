"""Tests for CEMS rapid mapping events tool."""

from __future__ import annotations

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cems_rapid_mapping_events_tool_exists(mcp_client):
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "cems_rapid_mapping_events_tool" in tool_names


@pytest.mark.unit
def test_cems_tool_requires_at_least_one_location_mode():
    from modules.hazards.cems_rapid_mapping_events import cems_rapid_mapping_events_tool

    result = cems_rapid_mapping_events_tool()
    assert result.error is True
    assert "Unable to resolve AOI from provided inputs." in result.message


@pytest.mark.unit
def test_cems_tool_prefers_polygon_over_latlon_and_location(monkeypatch):
    from modules.hazards import cems_rapid_mapping_events as mod

    monkeypatch.setattr(mod, "_fetch_activation_info_pages", lambda **_kwargs: [])

    result = mod.cems_rapid_mapping_events_tool(
        polygon_wkt="POLYGON ((-1 40, 1 40, 1 41, -1 41, -1 40))",
        lat=999.0,
        lon=999.0,
        location="Madrid",
        start_date="2020-01-01",
        end_date="2020-12-31",
    )
    assert result.error is False
    assert result.data["activations"] == []


@pytest.mark.unit
def test_cems_tool_location_ambiguity(monkeypatch):
    from modules.hazards import cems_rapid_mapping_events as mod

    monkeypatch.setattr(
        mod,
        "get_city_candidates",
        lambda *_args, **_kwargs: [
            {
                "display_name": "Paris, France",
                "lat": 48.8566,
                "lon": 2.3522,
                "bbox": [48.80, 48.90, 2.20, 2.45],
                "place_id": 1,
                "osm_id": 1,
                "osm_type": "R",
            },
            {
                "display_name": "Paris, Texas, USA",
                "lat": 33.66,
                "lon": -95.55,
                "bbox": [33.60, 33.70, -95.60, -95.50],
                "place_id": 2,
                "osm_id": 2,
                "osm_type": "R",
            },
        ],
    )

    result = mod.cems_rapid_mapping_events_tool(location="Paris")
    assert result.error is True
    assert "Location is ambiguous" in result.message


@pytest.mark.unit
def test_cems_tool_success_with_mocked_api(monkeypatch):
    from modules.hazards import cems_rapid_mapping_events as mod

    monkeypatch.setattr(
        mod,
        "get_city_candidates",
        lambda *_args, **_kwargs: [
            {
                "display_name": "Madrid, Spain",
                "lat": 40.4168,
                "lon": -3.7038,
                "bbox": [40.30, 40.55, -3.90, -3.50],
                "place_id": 10,
                "osm_id": 10,
                "osm_type": "R",
            }
        ],
    )

    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    info_payload = {
        "count": 1,
        "next": None,
        "results": [
            {
                "code": "EMSR999",
                "name": "Flood in Madrid",
                "category": "Flood",
                "activationTime": "2020-06-02T10:00:00",
            }
        ],
    }
    detail_payload = {
        "count": 1,
        "next": None,
        "results": [
            {
                "code": "EMSR999",
                "name": "Flood in Madrid",
                "category": "Flood",
                "subCategory": "River flood",
                "eventTime": "2020-06-01T10:00:00",
                "activationTime": "2020-06-02T10:00:00",
                "closed": False,
                "countries": [{"name": "Spain"}],
                "extent": "POLYGON ((-3.9 40.3, -3.5 40.3, -3.5 40.55, -3.9 40.55, -3.9 40.3))",
                "aois": [
                    {
                        "name": "Madrid AOI",
                        "number": 1,
                        "extent": "POLYGON ((-3.85 40.35, -3.55 40.35, -3.55 40.50, -3.85 40.50, -3.85 40.35))",
                        "products": [
                            {
                                "id": 100,
                                "type": "GRA",
                                "feasible": True,
                                "expectedDelivery": "2020-06-03T12:00:00",
                                "downloadPath": "https://example.com/p.zip",
                                "version": {"statusCode": "F", "deliveryTime": "2020-06-03T11:00:00"},
                                "layers": [{"name": "layer", "format": "cog"}],
                                "stats": {"Built-up": {"Residential": {"affected": 10}}},
                            }
                        ],
                    }
                ],
                "stats": {"Event Extent [ha]": 1200},
                "reportLink": "https://example.com/report",
            }
        ],
    }

    def _fake_get(url, params=None, timeout=25):
        _ = params, timeout
        if "public-activations-info" in url:
            return _Resp(200, info_payload)
        if "public-activations" in url:
            return _Resp(200, detail_payload)
        return _Resp(404, {})

    monkeypatch.setattr(mod.requests, "get", _fake_get)

    result = mod.cems_rapid_mapping_events_tool(
        location="Madrid",
        hazard_types=["flood"],
        start_date="2020-01-01",
        end_date="2020-12-31",
        only_active=True,
        limit=5,
    )

    assert result.error is False
    assert result.tool_name == "cems_rapid_mapping_events_tool"
    assert "Found 1 CEMS rapid-mapping activation" in result.message
    assert len(result.data["activations"]) == 1
    assert result.data["activations"][0]["code"] == "EMSR999"
    assert result.data["activations"][0]["product_type_counts"]["GRA"] == 1
