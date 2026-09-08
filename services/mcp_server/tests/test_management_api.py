"""Tests for management API endpoints."""

from __future__ import annotations


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["service"] == "mcp-server"


def test_api_dashboard(client):
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["transport"] == "streamable-http"
    assert body["mcp_path"] == "/mcp"
    assert body["modules_total"] == 6
    assert body["tools_registered"] > 0


def test_api_dashboard_modules(client):
    response = client.get("/api/dashboard/modules")
    assert response.status_code == 200
    body = response.json()
    names = {m["name"] for m in body["modules"]}
    assert names == {
        "utility",
        "hazards",
        "weather",
        "imagery",
        "geospatial",
        "flood",
    }
    flood = next(m for m in body["modules"] if m["name"] == "flood")
    assert "get_terrazard_flood_briefing_tool" in flood["registered_tools"]
    assert any(d["name"] == "geospatial" for d in flood["module_dependencies"])
    assert any(c["name"] == "terrazard_database" for c in flood["connections"])
    assert "kind" in flood["connections"][0]
    assert "status" in flood["connections"][0]


def test_api_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"healthy", "degraded"}
    assert "utility" in body["modules"]


def test_dashboard_page(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert b"Metaplanet" in response.content
    assert b"/api/dashboard/modules" in response.content
