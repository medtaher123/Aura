import pytest


def assert_tool_response(resp: dict, tool_name: str) -> None:
    assert isinstance(resp, dict)

    # Contract keys from src/tools/contracts.py
    expected_keys = {
        "message",
        "artifacts",
        "tool_name",
        "start_date",
        "end_date",
        "country",
        "city",
        "coordinates",
        "data",
        "error",
    }
    assert expected_keys.issubset(resp.keys())

    assert resp["tool_name"] == tool_name
    assert isinstance(resp["message"], str)
    assert resp["message"].strip() != ""

    assert isinstance(resp["error"], bool)

    artifacts = resp["artifacts"]
    assert isinstance(artifacts, dict)
    assert "maps" in artifacts and isinstance(artifacts["maps"], list)
    assert "thumbnails" in artifacts and isinstance(artifacts["thumbnails"], list)
    assert "urls" in artifacts and isinstance(artifacts["urls"], list)


class _DummyResponse:
    def __init__(self, *, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_get_date_tool_smoke():
    from src.tools.tools import get_date

    resp = get_date.invoke({})
    assert_tool_response(resp, "get_date")
    assert resp["error"] is False


def test_get_time_tool_smoke():
    from src.tools.tools import get_time

    resp = get_time.invoke({})
    assert_tool_response(resp, "get_time")
    assert resp["error"] is False


def test_calculator_tool_smoke():
    from src.tools.tools import calculator

    resp = calculator.invoke({"expression": "2 + 3 * 4"})
    assert_tool_response(resp, "calculator")
    assert resp["error"] is False
    assert resp.get("data", {}).get("result") == "14"


def test_query_stac_catalog_smoke(monkeypatch):
    from src.tools.tools_stac import query_stac_catalog
    import src.tools.tools_stac as mod

    monkeypatch.setattr(
        mod,
        "get_city_bbox",
        lambda city: ([52.3, 52.6, 13.1, 13.6], 52.52, 13.405, "Berlin"),
    )

    def fake_post(*args, **kwargs):
        return _DummyResponse(
            status_code=200,
            payload={
                "features": [
                    {
                        "properties": {"eo:cloud_cover": 12.3},
                        "assets": {"thumbnail": {"href": "https://example.com/thumb.png"}},
                    }
                ]
            },
        )

    monkeypatch.setattr(mod.requests, "post", fake_post)

    resp = query_stac_catalog.invoke(
        {
            "city": "Berlin",
            "start_date": "2024-01-01",
            "end_date": "2024-01-01",
            "collection": "sentinel-2-l2a",
            "limit_per_day": 1,
        }
    )
    assert_tool_response(resp, "query_stac_catalog")
    assert resp["error"] is False
    assert resp["artifacts"]["thumbnails"]


def test_detect_fire_tool_smoke(monkeypatch):
    from src.tools.fire_detection import detect_fire_tool
    import src.tools.fire_detection as mod

    monkeypatch.setattr(
        mod,
        "detect_fire_near_city",
        lambda start_date, end_date, city_name, radius_km: (
            [
                {
                    "lat": 52.5,
                    "lon": 13.4,
                    "brightness": 350.0,
                    "acq_date": "2024-01-01",
                    "acq_time": "1200",
                }
            ],
            1,
        ),
    )
    monkeypatch.setattr(mod, "get_city_bbox", lambda city: ([0, 0, 0, 0], 52.52, 13.405, city))

    resp = detect_fire_tool.invoke(
        {
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "location": "Berlin",
            "radius_km": 200,
        }
    )

    assert_tool_response(resp, "detect_fire_tool")
    assert resp["error"] is False
    assert resp["artifacts"]["maps"], "Expected a fire map spec"


def test_query_disaster_events_tool_smoke(monkeypatch):
    from src.tools.disaster_detection import query_disaster_events_tool
    import src.tools.disaster_detection as mod

    monkeypatch.setattr(mod, "get_iso3_from_country_name", lambda name: "DEU")

    events = [
        {
            "disastertype": "Flood",
            "country": "Germany",
            "location": "Berlin",
            "startyear": 2024,
            "startmonth": 1,
            "startday": 2,
            "endyear": 2024,
            "endmonth": 1,
            "endday": 5,
            "totaldeaths": 0,
            "totalaffected": 100,
            "origin": "Test",
            "latitude": 52.52,
            "longitude": 13.405,
        }
    ]
    monkeypatch.setattr(mod, "get_emdat_by_iso3", lambda iso3: events)

    resp = query_disaster_events_tool.invoke(
        {
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "location": None,
            "country_name": "Germany",
            "disaster_type": "flood",
        }
    )

    assert_tool_response(resp, "query_disaster_events_tool")
    assert resp["error"] is False
    assert resp.get("data", {}).get("events"), "Expected at least one event"

    # Also accept list-valued disaster_type and return events_by_type hashmap
    resp2 = query_disaster_events_tool.invoke(
        {
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "location": None,
            "country_name": "Germany",
            "disaster_type": ["flood", "storm"],
        }
    )
    assert_tool_response(resp2, "query_disaster_events_tool")
    assert resp2["error"] is False
    assert isinstance(resp2.get("data", {}).get("events_by_type"), dict)
    assert "flood" in resp2.get("data", {}).get("events_by_type", {})


def test_estimate_surface_water_ingress_tool_smoke(monkeypatch):
    from src.tools.water_ingress import estimate_surface_water_ingress_tool
    import src.tools.water_ingress as mod

    monkeypatch.setattr(
        mod,
        "estimate_surface_water_ingress",
        lambda location_input: {
            "Ingress_paths_estimate": "Water follows flow paths to low points.",
            "Mitigation_actions": [{"description": "Test action", "resource": "https://example.com"}],
            "Maps": {"Risk_points": [{"lat": 48.8566, "lon": 2.3522}]},
            "Explanation": "Test explanation",
            "Location": {"city": "Paris", "country": "France", "country_iso": "FR"},
            "Coordinates": {"lat": 48.8566, "lon": 2.3522},
        },
    )

    resp = estimate_surface_water_ingress_tool.invoke({"location_input": "Paris"})

    assert_tool_response(resp, "estimate_surface_water_ingress_tool")
    assert resp["error"] is False
    assert resp["artifacts"]["maps"], "Expected a risk map spec"


def test_get_route_info_smoke(monkeypatch):
    from src.tools.itinerary import get_route_info
    import src.tools.itinerary as mod

    monkeypatch.setattr(mod, "geocode_place", lambda name: (48.8566, 2.3522) if "Paris" in name else (45.764, 4.8357))

    def fake_get_route(origin, destination):
        return {
            "code": "Ok",
            "routes": [
                {
                    "distance": 10000,
                    "duration": 1800,
                    "legs": [
                        {
                            "steps": [
                                {
                                    "distance": 500,
                                    "maneuver": {"type": "depart"},
                                    "name": "Rue A",
                                    "geometry": {"coordinates": [[2.3522, 48.8566], [2.36, 48.86]]},
                                },
                                {
                                    "distance": 9500,
                                    "maneuver": {"type": "arrive"},
                                    "name": "Rue B",
                                    "geometry": {"coordinates": [[4.83, 45.76], [4.8357, 45.764]]},
                                },
                            ]
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(mod, "get_route", fake_get_route)

    resp = get_route_info.invoke({"source": "Paris", "destination": "Lyon"})

    assert_tool_response(resp, "get_route_info")
    assert resp["error"] is False
    assert resp["artifacts"]["maps"], "Expected a route map spec"


def test_weather_tool_smoke(monkeypatch):
    from src.tools.weather import weather_tool
    import src.tools.weather as mod

    monkeypatch.setattr(mod, "get_city_bbox", lambda city: ([0, 0, 0, 0], 52.52, 13.405, "Berlin"))

    monkeypatch.setattr(
        mod.requests,
        "get",
        lambda url, params=None: _DummyResponse(
            status_code=200,
            payload={
                "current_weather": {"temperature": 10.5, "windspeed": 5.0},
                "daily": {
                    "time": ["2024-01-01", "2024-01-02"],
                    "temperature_2m_max": [12, 13],
                    "temperature_2m_min": [5, 6],
                    "precipitation_sum": [0.0, 1.2],
                },
            },
        ),
    )

    resp = weather_tool.invoke({"city_name": "Berlin", "forecast_days": 2})

    assert_tool_response(resp, "weather_tool")
    assert resp["error"] is False


def test_general_question_tool_smoke(monkeypatch):
    from src.tools.general_chat import general_question_tool
    import src.tools.general_chat as mod

    class _DummyLLM:
        def invoke(self, prompt: str) -> str:
            return "This is a test answer."

    monkeypatch.setattr(mod, "llm", _DummyLLM())

    resp = general_question_tool.invoke({"query_text": "What is a ReAct agent?"})

    assert_tool_response(resp, "general_question_tool")
    assert resp["error"] is False


def test_geoserver_risk_mask_tool_smoke(monkeypatch):
    from src.tools.risk_geoserver import geoserver_risk_mask_tool
    import src.tools.risk_geoserver as mod

    monkeypatch.setattr(
        mod,
        "_wfs_get_features",
        lambda **kwargs: {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"risk_type": "flood", "region": "X", "confidence": 0.8, "area_m2": 1234},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
                        ],
                    },
                }
            ],
        },
    )

    resp = geoserver_risk_mask_tool.invoke(
        {
            "risk_type": "flood",
            "location": "Casablanca",
            "bbox": [0.0, 0.0, 1.0, 1.0],
            "render_mode": "geojson",
        }
    )

    assert_tool_response(resp, "geoserver_risk_mask_tool")
    assert resp["error"] is False
    assert resp["artifacts"]["maps"], "Expected a GeoServer map spec"


def test_query_hazards_tool_smoke(monkeypatch):
    from src.tools.hazard_detection import query_hazards_tool
    import src.tools.hazard_detection as mod

    monkeypatch.setattr(mod, "get_top_hazards_for_country", lambda country, n=5: [{"hazard": "Flood", "level": "High", "score": 4.0}])
    monkeypatch.setattr(mod, "get_city_bbox", lambda loc: ([0, 0, 0, 0], 35.0, 139.0, "Tokyo"))

    resp = query_hazards_tool.invoke({"country": "Japan", "top_n": 1, "location": "Tokyo"})

    assert_tool_response(resp, "query_hazards_tool")
    assert resp["error"] is False
    assert resp.get("data", {}).get("hazards"), "Expected at least one hazard"


def test_geo_info_tool_smoke(monkeypatch):
    from src.tools.geographic_info import geo_info_tool
    import src.tools.geographic_info as mod

    monkeypatch.setattr(
        mod,
        "get_country_info",
        lambda name: {
            "Type": "Country",
            "Name": "France",
            "Capital": "Paris",
            "Population": 1,
            "Area (km²)": 1,
            "Region": "Europe",
            "Subregion": "Western Europe",
            "Languages": ["French"],
            "Currency": "Euro",
            "Flag": "https://example.com/flag.png",
        },
    )

    resp = geo_info_tool.invoke({"name": "France"})

    assert_tool_response(resp, "geo_info_tool")
    assert resp["error"] is False


@pytest.mark.parametrize(
    "tool_import_path, expected_name",
    [
        ("src.tools.tools_stac:query_stac_catalog", "query_stac_catalog"),
        ("src.tools.fire_detection:detect_fire_tool", "detect_fire_tool"),
        ("src.tools.disaster_detection:query_disaster_events_tool", "query_disaster_events_tool"),
        ("src.tools.water_ingress:estimate_surface_water_ingress_tool", "estimate_surface_water_ingress_tool"),
        ("src.tools.itinerary:get_route_info", "get_route_info"),
        ("src.tools.weather:weather_tool", "weather_tool"),
        ("src.tools.general_chat:general_question_tool", "general_question_tool"),
        ("src.tools.risk_geoserver:geoserver_risk_mask_tool", "geoserver_risk_mask_tool"),
        ("src.tools.hazard_detection:query_hazards_tool", "query_hazards_tool"),
        ("src.tools.geographic_info:geo_info_tool", "geo_info_tool"),
    ],
)
def test_tools_are_langchain_tools(tool_import_path: str, expected_name: str):
    module_path, attr = tool_import_path.split(":", 1)
    mod = __import__(module_path, fromlist=[attr])
    tool_obj = getattr(mod, attr)

    # Basic LangChain tool interface check
    assert getattr(tool_obj, "name", None) == expected_name
    assert hasattr(tool_obj, "invoke")
