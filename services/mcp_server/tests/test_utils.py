"""
Tests for MCP utility functions.
"""

import pytest
from utils.contracts import make_tool_response


@pytest.mark.unit
def test_make_tool_response_basic():
    """Test make_tool_response creates valid response."""
    response = make_tool_response(tool_name="test_tool", message="Test message")

    assert isinstance(response, dict)
    assert response["tool_name"] == "test_tool"
    assert response["message"] == "Test message"


@pytest.mark.unit
def test_make_tool_response_with_data():
    """Test make_tool_response includes data."""
    response = make_tool_response(
        tool_name="test_tool",
        message="Test message",
        data={"key": "value", "count": 42},
    )

    assert isinstance(response, dict)
    assert response["data"]["key"] == "value"
    assert response["data"]["count"] == 42


@pytest.mark.unit
def test_make_tool_response_with_error():
    """Test make_tool_response handles error flag."""
    response = make_tool_response(
        tool_name="test_tool", message="Error occurred", error=True
    )

    assert "Error" in response or "error" in response


@pytest.mark.unit
def test_make_tool_response_with_location():
    """Test make_tool_response includes location data."""
    response = make_tool_response(
        tool_name="test_tool",
        message="Test",
        city="Paris",
        start_date="2024-01-01",
        end_date="2024-01-31",
    )

    assert isinstance(response, dict)
    assert response["city"] == "Paris"
    assert response["start_date"] == "2024-01-01"
    assert response["end_date"] == "2024-01-31"
