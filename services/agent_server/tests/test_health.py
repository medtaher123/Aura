"""
Tests for health check endpoint.
"""

import pytest


def test_health_check(client):
    """Test that health check returns healthy status."""
    response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "healthy"
    assert data["service"] == "agent-server"
    assert "version" in data
    assert "uptime_seconds" in data
    assert "timestamp" in data
    assert "mcp_server_url" in data


def test_root_endpoint(client):
    """Test root endpoint returns service info."""
    response = client.get("/")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["service"] == "agent-server"
    assert "version" in data
    assert "endpoints" in data
    assert data["endpoints"]["health"] == "/health"
    assert data["endpoints"]["websocket"] == "/ws/chat"
