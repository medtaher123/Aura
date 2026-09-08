"""
Tests for WebSocket endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from src.api.deps import get_current_user
from src.db.models.user import User
from src.main import app


@pytest.fixture
def ws_client():
    """Test client with WebSocket auth dependency stubbed."""

    async def override_get_current_user() -> User:
        return User(
            id="test_user",
            provider="test",
            email="t@t.com",
            username="tester",
        )

    app.dependency_overrides[get_current_user] = override_get_current_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_websocket_connection(ws_client):
    """Test WebSocket connection and acknowledgment."""
    with ws_client.websocket_connect("/ws/chat") as websocket:
        data = websocket.receive_json()

        assert data["type"] == "connection_ack"
        assert "server_version" in data


def test_websocket_requires_auth_when_enabled():
    """Unauthenticated WebSocket upgrades are rejected with HTTP 401."""
    client = TestClient(app)

    with pytest.raises(WebSocketDenialResponse) as exc_info:
        with client.websocket_connect("/ws/chat"):
            pass

    assert exc_info.value.status_code == 401
    assert b"Missing bearer token" in exc_info.value.content


@pytest.mark.integration
def test_websocket_chat_request(ws_client):
    """Test sending a chat request via the graph pipeline (requires MCP server)."""
    with ws_client.websocket_connect("/ws/chat") as websocket:
        websocket.receive_json()

        websocket.send_json({
            "type": "chat_request",
            "message": "Hello, agent!",
        })

        status = websocket.receive_json()
        assert status["type"] == "status"
        assert status["stage"] == "planning"

        complete = websocket.receive_json()
        assert complete["type"] == "complete"
        assert "response" in complete
        assert complete["error"] is False


def test_websocket_invalid_json(ws_client):
    """Test handling of invalid JSON."""
    with ws_client.websocket_connect("/ws/chat") as websocket:
        websocket.receive_json()

        websocket.send_text("not valid json{")

        error = websocket.receive_json()
        assert error["type"] == "error"
        assert "Invalid JSON" in error["message"]
        assert error["recoverable"] is True


def test_websocket_unknown_message_type(ws_client):
    """Test handling of unknown message type."""
    with ws_client.websocket_connect("/ws/chat") as websocket:
        websocket.receive_json()

        websocket.send_json({"type": "unknown_type"})

        error = websocket.receive_json()
        assert error["type"] == "error"
        assert "Unknown message type" in error["message"]
