"""
Tests for MCP utility functions.
"""

import pytest
from utils.contracts import ToolCoordinates, ToolResponse


@pytest.mark.unit
def test_ToolResponse_basic():
    """Test ToolResponse creates valid response."""
    response = ToolResponse(tool_name="test_tool", message="Test message")

    assert isinstance(response, ToolResponse)
    assert response.tool_name == "test_tool"
    assert response.message == "Test message"






@pytest.mark.unit
def test_ToolResponse_with_location():
    """Test ToolResponse includes location data."""
    response = ToolResponse(
        tool_name="test_tool",
        message="Test",
        city="Paris",
        start_date="2024-01-01",
        end_date="2024-01-31",
        coordinates=ToolCoordinates(lat=48.8566, lon=2.3522),
    )

    assert isinstance(response, ToolResponse)
    assert response.city == "Paris"
    assert response.start_date == "2024-01-01"
    assert response.end_date == "2024-01-31"
    assert response.coordinates is not None
    assert response.coordinates.lat == 48.8566
    assert response.coordinates.lon == 2.3522
