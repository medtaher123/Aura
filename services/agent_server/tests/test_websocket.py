"""
Tests for WebSocket endpoint.
"""

import pytest
import json
from fastapi.testclient import TestClient
from src.main import app


def test_websocket_connection():
    """Test WebSocket connection and acknowledgment."""
    client = TestClient(app)
    
    with client.websocket_connect("/ws/chat") as websocket:
        # Should receive connection acknowledgment
        data = websocket.receive_json()
        
        assert data["type"] == "connection_ack"
        assert "server_version" in data


def test_websocket_chat_request():
    """Test sending a chat request."""
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
