"""
Tests for WebSocket endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.api.models import LocationOption
from src.api.websocket import _patch_resume_state_with_confirmed_location


def test_websocket_connection():
    """Test WebSocket connection and acknowledgment."""
    client = TestClient(app)
    
    with client.websocket_connect("/ws/chat") as websocket:
        # Should receive connection acknowledgment
        data = websocket.receive_json()
        
        assert data["type"] == "connection_ack"
        assert "server_version" in data


def test_resume_patch_preserves_structured_tool_input():
    """When resuming, patch only location while preserving required fields."""
    pause_state = {
        "tool_input": {
            "start_date": "2026-02-24",
            "end_date": "2026-03-03",
            "location": "Dubai, United Arab Emirates",
            "radius_km": None,
        },
        "resume_patch": {"field": "location"},
    }
    resume_state = {
        "next_tool": "detect_fire_tool",
        # Legacy state shape can carry only a string marker.
        "next_input": "@osm_id:R4479752",
    }
    confirmed_location = LocationOption(
        name="دبي, الإمارات العربية المتحدة",
        coordinates=[25.0742823, 55.1885387],
        place_id=397136633,
        osm_id=4479752,
        osm_type="relation",
        osm_type_prefix="R",
    )

    _, patch_field = _patch_resume_state_with_confirmed_location(
        pause_state=pause_state,
        resume_state=resume_state,
        confirmed_location=confirmed_location,
    )

    assert patch_field == "location"
    assert isinstance(resume_state["next_input"], dict)
    next_input = resume_state["next_input"]
    assert next_input.get("start_date") == "2026-02-24"
    assert next_input.get("end_date") == "2026-03-03"
    assert next_input.get("radius_km") is None
    assert next_input.get("location") == "@osm_id:R4479752"


@pytest.mark.integration
def test_websocket_chat_request():
    """Test sending a chat request via the full orchestrator pipeline (requires MCP server)."""
    client = TestClient(app)
    
    with client.websocket_connect("/ws/chat") as websocket:
        # Skip connection ack
        websocket.receive_json()
        
        # Send chat request
        websocket.send_json({
            "type": "chat_request",
            "message": "Hello, agent!",
            "chat_history": [],
            "confirmed_locations": {},
            "document_context": None,
        })
        
        # Should receive status update
        status = websocket.receive_json()
        assert status["type"] == "status"
        assert status["stage"] == "planning"
        
        # Should receive complete message
        complete = websocket.receive_json()
        assert complete["type"] == "complete"
        assert "response" in complete
        assert complete["error"] is False


def test_websocket_invalid_json():
    """Test handling of invalid JSON."""
    client = TestClient(app)
    
    with client.websocket_connect("/ws/chat") as websocket:
        # Skip connection ack
        websocket.receive_json()
        
        # Send invalid JSON
        websocket.send_text("not valid json{")
        
        # Should receive error
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert "Invalid JSON" in error["message"]
        assert error["recoverable"] is True


def test_websocket_unknown_message_type():
    """Test handling of unknown message type."""
    client = TestClient(app)
    
    with client.websocket_connect("/ws/chat") as websocket:
        # Skip connection ack
        websocket.receive_json()
        
        # Send unknown message type
        websocket.send_json({"type": "unknown_type"})
        
        # Should receive error
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert "Unknown message type" in error["message"]
