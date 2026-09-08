"""
Tests for infrastructure query tool.
"""

import pytest

from utils.bbox_service import LocationAmbiguousError
from modules.geospatial import infrastructure as infra


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
    assert "bdtopo_buildings_by_cleabs_tool" in tool_names


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
    assert result.get("coordinates") == {"lat": 48.8566, "lon": 2.3522, "zoom": None}
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
    assert result.get("coordinates") == {"lat": 52.52, "lon": 13.405, "zoom": None}
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
    assert result.get("coordinates") == {"lat": 48.8566, "lon": 2.3522, "zoom": None}

    data = result.get("data", {})
    assert "group_breakdown" in data, "response must include group_breakdown"
    group_breakdown = data["group_breakdown"]
    assert group_breakdown == {"hospital": {"hospital": 33}}, (
        f"group_breakdown should be {{'hospital': {{'hospital': 33}}}}, "
        f"got {group_breakdown}"
    )


@pytest.mark.unit
def test_bdtopo_buildings_by_cleabs_single(monkeypatch):
    def fake_get_batiment_columns():
        return {
            "cleabs",
            "nature",
            "usage_1",
            "nombre_d_etages",
            "hauteur",
            "geometrie",
        }

    def fake_run_query(_sql_query, params=()):
        requested, _order, _limit = params
        assert requested == ["BATIMENT0001"]
        return [
            {
                "cleabs": "BATIMENT0001",
                "nature": "Indifferencie",
                "usage_1": "Residentiel",
                "nombre_d_etages": 3,
                "hauteur": 11.5,
            }
        ]

    monkeypatch.setattr(infra, "_get_batiment_columns", fake_get_batiment_columns)
    monkeypatch.setattr(infra, "_run_bdtopo_query", fake_run_query)

    result = infra.bdtopo_buildings_by_cleabs_tool("BATIMENT0001")

    assert result.tool_name == "bdtopo_buildings_by_cleabs_tool"
    assert result.error is False
    assert result.coordinates is None
    assert result.data["found_cleabs"] == ["BATIMENT0001"]
    assert result.data["missing_cleabs"] == []
    assert result.data["include_geometry"] is False
    assert len(result.data["matches"]) == 1
    assert result.data["matches"][0]["label"] == "BATIMENT0001"
    assert result.data["matches"][0]["source_table"] == "bdtopo_raw.batiment"
    assert result.artifacts.maps == []


@pytest.mark.unit
def test_bdtopo_buildings_by_cleabs_projects_available_attributes(monkeypatch):
    captured = {}
    available = {
        "cleabs",
        "identifiants_rnb",
        "nature",
        "usage_1",
        "usage_2",
        "etat_de_l_objet",
        "nombre_d_etages",
        "nombre_de_logements",
        "hauteur",
        "altitude_minimale_sol",
        "altitude_maximale_toit",
        "materiaux_des_murs",
        "materiaux_de_la_toiture",
        "origine_du_batiment",
        "geometrie",
        "fid",
        "loaded_at",
        "source_file",
    }

    def fake_run_query(sql_query, params=()):
        captured["sql"] = str(sql_query)
        return [{"cleabs": "BATIMENT0001", "identifiants_rnb": "RNB-1"}]

    monkeypatch.setattr(infra, "_get_batiment_columns", lambda: available)
    monkeypatch.setattr(infra, "_run_bdtopo_query", fake_run_query)

    result = infra.bdtopo_buildings_by_cleabs_tool("BATIMENT0001")

    sql = captured["sql"]
    assert "identifiants_rnb" in sql
    assert "nombre_de_logements" in sql
    assert "materiaux_des_murs" in sql
    assert "altitude_minimale_sol" in sql
    assert "loaded_at" not in sql
    assert "source_file" not in sql
    assert result.data["matches"][0]["identifiants_rnb"] == "RNB-1"


@pytest.mark.unit
def test_bdtopo_buildings_by_cleabs_multiple_with_missing(monkeypatch):
    def fake_get_batiment_columns():
        return {"cleabs", "nature", "usage_1", "geometrie"}

    def fake_run_query(_sql_query, params=()):
        requested, _order, limit = params
        assert requested == ["BATIMENT0001", "BATIMENT0002", "BATIMENT0003"]
        assert limit == 3
        return [
            {
                "cleabs": "BATIMENT0002",
                "nature": "Indifferencie",
                "usage_1": "Residentiel",
                "feature_lat": 43.2965,
                "feature_lon": 5.3698,
                "geom_geojson": {
                    "type": "Polygon",
                    "coordinates": [[[5.36, 43.29], [5.37, 43.29], [5.37, 43.30], [5.36, 43.30], [5.36, 43.29]]],
                },
            }
        ]

    monkeypatch.setattr(infra, "_get_batiment_columns", fake_get_batiment_columns)
    monkeypatch.setattr(infra, "_run_bdtopo_query", fake_run_query)

    result = infra.bdtopo_buildings_by_cleabs_tool(
        ["BATIMENT0001", "BATIMENT0002", "BATIMENT0002", "BATIMENT0003"]
    )

    assert result.error is False
    assert result.data["requested_cleabs"] == [
        "BATIMENT0001",
        "BATIMENT0002",
        "BATIMENT0003",
    ]
    assert result.data["found_cleabs"] == ["BATIMENT0002"]
    assert result.data["missing_cleabs"] == ["BATIMENT0001", "BATIMENT0003"]
    assert "Missing: BATIMENT0001, BATIMENT0003." in result.message


@pytest.mark.unit
def test_bdtopo_buildings_by_cleabs_requires_values():
    result = infra.bdtopo_buildings_by_cleabs_tool(["", "   "])
    assert result.error is True
    assert result.data["requested_cleabs"] == []


@pytest.mark.unit
def test_bdtopo_buildings_by_cleabs_without_geometry(monkeypatch):
    captured = {}

    def fake_get_batiment_columns():
        return {
            "cleabs",
            "nature",
            "usage_1",
            "geometrie",
        }

    def fake_run_query(sql_query, params=()):
        captured["sql"] = str(sql_query)
        requested, _order, _limit = params
        assert requested == ["BATIMENT0001"]
        return [
            {
                "cleabs": "BATIMENT0001",
                "nature": "Indifferencie",
                "usage_1": "Residentiel",
            }
        ]

    monkeypatch.setattr(infra, "_get_batiment_columns", fake_get_batiment_columns)
    monkeypatch.setattr(infra, "_run_bdtopo_query", fake_run_query)

    result = infra.bdtopo_buildings_by_cleabs_tool(
        "BATIMENT0001",
        include_geometry=False,
    )

    assert result.error is False
    assert "ST_AsGeoJSON" not in captured["sql"]
    assert "ST_PointOnSurface" not in captured["sql"]
    assert result.coordinates is None
    assert result.artifacts.maps == []
    assert result.data["include_geometry"] is False
    assert result.data["matches"][0].get("geom_geojson") is None


@pytest.mark.unit
def test_bdtopo_buildings_by_cleabs_with_geometry(monkeypatch):
    def fake_get_batiment_columns():
        return {
            "cleabs",
            "nature",
            "usage_1",
            "nombre_d_etages",
            "hauteur",
            "geometrie",
        }

    def fake_run_query(_sql_query, params=()):
        requested, _order, _limit = params
        assert requested == ["BATIMENT0001"]
        return [
            {
                "cleabs": "BATIMENT0001",
                "nature": "Indifferencie",
                "usage_1": "Residentiel",
                "nombre_d_etages": 3,
                "hauteur": 11.5,
                "feature_lat": 48.8567,
                "feature_lon": 2.3523,
                "geom_geojson": {
                    "type": "Polygon",
                    "coordinates": [[[2.35, 48.85], [2.36, 48.85], [2.36, 48.86], [2.35, 48.86], [2.35, 48.85]]],
                },
            }
        ]

    monkeypatch.setattr(infra, "_get_batiment_columns", fake_get_batiment_columns)
    monkeypatch.setattr(infra, "_run_bdtopo_query", fake_run_query)

    result = infra.bdtopo_buildings_by_cleabs_tool(
        "BATIMENT0001",
        include_geometry=True,
    )

    assert result.coordinates is not None
    assert result.coordinates.model_dump() == {
        "lat": 48.8567,
        "lon": 2.3523,
        "zoom": None,
    }
    assert result.data["include_geometry"] is True
    assert result.artifacts.maps[0]["tooltip"]["text"].startswith("CLEABS: {cleabs}")
    view_state = result.artifacts.maps[0]["view_state"]
    assert abs(view_state["latitude"] - 48.855) < 0.01
    assert abs(view_state["longitude"] - 2.355) < 0.01
    assert view_state["zoom"] >= 16.0
