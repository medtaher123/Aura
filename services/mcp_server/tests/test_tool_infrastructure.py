"""
Tests for infrastructure query tool.
"""

import pytest

from utils.bbox_service import LocationAmbiguousError
from tools import infrastructure as infra


class FakeAthenaClient:
    def __init__(self, rows=None):
        if rows is None:
            rows = [
                {
                    "Data": [
                        {"VarCharValue": "amenity"},
                        {"VarCharValue": "building"},
                        {"VarCharValue": "landuse"},
                        {"VarCharValue": "industrial"},
                        {"VarCharValue": "count"},
                    ]
                },
                {
                    "Data": [
                        {"VarCharValue": "hospital"},
                        {"VarCharValue": ""},
                        {"VarCharValue": ""},
                        {"VarCharValue": ""},
                        {"VarCharValue": "3"},
                    ]
                },
            ]
        self._rows = rows

    def start_query_execution(self, **_kwargs):
        return {"QueryExecutionId": "test-query-id"}

    def get_query_execution(self, **_kwargs):
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_query_results(self, **_kwargs):
        return {"ResultSet": {"Rows": self._rows}}


class FakeS3Client:
    def __init__(self, region="eu-west-3"):
        self._region = region

    def get_bucket_location(self, **_kwargs):
        if self._region == "us-east-1":
            return {"LocationConstraint": None}
        return {"LocationConstraint": self._region}


def _patch_athena(monkeypatch, rows=None):
    def _client(service_name, **kwargs):
        if service_name == "s3":
            region = kwargs.get("region_name") or "eu-west-3"
            return FakeS3Client(region=region)
        return FakeAthenaClient(rows=rows)

    monkeypatch.setattr(infra.boto3, "client", _client)
    monkeypatch.setattr(infra.time, "sleep", lambda *args, **kwargs: None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_infrastructure_tool_exists(mcp_client):
    """Test infrastructure tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "infrastructure_query_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
async def test_infrastructure_tool_with_city(mcp_client, monkeypatch):
    """Test infrastructure tool accepts a city name."""
    _patch_athena(monkeypatch)

    def fake_get_city_bbox(_location, **_kwargs):
        return ["48.81", "48.90", "2.25", "2.42"], "48.8566", "2.3522", "Paris"

    monkeypatch.setattr(infra, "get_city_bbox", fake_get_city_bbox)

    result = await mcp_client.call_tool(
        "infrastructure_query_tool",
        {
            "location": "Paris",
            "radius_km": 10,
            "infrastructure_types": ["hospital"],
        },
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "infrastructure_query_tool"
    coords = result.get("coordinates") or {}
    assert coords.get("lat") == pytest.approx(48.8566, abs=0.01)
    assert coords.get("lon") == pytest.approx(2.3522, abs=0.01)
    assert result.get("city") == "Paris"
    assert result.get("data", {}).get("infrastructure")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_infrastructure_tool_with_coordinates(mcp_client, monkeypatch):
    """Test infrastructure tool accepts coordinate parameters."""
    _patch_athena(monkeypatch)

    def fake_reverse_geocode(_lat, _lon):
        return {"city": "Berlin", "country": "Germany"}

    monkeypatch.setattr(infra, "reverse_geocode", fake_reverse_geocode)

    result = await mcp_client.call_tool(
        "infrastructure_query_tool", {"lat": 52.52, "lon": 13.405}
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "infrastructure_query_tool"
    coords = result.get("coordinates") or {}
    assert coords.get("lat") == pytest.approx(52.52, abs=0.01)
    assert coords.get("lon") == pytest.approx(13.405, abs=0.01)
    assert result.get("city") == "Berlin"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_infrastructure_tool_ambiguous_location(mcp_client, monkeypatch):
    """Test infrastructure tool returns disambiguation data."""
    _patch_athena(monkeypatch)

    candidates = [
        {
            "display_name": "Springfield, USA",
            "name": "Springfield",
            "lat": 39.78,
            "lon": -89.64,
            "bbox": [39.75, 39.82, -89.68, -89.60],
        },
        {
            "display_name": "Springfield, UK",
            "name": "Springfield",
            "lat": 55.95,
            "lon": -3.20,
            "bbox": [55.90, 56.00, -3.30, -3.10],
        },
    ]

    def fake_get_city_bbox(_location, **_kwargs):
        raise LocationAmbiguousError(query="Springfield", candidates=candidates)

    monkeypatch.setattr(infra, "get_city_bbox", fake_get_city_bbox)

    result = await mcp_client.call_tool(
        "infrastructure_query_tool", {"location": "Springfield"}
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "infrastructure_query_tool"
    assert result.get("data", {}).get("needs_location_confirmation") is True
    assert result.get("error") is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_infrastructure_tool_missing_input(mcp_client):
    """Test infrastructure tool handles missing inputs."""
    result = await mcp_client.call_tool("infrastructure_query_tool", {})
    assert isinstance(result, dict)
    assert result.get("error") is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_infrastructure_tool_hospitals_near_paris_group_breakdown(
    mcp_client, monkeypatch
):
    """
    Test hospitals near Paris within 10km returns correct group_breakdown structure.
    Verifies output correctness: group_breakdown should be {'hospital': {'hospital': 33}}.
    """
    # Mock Athena rows: hospital count = 33 for Paris 10km
    hospital_rows = [
        {
            "Data": [
                {"VarCharValue": "amenity"},
                {"VarCharValue": "building"},
                {"VarCharValue": "landuse"},
                {"VarCharValue": "industrial"},
                {"VarCharValue": "count"},
            ]
        },
        {
            "Data": [
                {"VarCharValue": "hospital"},
                {"VarCharValue": ""},
                {"VarCharValue": ""},
                {"VarCharValue": ""},
                {"VarCharValue": "33"},
            ]
        },
    ]
    _patch_athena(monkeypatch, rows=hospital_rows)

    def fake_get_city_bbox(_location, **_kwargs):
        return ["48.81", "48.90", "2.25", "2.42"], "48.8566", "2.3522", "Paris"

    monkeypatch.setattr(infra, "get_city_bbox", fake_get_city_bbox)

    # Set env so tool proceeds past ATHENA_OUTPUT checks
    monkeypatch.setenv("ATHENA_OUTPUT", "s3://test-infra-bucket/results/")
    monkeypatch.setenv("AWS_REGION", "eu-west-3")

    result = await mcp_client.call_tool(
        "infrastructure_query_tool",
        {
            "location": "Paris",
            "radius_km": 10,
            "infrastructure_types": ["hospital"],
        },
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "infrastructure_query_tool"
    assert result.get("error") is False
    assert result.get("city") == "Paris"
    coords = result.get("coordinates") or {}
    assert coords.get("lat") == pytest.approx(48.8566, abs=0.01)
    assert coords.get("lon") == pytest.approx(2.3522, abs=0.01)

    data = result.get("data", {})
    assert "group_breakdown" in data, "response must include group_breakdown"
    group_breakdown = data["group_breakdown"]
    assert group_breakdown == {"hospital": {"hospital": 33}}, (
        f"group_breakdown should be {{'hospital': {{'hospital': 33}}}}, "
        f"got {group_breakdown}"
    )
