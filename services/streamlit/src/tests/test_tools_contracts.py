"""
Tests for tools/contracts.py - Shared Pydantic models and tool response contracts.
"""

import pytest
from pydantic import ValidationError

from src.tools.contracts import (
    RiskQuery,
    GeoServerQuery,
    GeoServerRiskQuery,
    make_tool_response,
)


class TestRiskQuery:
    """Tests for RiskQuery Pydantic model."""

    def test_valid_risk_query(self):
        query = RiskQuery(risk_type="flood", region="Paris", bbox=None)
        assert query.risk_type == "flood"
        assert query.region == "Paris"

    def test_with_bbox(self):
        query = RiskQuery(
            risk_type="fire",
            region=None,
            bbox=[-122.5, 37.7, -122.3, 37.9]
        )
        assert query.bbox == [-122.5, 37.7, -122.3, 37.9]

    def test_required_risk_type(self):
        with pytest.raises(ValidationError):
            RiskQuery(region="Paris", bbox=None)  # Missing risk_type

    def test_all_fields_required(self):
        # RiskQuery requires all fields (risk_type, region, bbox)
        query = RiskQuery(risk_type="flood", region="Paris", bbox=[1.0, 2.0, 3.0, 4.0])
        assert query.risk_type == "flood"
        assert query.region == "Paris"
        assert query.bbox == [1.0, 2.0, 3.0, 4.0]


class TestGeoServerQuery:
    """Tests for GeoServerQuery Pydantic model."""

    def test_valid_query(self):
        query = GeoServerQuery(
            risk_type="flood",
            region="France",
            bbox=None,
            layer_name="georisk:floods"
        )
        assert query.risk_type == "flood"
        assert query.layer_name == "georisk:floods"

    def test_required_layer_name(self):
        with pytest.raises(ValidationError):
            GeoServerQuery(risk_type="flood", region="Paris", bbox=None)


class TestGeoServerRiskQuery:
    """Tests for GeoServerRiskQuery Pydantic model."""

    def test_default_values(self):
        query = GeoServerRiskQuery()
        assert query.layer_name == "georisk:predictions"
        assert query.limit == 500
        assert query.render_mode == "auto"

    def test_all_fields(self):
        query = GeoServerRiskQuery(
            layer_name="custom:layer",
            risk_type="flood",
            region="Europe",
            location="Paris",
            bbox=[2.0, 48.0, 3.0, 49.0],
            start_date="2024-01-01",
            end_date="2024-12-31",
            min_confidence=0.8,
            min_area_m2=100.0,
            model_name="flood_model",
            model_version="v1",
            limit=100,
            render_mode="wms",
        )
        assert query.layer_name == "custom:layer"
        assert query.risk_type == "flood"
        assert query.min_confidence == 0.8
        assert query.render_mode == "wms"

    def test_render_mode_validation(self):
        # Valid modes
        for mode in ["auto", "wms", "geojson"]:
            query = GeoServerRiskQuery(render_mode=mode)
            assert query.render_mode == mode

        # Invalid mode
        with pytest.raises(ValidationError):
            GeoServerRiskQuery(render_mode="invalid")


class TestMakeToolResponse:
    """Tests for make_tool_response function."""

    def test_minimal_response(self):
        response = make_tool_response(
            tool_name="test_tool",
            message="Test message",
            error=False,
        )

        assert response["tool_name"] == "test_tool"
        assert response["message"] == "Test message"
        assert response["error"] is False

    def test_all_required_keys_present(self):
        response = make_tool_response(
            tool_name="test",
            message="msg",
            error=False,
        )

        required_keys = [
            "message", "artifacts", "tool_name", "start_date",
            "end_date", "country", "city", "coordinates", "data", "error"
        ]
        for key in required_keys:
            assert key in response

    def test_default_artifacts(self):
        response = make_tool_response(
            tool_name="test",
            message="msg",
            error=False,
        )

        assert response["artifacts"]["maps"] == []
        assert response["artifacts"]["thumbnails"] == []
        assert response["artifacts"]["urls"] == []

    def test_custom_artifacts(self):
        artifacts = {
            "maps": ["map1.html", "map2.html"],
            "thumbnails": ["thumb1.png"],
            "urls": ["https://example.com"],
        }
        response = make_tool_response(
            tool_name="test",
            message="msg",
            artifacts=artifacts,
            error=False,
        )

        assert response["artifacts"] == artifacts

    def test_partial_artifacts_normalized(self):
        response = make_tool_response(
            tool_name="test",
            message="msg",
            artifacts={"maps": ["map1"]},  # Missing thumbnails and urls
            error=False,
        )

        assert response["artifacts"]["maps"] == ["map1"]
        assert response["artifacts"]["thumbnails"] == []
        assert response["artifacts"]["urls"] == []

    def test_date_fields(self):
        response = make_tool_response(
            tool_name="test",
            message="msg",
            start_date="2024-01-01",
            end_date="2024-12-31",
            error=False,
        )

        assert response["start_date"] == "2024-01-01"
        assert response["end_date"] == "2024-12-31"

    def test_location_fields(self):
        response = make_tool_response(
            tool_name="test",
            message="msg",
            country="France",
            city="Paris",
            coordinates={"lat": 48.8566, "lon": 2.3522},
            error=False,
        )

        assert response["country"] == "France"
        assert response["city"] == "Paris"
        assert response["coordinates"]["lat"] == 48.8566
        assert response["coordinates"]["lon"] == 2.3522

    def test_data_field(self):
        data = {"fires_count": 5, "severity": "high"}
        response = make_tool_response(
            tool_name="test",
            message="msg",
            data=data,
            error=False,
        )

        assert response["data"] == data

    def test_error_true(self):
        response = make_tool_response(
            tool_name="test",
            message="Error occurred",
            error=True,
        )

        assert response["error"] is True

    def test_error_coerced_to_bool(self):
        response = make_tool_response(
            tool_name="test",
            message="msg",
            error=1,  # Truthy value
        )

        assert response["error"] is True

        response2 = make_tool_response(
            tool_name="test",
            message="msg",
            error=0,  # Falsy value
        )

        assert response2["error"] is False

    def test_none_values_preserved(self):
        response = make_tool_response(
            tool_name="test",
            message="msg",
            start_date=None,
            end_date=None,
            country=None,
            city=None,
            coordinates=None,
            data=None,
            error=False,
        )

        assert response["start_date"] is None
        assert response["end_date"] is None
        assert response["country"] is None
        assert response["city"] is None
        assert response["coordinates"] is None
        assert response["data"] is None
